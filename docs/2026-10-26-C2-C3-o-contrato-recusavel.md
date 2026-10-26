# C2 e C3: o contrato "votar no log ≠ autorizar atos", em forma recusável, e as duas questões que ele arrasta

**2026-10-26 · PROPOSTA.** Como no rascunho de 09/10, o texto que for para `liceu_producer_registry.yaml`, `liceu_contract_registry.yaml` ou `liceu_constitution.yaml` espera a palavra do titular. Este documento não altera nenhum dos três.

O roteiro pede o contrato "enunciado de forma RECUSÁVEL: o que atravessa a fronteira, quem pode autorizar, e o que acontece com voto que chega sem autorização e com autorização que chega sem voto". E pede antes do etcd, porque o contrato **decide o que o etcd tem de garantir**.

---

## 0. O que já existe, medido antes de escrever

| peça | onde | estado |
|---|---|---|
| a separação entre voto e autorização | `liceu_producer_registry.yaml`, `mother-witness`, bloco `VOTO_NO_LOG_DE_CONSENSO` | **APLICADO em 2026-10-15** por decisão do titular: o voto decide "quem é líder do log"; não autoriza, não estabelece teto, não assume o papel da ativa, não substitui a atestação |
| maioria não substitui atestação | o mesmo bloco (`limite_explicito`) e `liceu_contract_registry.yaml`, `authority_invariants` de `liceu.authority.promoted` | **ESCRITO**: "o quorum decide QUEM, a atestação decide SE" |
| a permissão é só normativa | PRF-0179 | **MEDIDO**: um voto de consenso não é fato publicado e nunca passa pelo portão de "nunca autoriza"; a permissão remove a contradição e não acrescenta mecanismo |
| o que o contrato NÃO cobre | PRF-0182 | **MEDIDO**: ele cobre a **autorização** e **não** a **linearizabilidade da época**; nenhum portão do ecossistema confere a ordem das épocas |

Então o C2 não parte do zero. A separação está na lei há 11 dias. Faltam os **dois casos assimétricos**, e falta dizer o que acontece em cada um.

---

## 1. O contrato, cláusula por cláusula

Cada cláusula traz: o enunciado; **como recusá-la**, isto é, o fato observável que a falsifica; e **o que a confere hoje**.

### C2.1 · O que atravessa a fronteira

**Do log de consenso para a camada de autoridade atravessam só duas coisas: a linha (época, ativa, emissor) e o fato de que ela foi comprometida.** Nada do log vira autorização de ato de domínio.

- **Recusa:** um ato de domínio aceito pelo boundary do CORE cuja única base é uma entrada de log, sem passar pelos portões da camada de aplicação (o papel, a época, a atestação na promoção).
- **Confere hoje:** nada mecânico. Ainda não há log (o etcd foi decidido, não instalado), e a cláusula é normativa até o C5.

### C2.2 · Quem pode autorizar uma promoção

**A autorização de promover é a conjunção de três condições, e nenhuma delas é um voto:**
1. atestação válida da Testemunha, para este alvo, na época vigente;
2. avanço de exatamente 1 na época;
3. chamador com papel ACTIVE ou SUCCESSOR.

- **Recusa:** uma promoção com efeito sem `attestation_id` vigente, ou com salto de época diferente de 1.
- **Confere hoje:** o código. A porta da atestação está em `authority_control_plane.py:420-431`, antes da única escrita da época (linha 442), e o avanço de 1 é a regra `authority_epoch_not_monotonic`. Medido com escopo na PRF-0318.

### C2.3 · Voto que chega sem autorização

**Uma entrada comprometida pela maioria que promove sem atestação válida NÃO toma efeito.** Ela pode ficar no log, mas a época que ela carrega **não é servida**: o efeito é recusado no ponto de efeito (a cerca do passo B e a porta da atestação), e a recusa escala ao humano (D-040).

- **Recusa:** um processo servindo, ou seja, com o `enforce()` aceitando, sob uma época que entrou no log sem atestação válida.
- **Confere hoje:** nada, porque não há log. **E há um limite medido:** pela PRF-0182, a porta confere a atestação e **não** a ordem das épocas. Uma entrada que **reordena** épocas (em vez de pular a atestação) não é pega por ela. Isso é responsabilidade do log (§1.5).

### C2.4 · Autorização que chega sem voto

**Uma promoção autorizada localmente (atestação válida e `promote()` aceito num armazenamento) que não foi comprometida no log NÃO toma efeito.** A época que vale é a do log, e o armazenamento local é cache dela.

