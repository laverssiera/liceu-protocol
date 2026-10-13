# ADR-006 — Extrair ou não o control plane de autoridade

**Status:** PROPOSTO.
**Numeração:** o `ADR-005` está reservado para a topologia, como o plano do ciclo 25 o nomeia; este veio depois na numeração e antes no tempo.

**O que já foi decidido, e o que isto não é.** O titular decidiu em 2026-10-09: *"Control plane extraído, só a camada A"*, com a Opção B do `ADR-003` e três domínios votantes. Pela regra final do mesmo dia — *"decisão, execução e comprovação são estados distintos"* — **este ADR não registra essa decisão como executada**. Ele mede o que ela custa, nomeia o que ela ainda não decidiu, e inclui a opção de **não extrair**, porque sem ela a comparação não é comparação.

---

## 1. Por que este ADR começa com medição e não com leitura

A contagem anterior deste mesmo serviço dizia **10 escritas e 6 leituras SQL**. Ela era minha, e duas das três partes estavam erradas: o "10" somava `db.commit()` como escrita, e o "6" não corresponde a nada reproduzível. Extrair com base nela seria mover uma lista que ninguém mediu.

O instrumento é `cv-backend-core/tools/control_plane_inventory.py`. Cada operação se declara por **função mais âncora de texto**, e a linha é derivada por árvore sintática a cada execução — número de linha é derivável do código, e campo derivável escrito à mão nasce com defasagem garantida. Âncora que não casa exatamente uma vez **falha fechado**: o inventário se recusa a medir linha de que não tem certeza, porque medir a linha errada reporta cobertura que não existe.

**Escopo declarado da medição** — `padrão`: toda chamada `db.*` resolvida pela AST, mais atribuição a atributo de objeto carregado; `universo`: `app/services/authority_control_plane.py`, 763 linhas, ref `main`; `excluídos`: as rotas que chamam o serviço e os modelos em `app/models/`, que são outra superfície; `instrumento`: `ast.walk` mapeando cada `Call` para a função dona pela faixa `lineno`/`end_lineno`.

---

## 2. O que existe hoje — 23 operações, e quatro delas invisíveis

```
operações 23 · escritas 9 (5 INSERT + 4 UPDATE) · leituras 14
tabelas 6 · tabelas de camada A 3 · operações de camada A 17 · escritas de camada A 7
```

A aritmética fecha, que é o único jeito de saber que nenhuma linha se perdeu: 24 acessos `db.*` = 5 `add` + 5 `commit` + 5 `get` + 5 `query` + 4 `refresh`. Os 5 `commit` são fronteira de transação, não operação; as 4 UPDATEs não são chamada nenhuma — são atribuição.

**E é aí que está o achado.** `promote()` não chama `db.add` uma única vez. Ela carrega objetos com `db.get`, muda atributos e fecha tudo num `db.commit()`:

| o que muda | tabela |
|---|---|
| `old.role = "RETIRED"`, `old.role_since_epoch` | `authority_instances` |
| `target.role = "ACTIVE"`, `target.role_since_epoch` | `authority_instances` |
| `state.authority_epoch`, `active_instance_id`, `issuer_instance_id` | `authority_state` |
| `attestation.consumed_by_epoch` | `authority_attestations` |

Essas três tabelas são **exatamente** a camada A, pela definição literal do `ADR-003` §B: *"o estado de arbitragem (época, ativa, papéis, atestações vigentes)"*. Ou seja: **a superfície de escrita da camada A inteira são quatro UPDATEs dentro de uma função, num commit, sem um `db.add` para denunciar que existem** — e é a transição de autoridade, a escrita mais consequente do sistema.

Qualquer inventário que conte `db.add` acha zero delas.

---

## 3. A costura: onde ela passa

**A propriedade das tabelas particiona limpo por função. Nenhuma função toca as duas camadas.**

| | funções | operações |
|---|---|---|
| **movem** (só camada A) | `promote`, `ensure_state`, `attest`, `role_of`, `snapshot`, `valid_attestation_for`, `list_attestations` | 17 |
| **ficam** (nada de camada A) | `_audit`, `escalate_to_human`, `_latest_fact`, `list_escalations` | 6 |

Isso é favorável, e é mais do que se esperava: a costura não corta nenhuma função pelo meio.

**O grafo de chamadas, porém, atravessa a costura três vezes — e só num sentido:**

```
attest()   -> _audit()
promote()  -> _audit()
promote()  -> escalate_to_human()
```

