# ADR-002 — Identidade do fato versus `event_id`

**Estado:** **DECIDIDO em 2026-09-21** (ver §Decisão). Proposta em 2026-09-20; corrigida em 2026-09-21 (o 409 que a primeira versão dava como existente não existia — ver §Contexto). As três saídas estão levantadas com custo; a escolha é de protocolo.
**Origem:** CORE #47, aberto pelo primeiro fato real (1/5, `docs/evidence/2026-09-20-primeiro-fato-1of5.md` no CORE).

```
PROBLEMA     o mesmo pedido, publicado duas vezes pelo SDK, virou DOIS fatos
CAUSA        a chave de idempotência do boundary é o event_id, e o SDK gera um novo a cada publish
INVARIANTE   "dois pedidos iguais são um pedido" — declarado no contrato, imposto por ninguém
```

## Contexto — o que o código faz hoje

**No CORE** (`cv-backend-core/app/main.py:1322`, `_federation_idempotency_key`):

```python
if payload.event_id:
    return f"event_id:{payload.event_id}"          # sempre este ramo para o SDK
semantic_fields = {event_type, producer, scope, artifact_id,
                   source_event_id, causation_id, trace_id, contract_version}
return f"semantic:{sha256(...)}"                   # nunca alcançado pelo SDK
```

Dois detalhes que pesam nas saídas: o ramo semântico existe, mas (a) só é alcançado quando o envelope não tem `event_id`, o que o SDK nunca produz, e (b) inclui `trace_id`, que o SDK também gera aleatório — logo, mesmo que fosse alcançado, não deduplicaria duas publicações do mesmo fato.

**O CORE NÃO tem 409 para colisão de `event_id`.** A primeira versão deste ADR afirmava o contrário, citando `_same_federation_semantics` (main.py:1341). Lido linha a linha, o caminho é outro:

- `_same_federation_semantics` compara `event_id, event_type, producer, scope, artifact_id, source_event_id, causation_id, trace_id, contract_version` — **não compara `payload` nem `payload_hash`**. Serve de filtro para devolver o registro existente como replay (main.py:5476–5500), não de guarda.
- `emit` (`orchestration_runtime.py:118–122` e `134–138`): chave de idempotência já existente → **devolve a linha antiga** com `_idempotent_replay = True`. Nenhuma comparação de conteúdo. Nenhum erro.
- `grep 409` em `main.py`: só card estratégico e workspace. O endpoint `/federation/events/publish` (main.py:5394) só levanta 422 e o status de rejeição do conformance.
- O teste que existe (`tests/test_liceu_db_core.py:329`) publica o MESMO corpo duas vezes, sem `event_id` — o ramo semântico, que o SDK nunca alcança.

Consequência: mesmo `event_id` com conteúdo diferente → HTTP 200, `idempotent: true`, e o registro devolvido é o **antigo**. O conteúdo novo é descartado em silêncio. O `CollisionError` do SDK (`liceu_federation_sdk.py:104`, tratamento em `:541`) trata um 409 que o CORE nunca emite.

Isto muda o peso das saídas: hoje o defeito é "dois fatos para um ato" (duplicata, visível no store). Com `event_id` determinístico e SEM guarda no CORE, o defeito vira "um ato novo com a mesma identidade some" (silêncio, invisível). **Qualquer saída que fixe a identidade precisa do 409 no CORE junto** — `idempotency_key` igual + `payload_hash` diferente → 409 — ou troca um defeito visível por um invisível.

**No SDK** (`liceu_federation_sdk.py:348`, kit 0.11.0 / federation_sdk 0.4.0): `"event_id": str(uuid.uuid4())`. `build_envelope(contract_id, payload, artifact_id, *, trace_id, lineage, observed_at)` — **não há parâmetro `event_id`**.

**Nos produtores:**

| produtor | como obtém `event_id` | consequência |
|---|---|---|
| HUB (elo 0, pelo SDK) | default do SDK: `uuid4` | o 1/5 real produziu dois fatos para `pr-6b8fe798-…` (`5ef423a3…` e `1ee7869e…`) |
| ARCHIMEDES (elo 1, pelo SDK) | **subclassa** o cliente (`DeterministicFederationClient`) e injeta `uuid5(producer\|contract\|state_id\|state_version\|content_hash)`; recomputa o fingerprint | já é a saída B — por fora do kit, porque o SDK não oferece o gancho |
| FORNECEDORES (pelo SDK) | default do SDK | mesma exposição do HUB |
| 6 com cliente httpx próprio (ANCHOR, CEA, ECONOTECH, …) | próprio, aleatório (ex.: CEA `EVT-{uuid4}`) | nenhuma saída no SDK os alcança até migrarem |

