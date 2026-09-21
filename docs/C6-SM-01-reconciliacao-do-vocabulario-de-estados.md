# C6-SM-01 — Reconciliação do vocabulário de estados

**Estado:** levantamento em 2026-09-21. Sem decisão, sem implementação. A decisão é do dono do kit.
**Por que agora:** o elo 4 é a primeira superfície em que uma autorização real vai existir. Se "AUTHORIZED" puder significar ao mesmo tempo *estado do fato* e *resultado do ato de autoridade*, a ambiguidade nasce onde é mais perigosa.

**Aviso de ordem:** o plano diz que esta decisão "vem antes do P1 do ANCHOR". O P1 do ANCHOR já entrou (ANCHOR #10, `8338fa0`) e a infraestrutura do elo 4 também (ANCHOR #11, `00deeb5`). Os dois usam vocabulário que este documento classifica — inclusive um termo que **eu** introduzi e que colide (§3.7). A decisão vai ter de reconciliar com o que já está em `main`, não só com o que vem.

## 1. Inventário — por padrão, não por nome

Método: enums do kit (`enum:` em todo `payload_schema` ACTIVE, listas de maiúsculas na Constituição e nos registries), `class X(Enum)` / `Literal[...]` / `*_STATES|STATUSES|VERDICTS|ROLES|DECISIONS` / dicionários de transição no código dos 15, e o `index.html` do liceu-shell. Excluídos: `tests/`, diretórios legados (`liceu-6-0/`, `liceu-stack/`, `cefeida-3c273/`, `john-monolith/`, `_review`). O que a varredura por padrão achou e a lista original não tinha está marcado **(novo)**.

### 1.1 Kit — contratos (`liceu_contract_registry.yaml`, versões ACTIVE)

| vocabulário | valores | escreve | lê |
|---|---|---|---|
| `archimedes.planning-state.state_status` | DRAFT, OBSERVATION, ANALYSIS, RECOMMENDATION, VALIDATED, AUTHORITATIVE, AUTHORITATIVE_OUTPUT, SUPERSEDED, REJECTED | ARCHIMEDES (`authority_kernel.AuthorityState`, idêntico) | CORE (boundary), consumidores do elo 1 |
| `opera.execution.execution_status` | CREATED, SCHEDULED, RUNNING, BLOCKED, COMPLETED, ROLLED_BACK, SUPERSEDED | OPERA (ninguém ainda: o OPERA não publica pelo SDK) | — |
| `anchor.authorization.decision` | GRANTED, DENIED | ANCHOR (`authorization_publisher`, #11) | OPERA (elo 5, futuro) |
| `legal.admissibility.legal_coverage` | COVERED, COVERED_WITH_CONDITIONS, UNCOVERED, NOT_APPLICABLE | JURIDICO (ninguém: não publica) | ANCHOR (referência), CORE (D-040 dossiê) |
| `cefeida.evidence.evidence_kind` | OBSERVATION, METRIC, FORECAST, ANOMALY, TREND, STATISTICAL_EVIDENCE | CEFEIDA (`evidence_publisher`, #37) | JOHN |
| `john.recommendation.mode` | CONSERVATIVE, BALANCED, AGGRESSIVE | JOHN | ANCHOR |
| `john.recommendation.rationale[].direction` | POSITIVE, NEGATIVE, NEUTRAL | JOHN | ANCHOR |
| `cea.financial-exposure.financial_viability` | viavel, revisar, inviavel **(novo; minúsculas, pt)** | CEA | — |
| `authority.human-decision.escalation_reason` | MOTHERS_UNAVAILABLE, UNRESOLVED_CONFLICT, INSUFFICIENT_EVIDENCE, CONSTITUTIONAL_RISK_LIMIT, MANUAL_EMERGENCY | humano via Testemunha | CORE |
| `authority.human-decision.reversibility` | REVERSIVEL, IRREVERSIVEL, PARCIAL **(novo)** | humano | CORE |
| `*.scale` / `territorial_scope` | LOCAL…INTERPLANETARIA / SITE…PLANETARY | todos | CORE (teto) |

### 1.2 Kit — registries e Constituição

| vocabulário | valores | escreve | lê |
|---|---|---|---|
| contrato `status` | ACTIVE, DEPRECATED, RETIRED | dono do kit | SDK (resolver: RETIRED bloqueia escrita), CORE (410) |
| `classification` (taxonomia de eventos) | AUTHORITATIVE_EVENT, DOMAIN_EVENT, COMMAND, QUERY, PROJECTION_EVENT, INTERNAL_EVENT, CERTIFICATION_EVENT, LEGACY, DEPRECATED, DEAD_CODE, FALSE_POSITIVE, FUTURE_CONTRACT **(novo)** | dono do kit (ledger) | ninguém em código |
| instância `status` (Producer Registry) | ACTIVE, PLANNED **(novo)** | dono do kit | publishers (instância conhecida) |
| `authority_role` | ACTIVE, SUCCESSOR, WITNESS (+ RETIRED no CORE) | CORE (`promote`) | CORE (`enforce`) |
| conformance | G1-ENVELOPE, G2-CONTRACT, G3-AUTHORITY, G4-SCHEMA, G5-LOCAL | kit | SDK (antes da rede), CORE (boundary) |
| G6 | BLOCKED, NOT_VERIFIABLE | Constituição (texto) | — |

### 1.3 CORE (`cv-backend-core`)

| vocabulário | valores | escreve | lê |
|---|---|---|---|
| fencing / control plane (`_reject` rules) | authority_identity_required, authority_instance_not_active, authority_role_forbidden, witness_cannot_authorize, authority_epoch_required, **authority_epoch_stale, authority_epoch_ahead**, authority_field_declared_in_payload, authority_epoch_not_monotonic, promotion_target_not_successor, promotion_requires_witness_attestation, only_witness_attests, attestation_verdict_invalid, attestation_epoch_stale, attestation_cannot_concur_on_both_down, witness_cannot_concur_own_promotion, attestation_target_not_successor | CORE | quem publica (409/403) |
| identidade do fato (#52) | event_id_collision_divergent_semantics | CORE | SDK (`CollisionError`) |
| `ATTESTATION_VERDICTS` | ACTIVE_HEALTHY, ACTIVE_DOWN, BOTH_DOWN | Testemunha (declara) | `promote` |
| escalação `status` | OPEN (único valor em código) **(novo)** | CORE | humano |
| resposta do publish | `idempotent: true/false`; `conformance.mode` ALERT/BLOCK; `violations` | CORE | SDK → `outcome` |
| `KANBAN_STAGES` | leads, negotiation, proposal, juridico, closed **(novo; minúsculas)** | CORE (projeção) | UI |
| `STRATEGIC_STAGES` | backlog, planning, executing, validating, done **(novo)** | CORE | UI |

### 1.4 SDK e publishers dos elos (0.12.x, #37/#52/#11)

| vocabulário | valores | escreve | lê |
|---|---|---|---|
| `PublishResult.outcome` | PUBLISHED, REPLAYED, UNKNOWN | SDK (do corpo) | publishers |
| `PublishOutcome.status` | PUBLISHED, REPLAYED, UNKNOWN, **BLOCKED** + `reason` / `owner` / `missing` | publishers (HUB, ARCHIMEDES, CEFEIDA, JOHN, ANCHOR) | passo manual, CLI |
| `reason` de BLOCKED | missing_authoritative_input, method_not_declared, source_missing, contract_cannot_carry, contract_not_confirmed, conformance_rejected, publish_failed, event_id_collision_divergent_semantics, policy_missing, scope_above_ceiling, self_authorization, legal_basis_unresolved, … | publishers | humano |
| `legal_coverage` no outcome do ANCHOR (#11) | UNCOVERED, **REFERENCED** **(novo — introduzido por mim; ver §3.7)** | ANCHOR | humano |

### 1.5 ARCHIMEDES

| vocabulário | valores | escreve | lê |
|---|---|---|---|
| `AuthorityState` (kernel) | os 9 do contrato | kernel | publisher |
| `ROOT_STATE_STATUSES` (repositório) | DRAFT, ANALYSIS, VALIDATED, AUTHORITATIVE, SUPERSEDED, REJECTED — **6, não 9** **(novo)** | repositório | kernel |
| `PromotionAct` / call site | PUBLISHED, REPLAYED, BLOCKED | call site | humano |

### 1.6 ANCHOR

| vocabulário | valores | escreve | lê |
|---|---|---|---|
| `earth_governance_runtime` `status` | AUTHORIZED, BLOCKED; `blocked_at` "JOHN DECISION" / "JURIDICOTECH"; `flow` JOHN DECISION → JURIDICOTECH → ANCHORS → AUTHORIZED → OPERA | runtime | `maintenance_service`, `router_core` (#10: agora sempre BLOCKED) |
| `_JURIDICOTECH_ALLOWED` | authorized, approved, allow, ok, true **(novo)** | runtime | runtime |
| `GateStatus` (john_decision_governance) | PASS, FAIL, PENDING, ERROR **(novo)** | runtime | runtime |
| `DecisionStatus` | APPROVED, BLOCKED, PENDING **(novo)** | runtime | runtime |
| `ValidationOutcome` (trust) | approved, blocked, degraded, quarantine **(novo)** | runtime | runtime |
| `MissionStatus` | PENDING, APPROVED, SIGNED, EXECUTABLE **(novo)** | federation/authority | runtime |
| `TrustTier` | sovereign, trusted, monitored, restricted, quarantine **(novo)** | runtime | runtime |
| `ConsensusState` | pending, quorum_reached, committed, rejected, timeout **(novo)** | runtime | runtime |
| `LEGAL_UNCOVERED` (#10) | `legal_coverage: UNCOVERED`, `owner: liceu.legal`, `legal_basis_refs: []` | `maintenance_service` | runtime, evento NATS |

### 1.7 OPERA

| vocabulário | valores | escreve | lê |
|---|---|---|---|
| `OperaTask.status` (`execution_engine`) | pending, blocked, executing, completed **(novo; minúsculas)** | OPERA | OPERA |
| contrato `execution_status` | CREATED, SCHEDULED, RUNNING, BLOCKED, COMPLETED, ROLLED_BACK, SUPERSEDED | (ninguém) | — |
| `john_next_action` (#10) | 503 BLOCKED missing_authoritative_input; timeline `opera.john.consulted` | OPERA | UI |

### 1.8 BIM, JURIDICO, ECONO, CEFEIDA, frontend

| vocabulário | valores | escreve | lê |
|---|---|---|---|
| BIM `TABLE_STATUSES` (catálogo RT) | PROPOSTA, VIGENTE | BIM | gate W89A |
| BIM `RT_STATUSES` | ACTIVE, SUSPENDED, REVOKED **(novo)** | BIM | BIM |
| BIM `PRStatus` | OPEN, APPROVED, REJECTED, MERGED **(novo)** | BIM | BIM |
| JURIDICO `RiskLevel` | LOW, MEDIUM, MEDIUM_HIGH, HIGH, CRITICAL **(novo)** | JURIDICO | JURIDICO |
| JURIDICO transições de contrato (2 máquinas: `backend/` e `apps/backend-api/`) | (dicionários; não lidos aqui) **(novo)** | JURIDICO | JURIDICO |
| ECONO `smart_contracts._STATES` | aguardando_iot, iot_confirmado, **anchor_validado, juridico_aprovado, econo_liberado**, pagamento_executado, cancelado **(novo)** | ECONO | ECONO |
| CEFEIDA `observe()` (#39) | Observation / BLOCKED no_observation, method_not_declared | CEFEIDA | passo manual |
| design-tokens `rules.json.status` | ACTIVE, PENDENTE | dono dos tokens | consumidores |
| liceu-shell "Estados do fato" | OBSERVADO → INTERPRETADO → EVIDENCIADO → ADMISSÍVEL → AUTORIZADO → EXECUTADO → VERIFICADO → ACEITO → OPERACIONAL → MANTIDO → RENOVADO (11) | (estático no HTML) | quem olha |
| liceu-shell `data-established` | true, false (R04: chip de época) | shell | `check.py` |

**Observação sobre o inventário:** a lista original tinha 6 vocabulários; a varredura achou 30+. Os que importam para o elo 4 são os das seções 1.1–1.4 e 1.6; os demais entram para que a ontologia não seja feita contra uma lista incompleta.

## 2. Classificação — cada termo em UMA dimensão

| dimensão | pergunta que responde | vocabulários que caem aqui |
|---|---|---|
| **fact_state** | o que aconteceu ao *registro* no store | PUBLISHED, REPLAYED (outcome do publish); SUPERSEDED (archimedes, opera); UNKNOWN (o produtor não leu) |
| **decision_result** | o que um ato de decidir/autorizar concluiu | GRANTED, DENIED (anchor); APPROVE/BLOCK/PRIORITIZE/WAIT (era CEFEIDA, removido); DecisionStatus APPROVED/BLOCKED/PENDING (anchor runtime); earth_governance AUTHORIZED/BLOCKED; MissionStatus APPROVED/SIGNED/EXECUTABLE; GateStatus PASS/FAIL |
| **authority_state** | quem tem autoridade agora | ACTIVE, SUCCESSOR, WITNESS, RETIRED; `authority_epoch`; ATTESTATION_VERDICTS; instância ACTIVE/PLANNED |
| **execution_state** | onde a execução física está | execution_status CREATED…ROLLED_BACK (contrato); OperaTask pending/executing/completed; TaskStatus do BIM; ECONO pagamento_executado |
| **lifecycle_state** | em que etapa da *vida do objeto* ele está | archimedes DRAFT…AUTHORITATIVE…; liceu-shell 11 estados; BIM PhaseStatus; PRStatus; KANBAN/STRATEGIC stages; ECONO `_STATES` (parcialmente) |
| **fencing_condition** | por que a fronteira recusou | authority_epoch_stale/ahead/required, authority_identity_required, …; event_id_collision_divergent_semantics; G1…G5; 410 contract_retired |
| **evidence_condition** | o que falta ou o que a evidência é | evidence_kind; BLOCKED reasons missing_authoritative_input, method_not_declared, source_missing, no_observation; G6 NOT_VERIFIABLE; ATTESTATION `BOTH_DOWN` (parcialmente) |
| **legal_coverage** | o que o direito diz sobre o sujeito | COVERED, COVERED_WITH_CONDITIONS, UNCOVERED, NOT_APPLICABLE |
| **knowledge_validity** | se um registro *vale* para uso (existência ≠ validade) | contrato ACTIVE/DEPRECATED/RETIRED; catálogo PROPOSTA/VIGENTE; RT ACTIVE/SUSPENDED/REVOKED; tokens ACTIVE/PENDENTE; `data-established` |

### 2.1 Termos que caem em DUAS dimensões — os achados

| termo | dimensão 1 | dimensão 2 | onde |
|---|---|---|---|
| **AUTHORIZED / AUTORIZADO** | *decision_result* (earth_governance `status: "AUTHORIZED"`; `_JURIDICOTECH_ALLOWED` "authorized") | *lifecycle_state* (liceu-shell "AUTORIZADO" como 5º estado do fato; ECONO `anchor_validado`) | ANCHOR, shell, ECONO |
| **BLOCKED** | *evidence_condition* (publishers: BLOCKED `missing_authoritative_input`), *decision_result* (ANCHOR `DecisionStatus.BLOCKED`, earth_governance), *execution_state* (contrato `execution_status: BLOCKED`, OperaTask `blocked`), *fencing* (G6 BLOCKED) | — quatro dimensões — | todos |
| **APPROVED** | *decision_result* (ANCHOR `DecisionStatus`, `MissionStatus`, `ValidationOutcome.approved`) | *lifecycle_state* (BIM `PRStatus.APPROVED`) | ANCHOR, BIM |
| **ACTIVE** | *authority_state* (papel da Mãe) | *knowledge_validity* (contrato, instância, RT, tokens) | kit, CORE, BIM, tokens |
| **PENDING / PENDENTE** | *decision_result* (GateStatus, DecisionStatus, MissionStatus) | *knowledge_validity* (tokens PENDENTE) | ANCHOR, tokens |
| **REJECTED** | *lifecycle_state* (archimedes REJECTED = planejamento recusado, é fato) | *fencing_condition* (recusa na fronteira = nunca vira fato) | ARCHIMEDES, CORE |
| **SUPERSEDED** | *fact_state* | *lifecycle_state* (archimedes) — aqui é o mesmo significado: um registro mais novo substitui | ARCHIMEDES, OPERA — **coincidem**, não colidem |
| **VERIFICADO** | *lifecycle_state* (shell, 7º estado) | *evidence_condition* ("verificado" como resultado de conferência) | shell |

**AUTHORIZED é o primeiro candidato e confirma-se:** no ANCHOR ele é o *resultado* de um ato (`status: "AUTHORIZED"` → `operator: "OPERA"`), no shell é uma *etapa da vida* do objeto. Um fato de autorização com `decision: GRANTED` põe o objeto em "AUTORIZADO"; um com `decision: DENIED` também é um fato de autorização — e o objeto não avança. Se o mesmo nome servir para os dois, "AUTHORIZED" no shell não distingue "houve ato" de "o ato concedeu".

## 3. Colisões

### 3.1 Mesmo nome, coisas diferentes
1. **AUTHORIZED** — resultado (ANCHOR) × etapa (shell) — §2.1.
2. **BLOCKED** — "falta insumo" (publishers), "recusado" (ANCHOR), "execução parada" (OPERA/contrato), "gate ausente" (G6). Quatro significados, um token. O do publisher e o do contrato do OPERA vão conviver **no mesmo fato** do elo 5.
3. **ACTIVE** — Mãe ativa × contrato ativo × instância ativa × RT ativa.
4. **REJECTED** — fato de planejamento recusado (existe no store) × recusa na fronteira (não existe no store).
5. **PENDING** — três enums do ANCHOR e o `PENDENTE` dos tokens.

### 3.2 Nomes diferentes, a mesma coisa
1. **GRANTED ≈ AUTHORIZED ≈ APPROVED ≈ approved ≈ authorized/allow/ok/true ≈ PASS ≈ anchor_validado** — sete grafias para "o ato concedeu". O contrato diz GRANTED; o runtime do ANCHOR diz AUTHORIZED e aceita cinco sinônimos em minúsculas (`_JURIDICOTECH_ALLOWED`); o ECONO grava `anchor_validado` sem ter lido o ANCHOR.
2. **DENIED ≈ BLOCKED (DecisionStatus) ≈ FAIL ≈ blocked ≈ REJECTED (PRStatus)** — para "o ato negou".
3. **execution_status do contrato × OperaTask.status** — CREATED/SCHEDULED/RUNNING/COMPLETED × pending/executing/completed: o OPERA tem dois vocabulários para a mesma execução, e o do contrato ninguém escreve.
4. **`ROOT_STATE_STATUSES` (6) × `AuthorityState` (9)** no ARCHIMEDES — o repositório não conhece OBSERVATION, RECOMMENDATION, AUTHORITATIVE_OUTPUT, que o contrato e o kernel conhecem. Um estado válido pelo contrato pode ser inválido para gravar.
5. **`financial_viability` viavel/revisar/inviavel** — decision_result em minúsculas e português, único contrato assim.

### 3.3 Um produtor afirmando o estado de outro
ECONO `_STATES`: `anchor_validado`, `juridico_aprovado` — a máquina de estados do ECONO **contém** resultados do ANCHOR e do JURIDICO como etapas suas, sem consumir fato algum deles. É `legal_coverage`/`decision_result` fabricado por nome de estado — a classe do P1 do ANCHOR, em outro repo.

### 3.4 O runtime que aceita sinônimos
`_JURIDICOTECH_ALLOWED = {"authorized", "approved", "allow", "ok", "true"}` no `earth_governance_runtime`: qualquer uma dessas strings, em minúsculas, conta como cobertura jurídica. Com o #10 o `maintenance_service` deixou de mandar `decision`; mas o endpoint `POST /earth/governance` (`router_maintenance`) ainda aceita `juridicotech_decision` do corpo e o runtime ainda o compara com essa lista.

### 3.5 O shell
Os 11 estados são uma **projeção** de várias dimensões numa linha só: OBSERVADO/INTERPRETADO/EVIDENCIADO (evidence_condition + fact_state dos elos 0–2), ADMISSÍVEL (legal_coverage), AUTORIZADO (decision_result do elo 4), EXECUTADO/VERIFICADO/ACEITO/OPERACIONAL/MANTIDO/RENOVADO (execution_state + lifecycle). Como linha única, não consegue mostrar "autorização DENIED" nem "cobertura NOT_APPLICABLE" — ambos são fatos, e nenhum tem lugar. Hoje o HTML mostra "ciclo OBSERVADO" estático (FE-R02: é o exemplo que vira implementação).

### 3.6 O G6
`enquanto_nao_existir: [BLOCKED, NOT_VERIFIABLE]` — BLOCKED aqui é fencing_condition (gate ausente), o quinto uso do token.

### 3.7 Colisão que eu introduzi (ANCHOR #11)
`PublishOutcome.legal_coverage` devolve **REFERENCED** quando há `legal_basis_refs` resolvidas. `REFERENCED` não é valor de `legal_coverage` no contrato (COVERED, COVERED_WITH_CONDITIONS, UNCOVERED, NOT_APPLICABLE) — é uma **condição de referência** (há refs que resolvem), não uma cobertura. Pus um termo de outra dimensão dentro do campo `legal_coverage`. É exatamente o erro que este documento existe para nomear; fica registrado para ser corrigido com a decisão (proposta em §4.3).

## 4. Proposta — ontologia com dimensões separadas e mapeamento

Não é união das listas nem terceiro vocabulário. É: **um termo pertence a uma dimensão; cada vocabulário existente é mapeado para a dimensão a que pertence; onde um vocabulário mistura dimensões, ele é decomposto — não renomeado.**

### 4.1 As dimensões e seus valores canônicos (os que já existem no kit, sem inventar)

| dimensão | valores canônicos | fonte |
|---|---|---|
| `fact_state` | PUBLISHED · REPLAYED · SUPERSEDED · UNKNOWN | SDK `outcome` + SUPERSEDED do contrato |
| `decision_result` | GRANTED · DENIED | `anchor.authorization.decision` |
| `authority_state` | ACTIVE · SUCCESSOR · WITNESS · RETIRED + `authority_epoch: int` | CORE |
| `execution_state` | CREATED · SCHEDULED · RUNNING · BLOCKED · COMPLETED · ROLLED_BACK · SUPERSEDED | `opera.execution.execution_status` |
| `lifecycle_state` | por objeto, definido pelo dono (archimedes 9; BIM; catálogos) — **não** unificado | contratos |
| `fencing_condition` | os códigos do control plane + `event_id_collision_divergent_semantics` + G1…G5 + `contract_retired` | CORE, kit |
| `evidence_condition` | `missing_authoritative_input` · `method_not_declared` · `source_missing` · `contract_cannot_carry` · … + `evidence_kind` | publishers, contrato |
| `legal_coverage` | COVERED · COVERED_WITH_CONDITIONS · UNCOVERED · NOT_APPLICABLE | `legal.admissibility` |
| `knowledge_validity` | ACTIVE · DEPRECATED · RETIRED (lei); PROPOSTA · VIGENTE (catálogo); … por registro, definido pelo dono | kit, BIM |

### 4.2 Regras da ontologia
1. **Um termo, uma dimensão.** `BLOCKED` fica **só** em `execution_state` (é do contrato do OPERA). Os publishers deixam de devolver `status: BLOCKED` e passam a devolver `status: NOT_PUBLISHED` com `condition: <evidence_condition | fencing_condition>` — ou mantêm BLOCKED **só** como `status` de resultado de publish, com o campo `condition` obrigatório nomeando a dimensão. (Escolha do dono; a segunda é menor.)
2. **Resultado de ato ≠ etapa.** `decision_result` só tem GRANTED/DENIED. AUTHORIZED, APPROVED, PASS, approved/allow/ok/true e `anchor_validado` **mapeiam** para GRANTED; DENIED, FAIL, blocked (como resultado), `DecisionStatus.BLOCKED` mapeiam para DENIED. `_JURIDICOTECH_ALLOWED` sai: cobertura é `legal_coverage`, lida de fato do `liceu.legal`, nunca de string.
3. **Etapa é do dono do objeto.** ARCHIMEDES mantém os 9; o repositório precisa aceitar os 9 (colisão 3.2.4). O shell **deriva** a etapa das dimensões, não a declara.
4. **Nenhum produtor carrega, como estado seu, o resultado de outro.** ECONO `anchor_validado`/`juridico_aprovado` viram `decision_result` e `legal_coverage` **lidos** de fatos, ou saem.
5. **Existência ≠ validade** (R-VALIDITY): `knowledge_validity` é dimensão própria; nenhum registro participa de decisão fora dos usos permitidos pelo seu estado de validade.

### 4.3 Mapeamento dos vocabulários existentes

| vocabulário existente | dimensão | mapeamento |
|---|---|---|
| ANCHOR earth_governance `status` AUTHORIZED/BLOCKED | decision_result | AUTHORIZED→GRANTED; BLOCKED→DENIED **+** `condition` dizendo por quê (`blocked_at`) |
| ANCHOR `DecisionStatus` APPROVED/BLOCKED/PENDING | decision_result | APPROVED→GRANTED; BLOCKED→DENIED; PENDING→ *não é resultado*: é ausência de fato (`fact_state` ausente) |
| ANCHOR `GateStatus` PASS/FAIL/PENDING/ERROR | evidence_condition | PASS/FAIL são resultado de gate (condição), não decisão; ERROR é fencing/infra |
| ANCHOR `MissionStatus` PENDING/APPROVED/SIGNED/EXECUTABLE | mistura decision_result + lifecycle | APPROVED→GRANTED; SIGNED/EXECUTABLE→lifecycle do objeto "missão" |
| ANCHOR `_JURIDICOTECH_ALLOWED` | — | **sai** (regra 2) |
| ANCHOR #11 `legal_coverage: REFERENCED` | — | **sai**: `legal_coverage` só com os 4 do contrato; "há refs resolvidas" vira campo próprio (`legal_basis_resolved: true/false`) — correção minha |
| OPERA `OperaTask.status` pending/blocked/executing/completed | execution_state | pending→CREATED; executing→RUNNING; blocked→BLOCKED; completed→COMPLETED (e o OPERA passa a usar o vocabulário do contrato) |
| publishers `status: BLOCKED` + `reason` | evidence_condition / fencing_condition | regra 1: `condition` explícito; `reason` já é o valor |
| ARCHIMEDES `ROOT_STATE_STATUSES` (6) | lifecycle_state | igualar aos 9 do contrato |
| ECONO `_STATES` | lifecycle + decision_result + legal_coverage misturados | decompor: `aguardando_iot/iot_confirmado/pagamento_executado/cancelado` ficam (lifecycle do contrato inteligente); `anchor_validado`→`decision_result` lido; `juridico_aprovado`→`legal_coverage` lido; `econo_liberado`→ decision_result do próprio ECONO |
| BIM PROPOSTA/VIGENTE, RT ACTIVE/SUSPENDED/REVOKED | knowledge_validity | mantêm; são o precedente da R-VALIDITY |
| kit contrato ACTIVE/DEPRECATED/RETIRED | knowledge_validity | mantém |
| CORE `authority_role` ACTIVE… | authority_state | mantém — e o token ACTIVE fica reservado a esta dimensão no envelope; nos outros lugares é `knowledge_validity`, campo com outro nome |
| tokens `PENDENTE` | knowledge_validity | mantém (não é decisão) |
| liceu-shell 11 estados | **projeção** | cada etapa é uma função das dimensões, tabela em §4.4 |
| `cea.financial_viability` viavel/revisar/inviavel | decision_result do CEA | mantém no contrato (SemVer); nota de que é o único em minúsculas |

### 4.4 O que a separação permite — o fato do elo 4

```
fact_state        = PUBLISHED                     (do outcome do SDK; REPLAYED se repetido)
decision_result   = GRANTED | DENIED              (payload.decision — do contrato)
authority_epoch   = <carimbado pelo CORE>         (envelope; invariante EPOCA, kit 0.12.1)
authority_state   = <papel de quem carimbou>      (envelope: authority_role/issuer, do control plane)
legal_coverage    = UNCOVERED                     (declarado; ou o valor do fato do liceu.legal referenciado)
legal_basis_resolved = false                      (campo próprio — não é cobertura)
execution_state   = —                             (não existe ainda: o elo 5 não publicou)
lifecycle (shell) = derivado: decision_result=GRANTED ∧ execution_state=∅ → "AUTORIZADO";
                    decision_result=DENIED → NÃO avança (e o shell precisa de um lugar para isso)
```

E o fato do elo 5, quando existir: `execution_state = RUNNING`, `fact_state = PUBLISHED`, `decision_result` **lido** do elo 4 (causation), nunca redeclarado — e `BLOCKED` só aqui.

### 4.5 Projeção do shell (esboço para a decisão)

| etapa do shell | condição nas dimensões |
|---|---|
| OBSERVADO | fato do elo 0 PUBLISHED |
| INTERPRETADO | fato do elo 1 PUBLISHED (state_status AUTHORITATIVE) |
| EVIDENCIADO | fato do elo 2 PUBLISHED |
| ADMISSÍVEL | `legal_coverage` ∈ {COVERED, COVERED_WITH_CONDITIONS} **lido**; UNCOVERED/NOT_APPLICABLE **não** põem aqui — e precisam de representação própria |
| AUTORIZADO | elo 4 PUBLISHED com `decision_result = GRANTED` |
| EXECUTADO | elo 5 com `execution_state = COMPLETED` |
| VERIFICADO … RENOVADO | fora da cadeia 5/5; dimensões ainda sem contrato |

Duas lacunas que a projeção expõe: **DENIED** e **UNCOVERED/NOT_APPLICABLE** são fatos sem etapa. A decisão precisa dizer se o shell ganha estados terminais ("NEGADO", "SEM COBERTURA") ou se mostra a dimensão em vez da etapa.

## 5. O que fica para decidir

1. `BLOCKED`: reservado ao `execution_state`, com os publishers migrando para `condition` explícito — ou mantido nos publishers com `condition` obrigatório.
2. `decision_result` fechado em GRANTED/DENIED em todo o ecossistema, com AUTHORIZED/APPROVED/PASS como **mapeamento**, não como valor.
3. `legal_coverage` só com os 4 do contrato; `REFERENCED` sai do ANCHOR #11 (correção minha, um PR).
4. ECONO `_STATES`: decompor (regra 4) ou registrar como dívida.
5. ARCHIMEDES repositório: 6 → 9.
6. Shell: estados terminais para DENIED e UNCOVERED, ou exibição por dimensão.
7. Onde a ontologia vive: seção nova da Constituição (`global.state_vocabulary`) ou documento do kit referenciado pelos contratos. A primeira é o ato mais pesado do ecossistema.

Nada implementado. PARE.

---

## Anexo A — regras registradas (sem implementar)

**FE-R02** — a interface não preenche, infere nem representa como estabelecido nenhum atributo de confiança, autoridade, evidência, assinatura, cobertura, lineage ou estado que não exista no fato de origem. Vale para mocks, Storybook e documentação: exemplo fictício plausível vira implementação.
*Implementação pendente (ao sinal):* `liceu-shell/scripts/check.py` falha se aparecer época literal, `"VERIFIED"` em assinatura, ou `confidence` literal em qualquer arquivo, inclusive mock. Hoje o `check.py` cobre R01/P03 (verbos de autoridade), R02/R05 (`data-value`), R04 (`data-established`), R07 (barra de proveniência) — não cobre literais de época/assinatura/confiança em mocks.
*Nota sobre a "seção 44":* o documento que mostra `mother-a` e `Epoch 1` como valores **não está** nos repositórios que tenho (`grep` em liceu-shell e liceu-design-tokens: zero) — não conferido. A regra vale igual: o shell lê os dois do fato, não do documento.

**R-VALIDITY** — existência não implica validade. Um registro participa de uma decisão só nos usos permitidos por seu estado de validade.
*Registro como proposta de emenda* (não altera a Constituição agora): hoje o JOHN não consulta catálogo nenhum; a regra é preventiva. O precedente em código é o BIM (`TABLE_STATUSES` PROPOSTA/VIGENTE; `RT_STATUSES` ACTIVE/SUSPENDED/REVOKED). A dimensão `knowledge_validity` desta ontologia é onde ela se codifica quando for a hora.