**Zero travessias no sentido inverso.** Quem fica nunca chama quem move. A dependência através da costura é **acíclica**, o que é a diferença entre uma extração e um emaranhado.

**Duas fronteiras merecem nome:**

- **`enforce()` está no caminho quente.** Ela é chamada a cada fato federado publicado (`app/main.py`, na rota de publicação) e usa `ensure_state` e `role_of` — as duas do lado que move. Extrair transforma **toda publicação em duas leituras remotas**. É a preocupação do `ADR-003` §5 deixada de abstrata.
- **`build_dossier()` se parte.** Ela lê `list_attestations` e `snapshot` (movem) e `_latest_fact` (fica). Viraria junção entre dois sistemas.

**O raio dentro do monólito é estreito:** um único arquivo chamador, `app/main.py`, com 7 símbolos — e um deles é `_aware`, função **privada** usada de fora. As dependências que a extração carregaria são três: `app.config.settings`, `app.models.authority`, `app.models.orchestration`.

---

## 4. A promoção são duas transações, não uma

`promote()` comita a camada A, e **depois** `_audit()` abre transação própria (`db.add` + `db.commit`). Se o processo morrer entre as duas, **a transição de autoridade é durável e o registro de auditoria nunca existe**.

Isso já é verdade hoje, sem extração nenhuma. Mas a extração piora a forma do problema: `audit_events` não é camada A, então o split deixa de ser entre dois commits do mesmo banco e passa a ser **entre dois sistemas** — e `_audit()` é chamada por quatro funções (`_reject`, `attest`, `escalate_to_human`, `promote`), o que significa que nenhum chamador que queira atomicidade com a própria auditoria pode tê-la.

---

## 5. A cobertura de caracterização, e o portão

**Cobertura por execução é a métrica errada, e ela dava 23/23.** `sys.monitoring` sobre os testes de autoridade mostra que a suíte percorre todas as 23 operações. Isso não diz nada: linha executada só prova que o interpretador esteve ali.

Caracterizada é a operação cujo **efeito** está preso. A única forma de medir é mudar e ver se alguém grita. O portão (`tools/control_plane_gate.py`) roda **uma mutação por operação**, serialmente, com o banco apagado antes de cada execução para que mutação que corrompe estado não vire "detectada" por contágio.

**Primeira medição: 17/23.** Seis operações mudaram de efeito com a suíte inteira verde.

| op | o que ficou solto |
|---|---|
| **W02** | a semeadura gravava `role_since_epoch=99` e ninguém reclamava — e esse campo é a auditoria de promoção |
| **R02** | o guarda que impede semeadura duplicada só é alcançável com estado ausente e instâncias de pé (restauração parcial), e nada exercitava esse caso |
| R11–R14 | `db.refresh` depois de `commit` |

**Duas foram caracterizadas** em `tests/test_control_plane_characterization.py`, e as duas estão em `ensure_state()`, que é a função que **cria** as linhas da camada A. O teste de `R02` prende um caminho de recuperação que não estava coberto nem documentado.

**Quatro foram declaradas NÃO-CARACTERIZÁVEL, com a razão medida:**

1. `app/database.py:12` chama `sessionmaker(autocommit=False, autoflush=False, bind=engine)` **sem passar `expire_on_commit`**, que portanto vale `True`. Depois do commit os atributos estão expirados e qualquer leitura os recarrega sozinha: o `refresh` muda **quando** o SELECT sai, não **o que** o chamador observa.
2. Todo leitor lê com a sessão **aberta**: `get_db` fecha no `finally`, depois de o handler retornar, e o único leitor externo é `app/main.py` na rota de `attest`, dentro do handler.
3. A linha de `escalate_to_human` **nunca sai do serviço** — medido que nenhum chamador fora do módulo usa a função.

**A categoria é verificada nos dois sentidos**, e é isso que a torna honesta: operação fora da lista tem de ser **pega**; operação dentro da lista tem de **não** ser pega. Declaração falsa **falha o portão** — o rótulo não é estacionamento. E a categoria é estreita por teste: **escrita não pode entrar nela**, porque escrita que não se caracteriza não é "sem efeito", é buraco.

**Resultado:** `19/19 das caracterizáveis` · `4 declaradas sem efeito observável, 4 confirmadas pela mutação` · **PORTÃO ABERTO**.

O portão **falha fechado** em cinco situações, nenhuma degradando para aviso: inventário defasado · operação sem mutação declarada · linha de base vermelha · declaração de não-caracterizável falsa · caracterização abaixo de 100% das caracterizáveis.