**Precedentes de identidade determinística já no ecossistema:** `planning_request_id = uuid5(holder_id, requested_at, requested_scope)` no HUB; `promotion_request_id = uuid5("elo1|…")` e o `event_id` acima no ARCHIMEDES. A ideia "mesmo ato → mesmo id" não é nova; falta ela viver no protocolo.

**Fatos já gravados em duplicata:** nenhum durável. O único par existe no Postgres do Codespace efêmero, já destruído; a evidência #50 registra os dois. Não há migração de dados a fazer hoje — há uma regra a fixar antes que existam.

**Regra de versão do kit** (`liceu_contract_registry.yaml`): SemVer estrito; MAJOR = campo obrigatório adicionado/removido ou tipo alterado (é a regra dos contratos; o SDK segue a mesma disciplina por analogia).

## As três saídas

### A — chave semântica no CORE

O boundary deriva a chave de idempotência de `(producer, contract_id, contract_version, artifact_id)` quando `artifact_id` existe, ignorando `event_id` para esse fim; `event_id` continua sendo a identidade do registro, não da deduplicação.

| | |
|---|---|
| muda | só o CORE (`_federation_idempotency_key`) — e o comportamento de aceite para os 15 produtores de uma vez |
| o que quebra | qualquer produtor que publique fatos DISTINTOS com o mesmo `artifact_id` passa a receber replay (200 idempotente) em vez de fato novo. Hoje o HUB usa `artifact_id = planning_request_id` e o ARCHIMEDES `archimedes_root_states:<id>:<versão>` — ambos identidade do fato. Para os 6 com httpx é preciso levantar contrato a contrato se `artifact_id` é identidade ou só referência; onde não for, A muda o significado sem aviso |
| MAJOR? | nem contrato nem SDK mudam de schema. Muda a **semântica de aceite do boundary** — merece bump do `boundary_checker` (1.1.0 → 2.0.0) e texto na Constituição: "identidade do fato = (produtor, contrato, versão, artifact_id)". Sem isso, é comportamento oculto |
| duplicatas existentes | ficam. Chaves antigas são `event_id:…`; uma nova publicação do mesmo `artifact_id` não casa com elas — sem migração de chaves, o primeiro publish pós-mudança seria um terceiro registro. Migração: recomputar `idempotency_key` das linhas existentes (hoje: zero linhas duráveis) |
| cobertura | **total** — alcança os 6 produtores httpx sem que migrem |
| o que não resolve | o SDK continua gerando `event_id` aleatório: replay vira indistinguível de fato novo para o produtor a menos que o kit #6 exponha `idempotent` |

### B — `event_id` determinístico no SDK

O SDK deriva `event_id = uuid5(NS, "{producer}|{contract_id}|{contract_version}|{artifact_id}")` por default, com parâmetro `event_id=` para o produtor sobrescrever (o gancho que o ARCHIMEDES teve de criar por subclasse). `artifact_id` vazio → erro, não `uuid4`: o envelope canônico já o exige (abaixo).

Ponto de desenho que a leitura "derivar do conteúdo" esconde: derivar de `payload_hash` faria dois payloads diferentes com o mesmo `planning_request_id` virarem dois fatos — o oposto do invariante. Derivar da **identidade** (`artifact_id`) faz o segundo publish com conteúdo divergente colidir na chave — e aí o CORE precisa **recusar (409)**, o que hoje ele não faz (ver §Contexto: devolve o antigo como replay). Sem esse 409, B é **pior** que o estado atual: a duplicata some, e com ela o conteúdo novo. B é, portanto, **duas mudanças**: derivação no SDK + guarda no CORE (`idempotency_key` igual, `payload_hash` diferente → 409). O SDK já está pronto para o 409 (`CollisionError`); o CORE não o emite. (O ARCHIMEDES inclui `content_hash` na derivação, o que faz conteúdo novo virar `event_id` novo — evita a colisão em vez de detectá-la; com o 409 no CORE, isso deixa de ser necessário.)

