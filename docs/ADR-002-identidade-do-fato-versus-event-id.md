# ADR-002 — Identidade do fato versus `event_id`

**Estado:** proposta em 2026-09-20. Sem decisão. As três saídas estão levantadas com custo; a escolha é de protocolo.
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

O CORE já tem a proteção complementar: mesmo `event_id` com semântica divergente é **409** (`_same_federation_semantics`, main.py:1341; `CollisionError` no SDK). Ou seja, o boundary sabe recusar "dois conteúdos com a mesma identidade"; o que ele não sabe é reconhecer "o mesmo conteúdo com duas identidades".

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

O SDK deriva `event_id = uuid5(NS, "{producer}|{contract_id}|{contract_version}|{artifact_id}")` por default, com parâmetro `event_id=` para o produtor sobrescrever (o gancho que o ARCHIMEDES teve de criar por subclasse). Sem `artifact_id` → `uuid4`, explicitamente: quem não declara identidade não recebe deduplicação.

Ponto de desenho que a leitura "derivar do conteúdo" esconde: derivar de `payload_hash` faria dois payloads diferentes com o mesmo `planning_request_id` virarem dois fatos — o oposto do invariante. Derivar da **identidade** (`artifact_id`) faz o segundo publish com conteúdo divergente cair no **409 que o CORE já tem**. O 409 é o que torna a saída B segura: colisão de identidade com conteúdo diferente é recusada, não silenciada. (O ARCHIMEDES inclui `content_hash` porque seu `artifact_id` já carrega a versão; com a derivação por identidade, o resultado é o mesmo.)

| | |
|---|---|
| muda | o SDK (`build_envelope`: derivação + parâmetro `event_id`) e, por consequência, todo produtor que o use ao atualizar o kit |
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
                        não é identidade  id → 409 (certo)    por desenho
```

A e B não são excludentes: B fixa a identidade na origem; A a reconheceria também para quem ainda não fala SDK. Se as duas forem adotadas, a chave de A e a derivação de B têm de ser **a mesma função** sobre os mesmos campos — senão o ecossistema terá duas definições de "mesmo fato".

## O que fica em aberto para quem decide

1. Qual é a identidade do fato: `(producer, contract_id, contract_version, artifact_id)`? Ou o contrato declara o campo de identidade (`identity_field: planning_request_id`)? A segunda é mais honesta e mais cara (muda o schema do registry).
2. Contratos sem `artifact_id` obrigatório: não deduplicam (explícito) ou passam a exigir?
3. Rótulo de versão para B: 0.5.0 (aditiva) ou 1.0.0 (default mudou).
4. O kit #6 entra na mesma versão? Sem ele, B resolve o store e não resolve o produtor.

Sem implementação até a decisão. O ARCHIMEDES continua com a subclasse; o HUB continua exposto — e o elo 2 (CEFEIDA) não deve publicar sem que isto esteja decidido, ou nasce com o mesmo defeito.
