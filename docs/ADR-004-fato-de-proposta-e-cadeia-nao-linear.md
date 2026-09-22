# ADR-004 — O fato de proposta e a cadeia não linear

**Estado:** DECIDIDA em 2026-09-21 pelo dono do kit (§8). Implementação: kit 0.14.0 → boundary do CORE → ARCHIMEDES → bumps → um Codespace.
**Origem:** tentativa de disparar o elo 1 num CORE real (ciclo 6). Parou antes de subir ambiente: o kernel do ARCHIMEDES exige evidência para promover, e a evidência do CEFEIDA exige um fato publicado do ARCHIMEDES para existir. Circular na primeira volta.

```
PROBLEMA     ARCHIMEDES precisa de evidence_refs para promover a AUTHORITATIVE
             (kernel W89B3); só AUTHORITATIVE publica no elo 1; o CEFEIDA só
             evidencia o que foi publicado (fronteira: não lê o banco alheio).
             Primeira volta: ninguém consegue começar.
CAUSA        a cadeia foi declarada linear (posicao_na_cadeia 1→5) e a evidência
             volta: ela é insumo do elo 1, não só saída para o elo 3.
NÃO É        defeito do kernel. "Sem evidência não há ato" é regra correta e fica.
```

## 1. O que o código diz

### 1.1 O kernel do ARCHIMEDES exige evidência em toda promoção

`runtime/authority_kernel.py`, `_validate_request` (`:243–279`), para **qualquer** transição (ANALYSIS→VALIDATED inclusive):

```
"evidence is required"        if not request.evidence_refs        (:255)
"lineage is incomplete"       se falta qualquer LINEAGE_FIELD
"content hash mismatch"       provenance.content_hash != gravado
"invalid transition"          fora de AUTHORIZED_TRANSITIONS
```

`AUTHORIZED_TRANSITIONS` (`archimedes_state_repository.py:14`): DRAFT→{ANALYSIS, REJECTED}; ANALYSIS→{VALIDATED, REJECTED}; VALIDATED→{AUTHORITATIVE, REJECTED}; AUTHORITATIVE→{SUPERSEDED}.

O call site (`planning_state_call_site.py:270–274, :350`) tira `evidence_refs` do ato ou dos `candidates`; sem nenhum, `BLOCKED missing_authoritative_input`, `missing: evidence_refs`, antes de promover.

**O que VALIDATED verifica:** owner/domínio, produtor, validador, `reason`, evidência não vazia, transição legal, provenance completa, lineage completa, versão/status atuais, `content_hash` igual ao gravado. **Estrutura.** Nada sobre o território. Um leitor que veja "VALIDATED" e entenda "estudo territorial validado" lê errado — e a `justification` do ato tem de dizer isso (C6-SM-01, regra 2: resultado ≠ etapa).

### 1.2 Só AUTHORITATIVE publica no elo 1

`planning_state_publisher.py:286`: `if status != "AUTHORITATIVE": BLOCKED "so AUTHORITATIVE publica no elo 1"`. O contrato concorda: `authority_invariants`: *"estado deve estar em AUTHORITATIVE ou AUTHORITATIVE_OUTPUT do Authority Kernel"*.

E no entanto o **schema** do mesmo contrato aceita nove `state_status`: DRAFT, OBSERVATION, ANALYSIS, RECOMMENDATION, VALIDATED, AUTHORITATIVE, AUTHORITATIVE_OUTPUT, SUPERSEDED, REJECTED. O G4 (schema) deixaria passar um `ANALYSIS`; o invariante (texto) e o publisher (código) não. Hoje seis dos nove valores do enum são impublicáveis por construção.

### 1.3 O CEFEIDA evidencia um `subject_ref` que é `artifact_id`

`liceu.cefeida.evidence.subject_ref`: *"artifact_id do objeto observado"*. A evidência aponta para um artefato **publicado** — é o que torna o `subject_ref` verificável pelo CORE. O CEFEIDA não lê o banco do ARCHIMEDES (fronteira); sem fato publicado, não há `artifact_id` para observar.

### 1.4 A Constituição já disse que não é linear