| | |
|---|---|
| muda | o SDK (`build_envelope`: derivação + parâmetro `event_id`) e, por consequência, todo produtor que o use ao atualizar o kit. **E o CORE**: guarda de 409 em `/federation/events/publish` (chave igual + `payload_hash` diferente), com teste — hoje inexistente |
| o que quebra | ARCHIMEDES: a subclasse `DeterministicFederationClient` vira redundante (remover; comportamento igual). HUB e FORNECEDORES: nada quebra — passam a receber replay onde hoje recebem duplicata. Testes que afirmam "dois publishes = dois `event_id`" (nenhum conhecido) |
| MAJOR? | assinatura: aditiva (parâmetro opcional) → MINOR. Semântica: o default muda de "cada publish é um fato" para "cada identidade é um fato" — é exatamente a correção, mas é mudança de comportamento observável. Proposta honesta: **federation_sdk 0.4.0 → 0.5.0 com changelog explícito**, e a Constituição ganhando a frase da identidade. Se o critério for "comportamento default mudou", é MAJOR (1.0.0). A decisão de rótulo é do dono do kit |
| duplicatas existentes | ficam (event_ids diferentes); o invariante vale a partir da versão. Zero duráveis hoje |
| cobertura | **só os produtores no SDK** (3 hoje, 5 ao fim do ciclo 5). Os 6 httpx continuam aleatórios até migrar — o que já é o plano |
| o que exige junto | kit **#6** (`PublishResult.idempotent`/`conformance`) — sem ele, o produtor recebe 200 nos dois casos e o HUB/ARCHIMEDES continuam rotulando fato novo como `REPLAYED` (ARCHIMEDES #26, HUB #9) |

### C — invariante no consumidor

O boundary fica permissivo; quem lê deduplica por `artifact_id` (ou pelo id de domínio do contrato).

| | |
|---|---|
| muda | cada consumidor, por contrato: ARCHIMEDES lendo pedidos (elo 1), CEFEIDA lendo estados (elo 2), JOHN lendo evidências (elo 3), ANCHOR, OPERA… n consumidores × n contratos |
| o que quebra | nada hoje — e é o problema: nada obriga |
| MAJOR? | nada muda no protocolo. A garantia deixa de ser do protocolo |
| duplicatas existentes | ficam e **crescem**: o store canônico passa a conter N registros por fato, para sempre |
| lineage | `causation_id` do elo seguinte aponta para UM dos N `event_id` do fato anterior. Dois atos do elo 1 sobre "o mesmo pedido" podem ter lineage diferente — a ambiguidade que o #47 descreve, institucionalizada |
| cobertura | total no papel; na prática, a de cada consumidor |

## Comparação em uma tela

```
                        A · CORE          B · SDK             C · consumidor
onde muda               boundary          kit                 cada leitor
alcança os 6 httpx      sim               não (até migrar)    depende de cada um
MAJOR                   boundary 2.0      SDK 0.5 ou 1.0      nenhum
duplicatas existentes   migrar chaves     ficam               ficam e crescem
garantia é do protocolo sim               sim (p/ SDK)        não
precedente no código    ramo semântico    ARCHIMEDES subclasse  —
depende do kit #6       para o produtor   para o produtor     —
risco principal         artifact_id que   payload≠ c/ mesmo   lineage ambíguo
                        não é identidade  id → replay MUDO    por desenho
                                          (409 não existe;
                                          exige CORE junto)
```

A e B não são excludentes: B fixa a identidade na origem; A a reconheceria também para quem ainda não fala SDK. Se as duas forem adotadas, a chave de A e a derivação de B têm de ser **a mesma função** sobre os mesmos campos — senão o ecossistema terá duas definições de "mesmo fato".

## O que fica em aberto para quem decide

