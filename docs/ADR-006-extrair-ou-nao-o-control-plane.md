# ADR-006 — Extrair ou não o control plane de autoridade

**Status:** DECIDIDO pelo titular em 2026-10-26: **forma B'**. A palavra, literal: *"Decido o ADR-006 pela forma B': o estado da camada A vai para o etcd, lido por cada CORE, sem serviço separado agora."* A decisão e as condições antes do merge estão no **§9**; as seções 1 a 8 ficam como estavam em 2026-10-12, porque são a medição sobre a qual se decidiu.
**Decisão, execução e comprovação continuam estados distintos:** nenhuma linha da camada A saiu do CORE, e nenhum etcd foi instalado.
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

---

## 9. A decisão de 2026-10-26: forma B'

**Decidido pelo titular em 2026-10-26.** O estado da camada A (época, ativa, papéis e atestações vigentes) **vai para o etcd** e é **lido por cada CORE**. Não haverá serviço de control plane separado **agora**.

### 9.1 O que mudou desde 2026-10-12, e por que a forma B' surgiu

**No serviço, quase nada.** O inventário rodado em 2026-10-26 (`tools/control_plane_inventory.py`) dá as **mesmas 23 operações**, com 9 escritas e 14 leituras, as mesmas 4 UPDATEs no `promote()` e as mesmas 3 tabelas de camada A. O arquivo teve um commit desde 12/10 (`1f6e491`, 15/10) e foi de 763 para 791 linhas. O portão do control plane **passa** na main da CONSTRUTORA (`43c48be`).

**Em volta dele, a costura alargou:**
- dois chamadores novos da camada A: `authority_self_identity.py` (13/10, a rota whoami assinada: `ensure_state`, `role_of`) e `authority_replica.py` (25/10, o PASSO F: `ensure_state`, `instance_secrets`);
- a promoção virou **3 passos não atômicos**: o commit da camada A, a auditoria (`_audit`) e o empurrão da réplica (`authority_replica.empurrar`).

**Na evidência:**

| o que este ADR dizia em 12/10 | em 26/10 |
|---|---|
| A: "partição não resolve nada" (argumentado) | **medido**: dois escritores na mesma época (PRF-0309) |
| A: a Testemunha "continua réplica, e não testemunha" | **CLM-0006 PROVEN sem extração**, em laboratório com três processos e armazenamentos separados (PRF-0302/0306) |
| "CLM-0007 e UNK-0001 continuam abertas" | **CLM-0007 PROVEN** (PRF-0308); **UNK-0001 encerrada** pelo etcd (ADR-007) |
| o custo de B "ainda não medido" | **medido em parte**: o nó etcd custa cerca de 4× (PRF-0142); teto de 288 escritas por dia (PRF-0173); régua de fsync (PRF-0175). **A taxa de publicação não está medida** |
| — | **o P1_07B exige este ADR decidido** antes do merge (critério em `docs/2026-10-26-C2-C3-o-contrato-recusavel.md`) |
| — | **a cláusula C2.4 (autorização sem voto) está violada** até existir consenso (PRF-0309) |

**Por que B' e não B.** Quando este ADR foi escrito, "B" pressupunha um **serviço** extraído. Com o etcd escolhido (ADR-007), o árbitro externo já existe, e a camada A pode viver nele sem um processo novo entre o CORE e o etcd.

| | B (serviço extraído) | **B' (decidida)** |
|---|---|---|
| quem arbitra a época | o serviço, sobre consenso | **o etcd** |
| `enforce()` por publicação | leituras remotas ao serviço | leituras ao etcd, também remotas |
| `audit_events` e `build_dossier()` | entre sistemas | **continuam no banco do CORE**; só a camada A sai |
| processos novos para operar | o serviço e o etcd | **só o etcd** |
| P1_07B | se aplica | **se aplica**, porque o estado sai do processo do CORE |

**"Agora" é parte da decisão.** O serviço separado não foi recusado. Ele fica para quando houver motivo medido para tê-lo.

### 9.2 Condições ANTES do merge da troca da fonte da época

Nenhum código que mova a camada A para o etcd entra na main da CONSTRUTORA sem as cinco condições abaixo cumpridas e citadas no PR:

1. **A taxa de publicação medida.** O custo da B' é **por fato publicado**, porque o `enforce()` lê a época a cada publicação. Sem a taxa, não há orçamento honesto.
2. **A leitura da época no `enforce()` decidida e medida:** linearizável, ou cercada no efeito. Pela PRF-0182, a ordem das épocas não é conferida a jusante, e a correção do log sob partição continua estrutural **para a época** (C2.5).
3. **A atomicidade dos três passos do `promote()` desenhada, ou a janela declarada.** Hoje são commit, auditoria e réplica, cada um no seu tempo. Com o etcd, o commit da camada A passa a ser no etcd e a auditoria fica no banco do CORE.
4. **A porta da atestação mantida como pré-condição explícita, com teste.** O consenso não a preserva por si (CLM-0086, REFUTED pela PRF-0318). O teste é o do C5: `promote()` pelo etcd **recusando sem atestação**, e o split-brain da PRF-0309 **recusando o segundo escritor**.
5. **O destino da réplica do passo F decidido.** Com o etcd como fonte, `authority_state_replica` fica redundante: ou sai, ou passa a cache declarado da linha do etcd. Sem decisão, ela vira uma segunda fonte silenciosa.

**E uma condição de processo:** a troca precisa **provar que não tocou a regra de fencing**, rodando de novo, inteiros, os testes de fencing e de atestação, e comparando o veredito (roteiro, C5). Não existe stub de consenso no CORE a ser trocado: o cliente é escrito do zero.

### 9.3 O que esta decisão não autoriza

- **Não autoriza o merge**: só as cinco condições acima o autorizam.
- **Não instala o etcd** e não escolhe provedor nem host. O envelope (cauda, custo, jitter) continua pendente de host real (ADR-007 §5.1).
- **Não decide o serviço separado para sempre**: "agora" é parte da palavra.
- **O laboratório do C5 é medição, não extração.** O etcd em contêineres numa branch, para medir, não aciona o P1_07B, porque o critério fala de merge no CORE.