- **Recusa:** dois processos servindo a mesma época depois de promoções feitas em armazenamentos diferentes. É o split-brain de escrita da PRF-0309.
- **Confere hoje:** **NADA, e a cláusula está VIOLADA por construção**: a PRF-0309 mediu dois `promote()` concorrentes escrevendo a época 2, porque ainda não há log. É o que o C5 tem de fechar, e o teste do C5 é exatamente este: o mesmo split-brain, com o etcd, tem de recusar o segundo.

### C2.5 · Consequência: o que o etcd tem de garantir

Com C2.1 a C2.3, o log **não** precisa garantir autorização: autorização errada é recusada a jusante, pela atestação. **Mas a PRF-0182 limita isso:** a ordem das épocas não é conferida a jusante por ninguém. Logo:

- **a correção do log sob partição é estrutural para a época.** Ela não sai do caminho de confiança; sai só a parte da autorização;
- o etcd tem de dar **P4 e P5** para a sequência de épocas (a régua do model check, no ADR-007 §2);
- **a leitura da época no `enforce()`** tem de ser linearizável **ou** cercada no efeito. O modelo não exige P3, mas avisa que isso **não a torna dispensável**. É a primeira medição do C5.

**Esta é a resposta à pergunta do C2: "votar nunca autoriza" já é a lei, e por isso o ônus do etcd cai para a época, mas não cai a zero.**

---

## 2. C3: as duas questões que o contrato arrasta

### 2.1 · A atestação continua obrigatória com promoção por maioria?

**Sim, e isso já está na lei** (os invariantes do Contract Registry e o limite explícito do Producer Registry). A maioria **não** substitui a atestação; se substituísse, a Testemunha deixaria de arbitrar.

A CLM-0086 ("o consenso preserva a porta **por si**") estava STALE desde que a FIT-019 rebaixou a PRF-0114. **Ela voltou a REFUTED pela PRF-0318**, uma leitura do código com escopo declarado: a porta pertence ao `promote()`, e não à fonte da época. Trocar a fonte para consenso **não** a preserva sozinha; ela precisa ser mantida explicitamente como pré-condição. O teste que fecha isso é do C5: `promote()` pelo consenso, recusando sem atestação.

### 2.2 · O P1_07B se aplica à extração da camada A? O critério

O portão protege a **fronteira física do CORE** (`liceu_constitution.yaml`, `monolitos.core.fronteira_fisica`). Ele traz duas listas e uma razão:
- `core_somente`: identity, contracts, federation event fabric, service identities, trust, lineage, replay, technical federation policy;
- `core_nunca`: os domínios;
- `razao_da_adr`: "extração toca migrations, auth, Event Store, Codespaces e lineage".

Ele está marcado **CUMPRIDO** pela ADR-001, para a extração do kit.

**Critério proposto, mecânico e não caso a caso:**

> Uma mudança **mergeada no CORE** aciona o P1_07B se, e somente se, **(a)** move para fora do processo do CORE código ou estado de algum item de `core_somente`, **ou** **(b)** toca, ao extrair, algum dos cinco itens da `razao_da_adr`. Acionado, o portão exige uma ADR com estado DECIDIDO **antes do merge**, e a regra R0G passa a conferir isso pelo nome da ADR.

**Aplicado à camada A:**
- o estado que sai (`authority_state`, papéis, atestações) é **trust** e **technical federation policy**: atende a (a);
- a extração toca **migrations** (as tabelas) e **auth** (a identidade por instância): atende a (b).

**Logo o P1_07B se aplica, e a ADR que ele exige é o ADR-006** ("extrair ou não o control plane"), que está **PROPOSTO**. Até o ADR-006 ser decidido, nenhum código que tire a fonte da época de dentro do CORE pode ser mergeado.

**O que isso significa para o C5:** o laboratório (etcd em contêineres numa branch, com medição) é **medição, não extração**, e o critério fala de merge no CORE. Já **mergear** a troca da fonte da época para o etcd **exige o ADR-006 decidido antes**.

---

## 3. Uma premissa do C5 que não bate

O roteiro manda **"TROQUE o stub pelo cliente real"**. **Não existe stub de consenso no CORE.** Os únicos stubs de `cv-backend-core/app` são os do `action_engine` (WhatsApp, scoring e similares). O "log de mentira" contra o qual o fencing foi provado está no **modelo do genoma** (`tools/modelo/fencing.py`, PRF-0218).

No C5, então, não se substitui uma peça: **escreve-se** o cliente e troca-se a fonte da época no `promote()` e no `enforce()`. A condição do roteiro continua valendo, e fica até mais nítida: provar que essa troca **não tocou a regra de fencing**, e rodar de novo, inteiros, os testes de fencing e de atestação.