`liceu_constitution.yaml`, `nao_e_sequencia_universal`: *"CEFEIDA pode observar a realidade ANTES de qualquer planejamento. Na arquitetura madura CEFEIDA e ARCHIMEDES são paralelos sob REALITY, convergindo em JOHN. O sistema não deve impor sequência linear universal."*

E `posicao_na_cadeia` (1→5) é lido por **um** lugar: `liceu_registry_check.py` R11, que exige `[1,2,3,4,5]` ordenado. Nenhum código de runtime (kit, CORE, publishers) lê a posição. A linearidade é uma asserção do checker, não uma regra do boundary.

### 1.5 O que a Interface canônica declarou (do dono)

Registrado pelo dono, não conferido em código: na `Interface_canonica` v0.2.0 o CEFEIDA consome o estado do ARCHIMEDES de forma **obrigatória** e o ARCHIMEDES consome a evidência do CEFEIDA de forma **opcional**. O kernel exige o contrário. A direção da obrigação estava invertida no que foi escrito — e só apareceu ao executar.

## 2. A cadeia real

```
declarada    ARCHIMEDES ──▶ CEFEIDA ──▶ JOHN ──▶ ANCHOR ──▶ OPERA
             (1)            (2)          (3)       (4)        (5)

real         ARCHIMEDES propõe ──▶ CEFEIDA evidencia ──▶ ARCHIMEDES promove ──▶ JOHN ──▶ ANCHOR ──▶ OPERA
             (proposta, ANALYSIS)   (causation = proposta)  (evidence_refs = [evidência])
```

A evidência é insumo do elo 1 **e** saída para o elo 3. O elo 1 tem duas publicações: a proposta e o estado autoritativo. A segunda referencia a primeira.

## 3. O fato de proposta — as saídas

### 3.1 Um contrato existente já serve?

| candidato | serve? | por quê |
|---|---|---|
| `liceu.archimedes.planning-state` com `state_status: ANALYSIS` | **não como está** | o schema aceita, mas o invariante diz "AUTHORITATIVE ou AUTHORITATIVE_OUTPUT" e o publisher recusa (`:286`). Aceitar seria contradizer o invariante — e o `event_type` `archimedes.planning.state.authoritative` mentiria no nome |
| `liceu.hub.planning-request` | não | é o pedido, do HUB; não carrega candidatos |
| `liceu.cefeida.evidence` com `subject_ref` = pedido | não | evidenciaria o **pedido**, não o estudo — prova a porta, não o elo (rejeitado pelo dono) |

Nenhum serve. É contrato novo — ou versão nova do planning-state com dois `event_type`, o que a estrutura do registry (um `event_type` por versão de contrato) não comporta sem quebrar R07.

### 3.2 Contrato novo: `liceu.archimedes.planning-proposal`

| | |
|---|---|
| `contract_id` | `liceu.archimedes.planning-proposal` |
| `event_type` | `archimedes.planning.proposal.published` |
| `classification` | **`DOMAIN_EVENT`**, não `AUTHORITATIVE_EVENT` — a proposta não afirma autoridade; é o estudo *antes* do ato. A taxonomia já tem o valor |
| `owner` / `allowed_producers` | `liceu.archimedes` |
| `posicao_na_cadeia` | ver §5 |
| `required_envelope_fields` | `artifact_id`, `trace_id`, **`causation_id`** (= `event_id` do `hub.planning.requested`: a proposta é causada pelo pedido) |
| `forbidden_envelope_fields` | `decision_id`, `governance_decision_id`, `execution_id` — os mesmos do planning-state |
| `scale` | herdada do pedido (`hub.planning-request.scale`); a proposta não afirma escala própria — escala é afirmação de autoridade, e a proposta não é ato de autoridade (call site: *"scale — afirmação de autoridade, nunca propriedade do estudo"*) |
| `payload` (proposta) | `planning_request_id` (obrig.), `state_id`, `state_version`, `content_hash` (os três do Root State: a evidência aponta para uma versão exata), `territorial_scope`, `candidates[]` (mesmo schema do planning-state), `crs`, `study_method_version` (obrig.: o que produziu os candidatos — ou `DECLARED` quando o mandatário declarou), `proposed_at` |
| `artifact_id` | `archimedes_root_states:<state_id>:<state_version>` — **o mesmo** que o planning-state usa (`artifact_id_for`), de modo que a evidência do CEFEIDA (`subject_ref = artifact_id`) e o estado autoritativo apontem para o mesmo objeto. O `event_id` difere pelo `contract_id` (ADR-002: `producer|contract|version|artifact_id`) |
| invariantes | "proposta não é alternativa autorizada nem estado autoritativo"; "`candidates[].evidence_refs` **vazio** na proposta — a evidência vem depois e aponta para ela"; "`study_method_version: DECLARED` marca proposta sem estudo — conta na estrutural, não na substantiva" |