1. Qual é a identidade do fato: `(producer, contract_id, contract_version, artifact_id)`? Ou o contrato declara o campo de identidade (`identity_field: planning_request_id`)? A segunda é mais honesta e mais cara (muda o schema do registry — 10 contratos, MINOR cada). A primeira já está escrita: a Constituição nomeia `contract_id + contract_version + artifact_id` como o invariante do envelope canônico (`liceu_constitution.yaml:531`), e o `boundary_check` o exige de todo produtor (`liceu_boundary_check.py:263`, `CAMPOS_ENVELOPE_OBRIGATORIOS`). Escolher a primeira é dar efeito ao que já é regra; a segunda cria uma segunda regra.
2. ~~Contratos sem `artifact_id`~~ — **a pergunta se desfaz**: `artifact_id` é campo do **envelope**, obrigatório em todos os contratos (`build_envelope(contract_id, payload, artifact_id, …)`, posicional; nenhum dos 10 `payload_schema` o declara porque não é do payload). O que varia é **o que cada produtor põe nele**: HUB usa `planning_request_id` (`planning_request_publisher.py:312`); ARCHIMEDES usa `archimedes_root_states:<state_id>:<state_version>` (`planning_state_publisher.py:306`) — a versão faz parte da identidade, logo SUPERSEDED é fato novo, como deve. A pergunta real é: o kit fiscaliza que `artifact_id` seja identidade estável do ato (e não referência ou aleatório)? Hoje não — e é onde A "muda o significado sem aviso" para os 6 httpx.
3. Rótulo de versão para B: 0.5.0 (aditiva) ou 1.0.0 (default mudou).
4. O kit #6 entra na mesma versão? Sem ele, B resolve o store e não resolve o produtor.
5. **O 409 no CORE** entra antes, junto ou depois? Antes ou junto: senão há uma janela em que a colisão é silenciosa. É um PR no CORE (guarda + teste "mesmo `event_id`, `payload_hash` diferente → 409"), independente da saída escolhida — vale até para C.

## Decisão (2026-09-21, dono do kit)

**1. Saída B, com a guarda no CORE.** O kit deriva `event_id` da identidade do fato. O CORE **não** deriva — aplica:

```
kit    event_id = uuid5(FACT_IDENTITY_NAMESPACE, producer_id|contract_id|contract_version|artifact_id)
CORE   chave igual + payload_hash igual      → replay, 200, idempotent: true
       chave igual + payload_hash diferente  → 409, com motivo nomeado
```

Por que B+guarda e não A+B: com A+B haveria duas funções calculando identidade — uma no kit, uma no CORE — e mesmo escritas iguais divergiriam no primeiro ajuste. Com B+guarda existe **uma** definição (no kit); o CORE só verifica consistência de conteúdo sob a chave que recebe. É a leitura estrita de "a mesma função sobre os mesmos campos": a forma de garantir isso é haver uma. Os 6 produtores httpx seguem com `event_id` aleatório até migrar ao SDK — não piora nada: estão em ALERT e o inventário do C1 já os lista.

Teste obrigatório: o mesmo ato duas vezes → 200 + `idempotent: true` no segundo, mesmo `event_id`; ato diferente com a mesma identidade → 409, e nada gravado.

**2. Identidade = a tupla do envelope, que já é constitucional** (`liceu_constitution.yaml:531`). O campo declarado por contrato exigiria schema novo no registry, MINOR em 10 contratos, o SDK lendo do payload e a revogação da tupla no mesmo ato — flexibilidade que nenhum contrato atual demonstrou precisar. Se um contrato futuro provar que a tupla não serve, a mudança é emenda constitucional que revoga a tupla no mesmo ato. Nunca duas regras convivendo.

**3. Rótulo: próxima MINOR (federation_sdk 0.5.0, pacote 0.12.0). Não 1.0.0.** A 1.0.0 declara estabilidade; hoje a regra de identidade acabou de ser decidida, 6 produtores não usam o SDK e a cadeia está em 1/5. Fica para quando os 5 elos publicarem pelo SDK com a regra provada em produção. **O kit #6 entra na mesma tag**: B sem ele é invisível — o produtor recebe 200 nas duas publicações e não distingue fato novo de replay.

**Ordem de execução:** (1) kit 0.12.0 — `event_id` por identidade + #6; (2) CORE — guarda 409 com teste; (3) bumps ARCHIMEDES, HUB, FORNECEDORES, CORE; (4) elo 2 depois de 1–3 em `main`. **A tag do kit não é consumida antes de (2) estar em `main`**: sem a guarda, o primeiro bump passa a descartar ato novo em silêncio.

O ARCHIMEDES remove a subclasse `DeterministicFederationClient` no bump; o HUB e o ARCHIMEDES passam a rotular `PUBLISHED`/`REPLAYED` pelo corpo (`PublishResult.outcome`), fechando ARCHIMEDES #26 e HUB #9.