**Um limite declarado:** a caracterização corre em SQLite (`test_cv_backend_core.db`). Semântica de transação, bloqueio e concorrência do Postgres **não** está caracterizada por estes testes. O repositório tem um job separado contra Postgres real, mas ele só exercita `bootstrap_database()` e `/ready`.

---

## 6. As opções

### A — não extrair

Mantém o control plane como módulo do CORE, no mesmo banco.

| | |
|---|---|
| época e fencing | continuam como hoje: `enforce()` lê `authority_state` no mesmo processo, sem rede |
| partição | **não resolve nada**: duas Mães sem árbitro continuam possíveis, que é a razão de o `ADR-003` existir |
| Testemunha | continua lendo o mesmo armazenamento da Ativa — pelo §4 do `ADR-003`, continua **réplica e não testemunha** |
| as duas transações | continuam duas, no mesmo banco: recuperável por inspeção |
| custo | zero |
| o que ganha | o tempo que a extração consumiria, e nenhuma leitura remota no caminho quente |

**A não é uma opção vazia.** Ela é a única que não gasta nada, e a `CLM-0006` (*"a Testemunha observa a Ativa de forma independente"*) está hoje **STALE** e não REFUTED — ou seja, o que se sabe sobre a Testemunha é *não se sabe*, não *é falso*. A pressa de extrair não se apoia em medição nova.

### B — extrair só a camada A (a decidida)

| | |
|---|---|
| costura | limpa por função, acíclica, 3 travessias num sentido |
| `enforce()` | **2 leituras remotas por publicação** — o custo que o `ADR-003` §5 previu, agora localizado |
| `build_dossier()` | junção entre dois sistemas |
| as duas transações | passam a ser **entre sistemas** |
| camada A | 17 operações, 7 escritas, 3 tabelas |
| o que ganha | o árbitro único de época; e, pela Opção B do `ADR-003`, a Testemunha passa a observar o **protocolo** e não o armazenamento da Ativa — é o único caminho medido que faz dela testemunha |
| custo | **ainda não medido**; é o C25-04, com amplificação de escrita, latência de `fsync` no alvo real e crescimento por época |

### C — extrair o serviço inteiro

| | |
|---|---|
| costura | desaparece: as 3 travessias viram internas |
| `audit_events` e `event_log` | iriam para o cluster de consenso, e **não são estado de arbitragem** — é pôr histórico num log replicado que o `ADR-003` §3 recusou para C |
| custo | o de B mais o volume de auditoria, que cresce por rejeição e não por época |
| o que ganha | atomicidade entre promoção e auditoria |

**C compra a atomicidade pelo preço errado.** O problema das duas transações se resolve sem mover o histórico — e a forma disso é decisão de desenho, não desta ADR.

---

## 7. O que a medição muda na base da decisão

A decisão de 2026-10-09 foi tomada sem estes números. A medição **não a contradiz** — a costura é mais limpa do que se supunha — e acrescenta três coisas que não estavam na mesa:

1. **As quatro escritas invisíveis de `promote()`.** Extrair sem elas no inventário seria extrair sem saber o que move.
2. **`enforce()` no caminho quente.** O custo de B não é um custo de promoção (raro); é um custo **por fato publicado**. Isso é entrada obrigatória do C25-04.
3. **As duas transações.** B as transforma em cross-system, e isso é um defeito novo que a extração **cria**, não um que ela conserta.

Nenhuma das três recomenda reverter a decisão. Todas as três mudam o que a execução precisa resolver antes de começar.

---

## 8. O que este ADR não decide

- **Não recomenda extrair agora.** O portão está aberto, o que remove o impedimento — não cria a obrigação. O custo de B é a pergunta do C25-04, e `CLM-0007` e `UNK-0001` continuam abertas.
- **Não decide as quatro `refresh`.** Dados os chamadores de hoje elas são redundantes; se algum dia alguém devolver essas linhas para fora da sessão, deixam de ser. Removê-las amarraria a correção a *"nenhum chamador desanexa"*, calado. Mantê-las é a escolha conservadora, e quem decide é o titular.
- **Não decide o acoplamento de `_aware`.** Função privada usada de fora é dívida nomeada aqui, não resolvida.
- **Não caracteriza semântica de Postgres.** Declarado em §5 como limite, não como cobertura.
- **Não extraiu nada.** Nenhuma linha do control plane mudou neste trabalho: o que entrou foram inventário, portão, dois testes de caracterização e este documento.