**O que muda no ARCHIMEDES:** o kernel **não muda**. O call site ganha um segundo ato: `publish_proposal(state_id)` (estado em ANALYSIS, sem promoção) e `promote_and_publish` passa a exigir que `evidence_refs` do ato resolvam para fatos `cefeida.evidence.published` cujo `subject_ref` seja o `artifact_id` da proposta (leitura pelo SDK, como o ANCHOR já faz com o sujeito). Sem isso, a evidência poderia ser qualquer string — e o kernel só checa "não vazio".

**O que muda no CEFEIDA:** nada no publisher (#37). `subject_ref` recebe o `artifact_id` da proposta; `causation_id` recebe o `event_id` da proposta. `EvidenceRecord.subject_ref` já existe.

**O que muda no planning-state (elo 1, autoritativo):** `causation_id` passa a apontar para a **proposta** (não para o pedido — o pedido é a causa da proposta); `candidates[].evidence_refs` obrigatórios e resolvíveis. Isso é MINOR no contrato (regra nova sobre campo existente) ou MAJOR (evidence_refs obrigatório) — decisão. Hoje `required_envelope_fields` do planning-state é `[artifact_id, trace_id]`, sem `causation_id`: o mesmo furo do `cefeida.evidence` (nota do registry vs lista).

### 3.3 O que a decisão entre "contrato novo" e "versão nova" custa

- Contrato novo: registry MINOR (+1 contrato), R11 passa a ver 6 elos (ou a proposta fica fora da contagem, §5). Nenhum contrato existente muda.
- Versão nova do planning-state com `state_status: ANALYSIS` publicável: MAJOR do planning-state (muda o invariante "só AUTHORITATIVE") **e** exige que o `event_type` deixe de dizer `authoritative` — ou passa a mentir. R07 (event_type ↔ contrato nos dois sentidos) não comporta dois tipos numa versão.

## 4. O que a não linearidade muda

### 4.1 No G4 (schema)
Nada. G4 valida cada envelope contra o schema do **seu** contrato. Não conhece a cadeia. A proposta tem schema próprio; o planning-state ganha (se decidido) `evidence_refs` obrigatório em `candidates`.

### 4.2 No lineage
- Hoje: `causation_id` de cada elo aponta para o elo anterior; a cadeia é uma lista. Com a proposta: o planning-state aponta para a proposta; a evidência aponta para a proposta; o planning-state **também** referencia a evidência em `candidates[].evidence_refs`. É um **DAG**: dois fatos (evidência e estado) apontam para o mesmo pai (proposta); o estado referencia a evidência fora do `causation_id`.
- O CORE **resolve** `causation_id`/`source_event_id`/`parent_event_id` (main.py: `lineage_reference_not_found` → 422) mas **não** resolve `evidence_refs` — são strings no payload. Se a promoção exige evidência resolvível, quem resolve é o ARCHIMEDES (leitura pelo SDK), não o boundary. Decisão: o CORE passa a resolver `evidence_refs` (invariante novo, custo no boundary) ou fica no produtor.
- ADR-002: identidade por `artifact_id`. Proposta e estado compartilham `artifact_id` e diferem no `contract_id` → `event_id` distintos, sem colisão. A evidência tem `artifact_id` próprio (`cefeida_evidence:…`) com `subject_ref` = o do ARCHIMEDES.

### 4.3 No checker R11
`posicao_na_cadeia` exige `[1..n]` ordenado. Ou a proposta entra como posição própria (a cadeia mínima vira 6 elos: proposta 1, evidência 2, estado 3, …) ou fica sem posição, como `human-decision` ("ramificação", `nota_ramificacao`) — e R11 continua contando 5.

### 4.4 No que "5/5" significa
A contagem estrutural passa a ter uma **volta**: o elo 1 só fecha depois do elo 2. A ordem de execução da primeira sessão é proposta → evidência → estado → recomendação → autorização → execução. O dono já antecipou: o ANCHOR pode precisar de parecer jurídico antes de autorizar, e o parecer pode precisar da recomendação — outra volta, que só aparece ao executar o elo 4. A cadeia mínima é um DAG com pelo menos um retorno; o número que se anuncia precisa dizer de qual grafo.

## 5. A proposta conta como elo?

| | como elo próprio (6/6) | como etapa interna do elo 1 (5/5) |
|---|---|---|
| a favor | é fato publicado, com contrato, atravessa o boundary, tem prova estrutural própria | a proposta não afirma autoridade; "elo" no ecossistema tem sido sinônimo de ato com dono de autoridade; a contagem 5/5 já está em toda parte |
| contra | infla a contagem com um fato não autoritativo; R11 muda | esconde que o elo 1 tem duas publicações e que o CEFEIDA é insumo dele |
| contagem | 6/6 estrutural | 5/5 estrutural, com nota: "elo 1 = proposta + estado" |

Leitura sugerida (não decisão): **etapa interna do elo 1**, com `posicao_na_cadeia` ausente (ramificação, como `human-decision`) e `classification: DOMAIN_EVENT`. A contagem continua 5/5, mas o documento de evidência lista **seis** fatos e diz que o primeiro é proposta. Se a proposta contar como elo, o que se ganha em precisão se perde em comparabilidade com tudo o que já foi contado.

## 6. Se o CEFEIDA não evidenciar

Hoje: nada expira. `archimedes_root_states` guarda ANALYSIS indefinidamente; não há `valid_until` no Root State nem no kernel.

| saída | o que exige | efeito |
|---|---|---|
| **A** — a proposta fica em ANALYSIS indefinidamente | nada | honesto e simples; o elo 1 não fecha, e o motivo é legível (sem evidência). Risco: propostas velhas acumulam; nova versão do estudo supera a anterior (`SUPERSEDED` via nova `state_version`) |
| **B** — a proposta carrega `proposal_expires_at` | campo no contrato; o kernel recusa promover com evidência posterior ao prazo | força o CEFEIDA a responder num prazo; mas "expirar" um estudo por falta de evidência confunde ausência de resposta com invalidade do estudo (R-VALIDITY: validade é dimensão própria) |
| **C** — o elo 1 declara `BLOCKED missing_authoritative_input`, `owner: liceu.cefeida`, como ato registrado | escalação registrada no ARCHIMEDES (auditável), sem expirar nada | é o padrão P04 já usado nos publishers: a ausência é declarada, nomeando o dono, e fica visível — sem inventar prazo |

Leitura sugerida: **A + C** — nada expira, e a ausência é um registro nomeado, não silêncio. B só se o dono quiser SLA de evidência, e isso é regra de operação, não de protocolo.

## 7. O que fica para decidir

1. Contrato novo `liceu.archimedes.planning-proposal` (§3.2) — ou versão MAJOR do planning-state (§3.3).
2. `classification: DOMAIN_EVENT` para a proposta.
3. `evidence_refs` obrigatórios e **resolvíveis** no planning-state: quem resolve — ARCHIMEDES (SDK) ou CORE (boundary).
4. `causation_id` do planning-state passa a ser a proposta; e `causation_id` entra em `required_envelope_fields` do planning-state (mesmo furo do cefeida.evidence).
5. A proposta como etapa interna do elo 1 (sem `posicao_na_cadeia`) ou como elo (R11 → 6).
6. Sem evidência: A + C (nada expira; ausência declarada) ou B (prazo).
7. `study_method_version: DECLARED` como marca explícita de proposta sem estudo — conta na estrutural, nunca na substantiva.

Nada implementado. O Codespace não sobe antes disto: sem a proposta, o elo 1 não promove, e refazer o elo 0 prova o que o #50 já provou.

## 8. Decisão (2026-09-21, dono do kit)

Item a item do §7, com os ajustes que o dono fez ao texto:

| § | Decisão |
|---|---|
| 7.1 | **Contrato novo** `liceu.archimedes.planning-proposal` 1.0.0. `DOMAIN_EVENT`. Mesmo `artifact_id` do planning-state (`archimedes_root_states:<state_id>:<state_version>`); `event_id` difere pelo `contract_id` (ADR-002). `causation_id` = o `hub.planning.requested`. Sem `posicao_na_cadeia`. |
| 7.2 | `DOMAIN_EVENT` — sim. Proposta não é ato de autoridade. |
| 7.3 | **Os dois resolvem.** O contrato declara `resolvable_refs: [{path, must_resolve_to: [{event_type, producer}, ...]}]`; o **boundary** do CORE resolve toda referência do payload assim declarada, como já resolve `causation_id` (422 `lineage_reference_not_found:<path>:<id>`), exigindo **tipo E produtor** do fato encontrado. O **ARCHIMEDES** resolve de novo, pelo SDK, antes de promover — e exige mais: o `causation_id` de cada evidência tem de ser o `event_id` da **versão** da proposta que está sendo promovida. |
| 7.4 | `causation_id` **obrigatório** no planning-state (= proposta) e no cefeida.evidence (= versão da proposta evidenciada). MAJOR nos dois: planning-state **2.0.0**, cefeida.evidence **2.0.0**; 1.0.0 de ambos RETIRED sem migração (nenhum fato existe). `hub.planning-request` intocado: raiz, `causation_id` continua proibido. |
| 7.5 | Proposta é **etapa interna do elo 1**, sem posição. R11 continua 5 elos. |
| 7.6 | **A + C.** Nada expira. Ausência de evidência é declarada nomeando `liceu.cefeida` como owner do bloqueio. |
| 7.7 | Sim à marca, mas **em dois campos** (C6-SM-01: um termo, uma dimensão). `study_basis: DECLARED\|METHOD` (enum, obrigatório) e `study_method_version` (obrigatório se METHOD, **proibido** se DECLARED — schema `if/then` + G5). A contagem substantiva exige `study_basis = METHOD`. O publisher recusa METHOD sem versão e DECLARED com versão. |

**Ajuste do dono — a evidência amarra a VERSÃO.** `cefeida.evidence` 2.0.0: `subject_ref` = `artifact_id` da proposta (obrigatório); `causation_id` = `event_id` **da versão** da proposta evidenciada (obrigatório). Aprova-se uma versão, não um nome: evidência sobre a v1 não promove a v2.

**`resolvable_refs` entra também onde já havia referência de payload:** `john.recommendation` 2.0.0 (`evidence_refs` → `cefeida.evidence.published` / `liceu.cefeida`) e `anchor.authorization` 1.1.0 (`legal_basis_refs` → `legal.admissibility.assessed` / `liceu.legal`; **opcional**: resolve só quando presente; ausente = UNCOVERED declarado; presente e irresolvível = 422 — e hoje toda referência falha, porque `liceu.legal` não publica, o que está certo).

**Contagem declara o grafo.** Toda métrica diz o DAG que conta: "estrutural N/5, substantiva M/5 — DAG do ADR-004, retorno CEFEIDA → ARCHIMEDES; etapas internas não contam como elo".

### 8.1 Extensão futura registrada, não implementada — R-VALIDITY

Resolver prova que o fato **existe** com o tipo e o produtor exigidos. Não prova que está **válido**: uma `cefeida.evidence.published` SUPERSEDED (ou retratada, quando isso existir) resolve e passa no boundary e no ARCHIMEDES. Validade é dimensão própria (C6-SM-01 `knowledge_validity`). Quando houver fato de supersessão/retratação, `must_resolve_to` ganha uma condição de validade — não antes, para não inventar estado que nenhum contrato produz.

### 8.2 Ordem de implementação (do dono)

1. kit 0.14.0 — contratos, registries, self-tests, tag após merge.
2. CORE — boundary resolve `resolvable_refs` (tipo e produtor), com teste.
3. ARCHIMEDES — `publish_proposal`; promoção exige evidência cuja `causation_id` == `event_id` da versão promovida, com teste; a justificativa de VALIDATED diz o que validou (estrutura).
4. bumps.
5. UM Codespace: 0 → proposta → evidência → planning-state → recomendação; duas contagens, grafo declarado.
