# Rascunho — os quatro contratos do plano de autoridade e a separação da Testemunha

**2026-10-09 · RASCUNHO PARA REVISÃO. Nada aqui foi aplicado.**

Este documento é proposta. Ele **não** altera `liceu_contract_registry.yaml`, `liceu_event_registry.yaml`, `liceu_producer_registry.yaml` nem `liceu_constitution.yaml` — por instrução expressa do titular, mexer nesses arquivos espera a palavra dele.

Nasceu de três trabalhos que a decisão de 2026-10-09 (Opção B, três domínios votantes, control plane extraído) deixou disponíveis e que não dependem de provedor, cluster ou gasto:

1. a separação entre **votar no log** e **autorizar atos**
2. os **quatro contratos** dos `event_type` `authority.`
3. a preservação explícita da porta `promotion_requires_witness_attestation`

Todo campo de payload abaixo foi **lido do código**, não inventado. A procedência de cada um está dita.

---

## 0. Uma correção de atribuição, antes de tudo

O §3 do ADR-003 diz, ao descrever a tensão da Opção B:

> um nó Raft **vota**; a Testemunha "só informa, nunca autoriza"

A frase é atribuída à Constituição. **Ela não está na Constituição.** Busca por "testemunha", "witness", "só informa" e "nunca autoriza" em `liceu_constitution.yaml` não devolve nada.

A norma existe, e está no **Producer Registry**, `liceu_producer_registry.yaml` linhas 560-566:

```yaml
    - instance_id: liceu.authority#mother-witness
      authority_role: WITNESS
      status: PLANNED
      PROIBICOES:
      - nunca autoriza
      - nunca estabelece teto
      - nunca assume o papel da ativa
```

Isso muda duas coisas de forma prática:

- **são três proibições, não uma.** "Nunca autoriza" é a que entra em tensão com o voto de Raft. "Nunca estabelece teto" e "nunca assume o papel da ativa" não são tocadas por votar em liderança de log, e a emenda não deve mexer nelas.
- **a emenda vai no Producer Registry**, não na Constituição. Quem seguisse a atribuição do ADR escreveria no arquivo errado.

É a mesma classe de erro que o genoma já registrou uma vez — três citações atribuídas ao §6 que eram do §3. O conteúdo citado estava certo; a fonte, não.

---

## 1. Proposta: a separação entre votar no log e autorizar atos

**Onde:** `liceu_producer_registry.yaml`, no bloco de `liceu.authority#mother-witness`.

**Texto proposto**, acrescentando ao bloco existente sem alterar as três proibições:

```yaml
    - instance_id: liceu.authority#mother-witness
      authority_role: WITNESS
      status: PLANNED
      PROIBICOES:
      - nunca autoriza
      - nunca estabelece teto
      - nunca assume o papel da ativa
      VOTO_NO_LOG_DE_CONSENSO:
        permitido: true
        procedencia: '[DECIDIDO 2026-10-09] Opcao B do ADR-003, tres dominios votantes'
        o_que_o_voto_decide: quem e lider do log replicado da camada A
        o_que_o_voto_NAO_decide:
        - autorizar ato de dominio
        - estabelecer teto de decisao
        - assumir o papel da ativa
        - substituir a atestacao exigida pela promocao
        razao: >
          Votar em lideranca de log e ato de PROTOCOLO, nao ato de AUTORIDADE. A
          proibicao "nunca autoriza" permanece integral: ela proibe autorizar
          atos, e um voto de Raft nao autoriza ato nenhum — ele ordena o log.
          Sem esta distincao escrita, a Opcao B fica impossivel por contradicao
          com a proibicao, ou a proibicao fica violada em silencio.
        limite_explicito: >
          Maioria no log NAO substitui atestacao. Com tres nos votantes, ACTIVE e
          SUCCESSOR formam maioria sem a Testemunha; a porta da atestacao e
          pre-condicao SEPARADA e permanece.
```

**O que esta redação deliberadamente não faz:** não concede à Testemunha nenhum poder novo sobre atos, não altera `attest()`, e não remove nenhuma das três proibições.

---

## 2. Proposta: a porta da atestação, como invariante escrito

**O problema**, medido em `cv-backend-core/app/services/authority_control_plane.py` linhas 393-398: se `attestation` é `None`, o `promote()` recusa com a regra `promotion_requires_witness_attestation`. É porta **separada** do fencing.

A Opção B troca **onde** o `enforce()` lê a época e **quem** a incrementa (§5 do ADR). Não diz nada sobre essa porta. E com três votantes, ACTIVE e SUCCESSOR são dois — maioria. Se `promote()` virar "proposta aceita pela maioria" sem preservar a porta, promove-se **sem a Testemunha**, e cai a exigência que o próprio titular escreveu: *"a falha da Testemunha deve produzir `UNOBSERVABLE`, sem promoção automática de autoridade"*.

**Texto proposto**, para o bloco de invariantes de autoridade:

```yaml
      authority_invariants:
      - >
        A promocao exige atestacao VIGENTE da Testemunha. Esta exigencia e
        pre-condicao SEPARADA do fencing de epoca, e nao e satisfeita por
        maioria em log de consenso: maioria responde "quem e lider do log",
        nao "alguem verificou". Em qualquer topologia — incluindo a Opcao B do
        ADR-003 — a troca da fonte da epoca NAO revoga esta porta.
      - >
        Falha da Testemunha produz ACTIVE_UNOBSERVABLE e BLOQUEIA a promocao.
        Incapacidade de observar nunca e lida como ausencia do observado.
```

A segunda frase não é novidade: é o comportamento já medido na `PRF-0061` do genoma. Está proposta aqui porque o que não está escrito é o que a próxima refatoração apaga sem perceber.

---

## 3. Proposta: os quatro contratos

### Por que eles não existem hoje

Medido: dos cinco `event_type` `authority.` deste sistema, o Event Registry declara **um** (`authority.human.decision.recorded`). Os outros quatro são emitidos pelo CORE e não têm dono declarado em lugar nenhum — e a razão está em `_audit`, linhas 180-194: ele monta um `AuditEvent` e faz `db.add` + `db.commit`. **Eles nunca foram fatos. São linhas de tabela.**

Com o control plane extraído (§7.1, decidido), o plano passa a emiti-los atravessando uma fronteira, e fato que atravessa fronteira precisa de contrato.

### Uma lacuna de vocabulário que a proposta encontra

O Event Registry tem `implementation_status` com valores como `DECLARED_BUT_NOT_IMPLEMENTED` e `NAO_INICIADA`, e a nota dele separa bem os eixos: *"`contract_lifecycle` é do CONTRATO; `implementation_status` é do CÓDIGO. Não são contraditórios — são eixos distintos."*

**Nenhum valor existente descreve o estado real destes quatro:** o código os emite, mas como linha de auditoria, não como fato publicado. Proponho `EMITIDO_COMO_AUDITORIA_NAO_COMO_FATO` e deixo a escolha do rótulo com o titular — inventar valor de vocabulário é decisão de protocolo, não minha.

### E uma questão de nome

Os `event_type` do registry são todos pontilhados, com três ou quatro segmentos: `cefeida.evidence.published`, `opera.execution.created`, `authority.human.decision.recorded`. Três dos quatro seguem isso. O quarto, não:

```
authority.fencing.rejected      ok
authority.epoch.promoted        ok
authority.witness.attested      ok
authority.human_escalation      dois segmentos, com underscore dentro
```

Duas saídas, e a escolha é do titular: **contratar como está**, preservando o que o código emite, ou **renomear** para `authority.escalation.requested` — consistente com a casa, e exige mudar o código. Rascunhei com o nome atual, para a proposta não embutir uma mudança de código que ninguém autorizou.

### 3.1 `liceu.authority.fencing-rejected`

Payload lido de `_reject` (linhas 199-208): `{"rule": rule, **context}`, com o `context` montado no `enforce()` (linhas 233-242).

```yaml
  liceu.authority.fencing-rejected:
    1.0.0:
      contract_id: liceu.authority.fencing-rejected
      contract_version: 1.0.0
      status: DRAFT
      owner: liceu.authority
      allowed_producers:
      - liceu.authority
      event_type: authority.fencing.rejected
      posicao_na_cadeia: null
      natureza: AUDITORIA_DO_PLANO_DE_AUTORIDADE
      proposito: >
        registrar que um fato foi RECUSADO na fronteira, com a regra nomeada, a
        epoca recebida e a vigente. Recusa e fato auditavel ANTES de virar
        resposta HTTP.
      payload_schema:
        type: object
        required:
        - rule
        - producer_id
        - producer_instance_id
        - authority_role
        - event_type
        - received_epoch
        - current_epoch
        properties:
          rule: {type: string}
          producer_id: {type: string}
          producer_instance_id: {type: [string, 'null']}
          identity_producer_id: {type: [string, 'null']}
          authority_role: {type: [string, 'null']}
          event_type: {type: string}
          contract_id: {type: [string, 'null']}
          received_epoch: {type: [integer, 'null']}
          current_epoch: {type: integer}
```

### 3.2 `liceu.authority.epoch-promoted`

Payload lido da linha 421-426: `{**context, "previous_active_instance_id", "new_epoch", "witness_instance_id", "attestation_id"}`, com o `context` do `promote()` (linhas 359-363).

```yaml
  liceu.authority.epoch-promoted:
    1.0.0:
      contract_id: liceu.authority.epoch-promoted
      contract_version: 1.0.0
      status: DRAFT
      owner: liceu.authority
      allowed_producers:
      - liceu.authority
      event_type: authority.epoch.promoted
      posicao_na_cadeia: null
      natureza: AUDITORIA_DO_PLANO_DE_AUTORIDADE
      proposito: >
        registrar a promocao de epoca: quem passou a ACTIVE, quem foi RETIRED, e
        qual atestacao da Testemunha a autorizou.
      payload_schema:
        type: object
        required:
        - target_instance_id
        - caller_instance_id
        - current_epoch
        - requested_epoch
        - new_epoch
        - previous_active_instance_id
        - witness_instance_id
        - attestation_id
        properties:
          target_instance_id: {type: string}
          caller_instance_id: {type: string}
          current_epoch: {type: integer}
          requested_epoch: {type: integer}
          new_epoch: {type: integer}
          previous_active_instance_id: {type: [string, 'null']}
          witness_instance_id: {type: string}
          attestation_id: {type: string}
      authority_invariants:
      - witness_instance_id e attestation_id sao OBRIGATORIOS: promocao sem atestacao nao existe
```

### 3.3 `liceu.authority.witness-attested`

Payload lido da linha 603-606: `{**context, "attestation_id", "expires_at"}`, com o `context` do `attest()` (linhas 522-527).

```yaml
  liceu.authority.witness-attested:
    1.0.0:
      contract_id: liceu.authority.witness-attested
      contract_version: 1.0.0
      status: DRAFT
      owner: liceu.authority
      allowed_producers:
      - liceu.authority
      event_type: authority.witness.attested
      posicao_na_cadeia: null
      natureza: AUDITORIA_DO_PLANO_DE_AUTORIDADE
      proposito: >
        registrar o que a Testemunha MEDIU, com o veredito derivado da sonda e o
        alcance de cada ponta. Atestacao e resultado de sonda, nao declaracao.
      payload_schema:
        type: object
        required:
        - producer_instance_id
        - observed_epoch
        - current_epoch
        - verdict
        - active_probe_reached
        - successor_probe_reached
        - attestation_id
        - expires_at
        properties:
          producer_instance_id: {type: string}
          observed_epoch: {type: [integer, 'null']}
          current_epoch: {type: integer}
          verdict: {type: string}
          concur_promotion_of: {type: [string, 'null']}
          active_probe_reached: {type: [boolean, 'null']}
          successor_probe_reached: {type: [boolean, 'null']}
          attestation_id: {type: string}
          expires_at: {type: string, format: date-time}
      authority_invariants:
      - >
        active_probe_reached e successor_probe_reached sao obrigatorios porque
        distinguem NAO OBSERVEI de OBSERVEI QUE ESTA MORTA. Atestacao sem o
        alcance da sonda nao permite essa distincao.
      - a Testemunha atesta; nunca autoriza, nunca estabelece teto, nunca assume o papel da ativa
```

### 3.4 `liceu.authority.escalation-requested`

Payload lido da linha 742-747, que é o único dos quatro com payload **literal** no código, não derivado de `context`.

```yaml
  liceu.authority.escalation-requested:
    1.0.0:
      contract_id: liceu.authority.escalation-requested
      contract_version: 1.0.0
      status: DRAFT
      owner: liceu.authority
      allowed_producers:
      - liceu.authority
      event_type: authority.human_escalation
      posicao_na_cadeia: null
      natureza: AUDITORIA_DO_PLANO_DE_AUTORIDADE
      proposito: >
        registrar que a promocao foi BLOQUEADA e um humano foi acionado, com a
        completude do dossie. Escalar sem contexto transfere o problema, nao a
        decisao.
      payload_schema:
        type: object
        required:
        - escalation_id
        - reason
        - target_instance_id
        - requested_by_instance_id
        - current_epoch
        - dossier_completeness
        properties:
          escalation_id: {type: string}
          reason: {type: string}
          target_instance_id: {type: string}
          requested_by_instance_id: {type: string}
          current_epoch: {type: integer}
          dossier_completeness:
            type: object
            required: [present, required]
            properties:
              present: {type: integer}
              required: {type: integer}
      nota_de_nome: >
        event_type fora da convencao pontilhada da casa. Mantido como o codigo
        emite; renomear para authority.escalation.requested e decisao do titular
        e exige mudanca de codigo.
```

### 3.5 As quatro entradas correspondentes no Event Registry

Necessárias para R05, R06 e R07 — todo `contract_id` resolve, versão bate, e `event_type` ↔ contrato consistente nos dois sentidos.

```yaml
  authority.fencing.rejected:
    owner: liceu.authority
    contract_id: liceu.authority.fencing-rejected
    contract_version: 1.0.0
    posicao_na_cadeia: null
    descricao: fato recusado na fronteira, com a regra nomeada
    natureza: AUDITORIA_DO_PLANO_DE_AUTORIDADE
    transport: HTTP boundary oficial
    implementation_status: EMITIDO_COMO_AUDITORIA_NAO_COMO_FATO
    contract_lifecycle: DRAFT

  authority.epoch.promoted:
    owner: liceu.authority
    contract_id: liceu.authority.epoch-promoted
    contract_version: 1.0.0
    posicao_na_cadeia: null
    descricao: promocao de epoca, com a atestacao que a autorizou
    natureza: AUDITORIA_DO_PLANO_DE_AUTORIDADE
    transport: HTTP boundary oficial
    implementation_status: EMITIDO_COMO_AUDITORIA_NAO_COMO_FATO
    contract_lifecycle: DRAFT

  authority.witness.attested:
    owner: liceu.authority
    contract_id: liceu.authority.witness-attested
    contract_version: 1.0.0
    posicao_na_cadeia: null
    descricao: o que a Testemunha mediu, com o alcance de cada sonda
    natureza: AUDITORIA_DO_PLANO_DE_AUTORIDADE
    transport: HTTP boundary oficial
    implementation_status: EMITIDO_COMO_AUDITORIA_NAO_COMO_FATO
    contract_lifecycle: DRAFT

  authority.human_escalation:
    owner: liceu.authority
    contract_id: liceu.authority.escalation-requested
    contract_version: 1.0.0
    posicao_na_cadeia: null
    descricao: promocao bloqueada e humano acionado, com completude do dossie
    natureza: AUDITORIA_DO_PLANO_DE_AUTORIDADE
    transport: HTTP boundary oficial
    implementation_status: EMITIDO_COMO_AUDITORIA_NAO_COMO_FATO
    contract_lifecycle: DRAFT
```

---

## 4. `posicao_na_cadeia: null` nos quatro — e por quê

Os quatro são **auditoria do plano de autoridade**, não elos. Nenhum deles é ato do LICEU na cadeia da P-001, e contratá-los **não pode** fazer o numerador subir.

É o mesmo cuidado que a FIT-016 já aplica aos elos 4 e 5: eles entram como observações do mundo real, nunca como fatos `anchor.authorization` ou `opera.execution`. Aqui a regra é análoga — contratar um evento de auditoria dá a ele dono e forma, não posição na cadeia.

Se algum destes recebesse `posicao_na_cadeia` com número, o juiz passaria a contá-lo, e a cadeia subiria sem nenhum ato novo ter acontecido. **É esse o erro que o `null` impede.**

---

## 5. O que este rascunho não resolve

- **o portão da ADR.** `P1_07B_extracao_fisica` está `ADR_REQUIRED`, e a razão escrita nele — *"extração toca migrations, auth, Event Store, Codespaces e lineage"* — descreve a extração do control plane melhor do que descreve a extração original. Se o portão vale, falta uma ADR antes de qualquer código. Não é pergunta que um rascunho de contrato responde.
- **as três perguntas do §7** que seguem abertas: camada C (§7.3), `activation_certificate_id` (§7.4) e promoção não planejada (§7.5).
- **a leitura da linha 710.** O `_latest_fact` lê `archimedes.planning.state` e `cefeida.evidence.published` por SQL. Contratar os quatro eventos de auditoria não resolve essa dependência: ela é de **leitura** do histórico da cadeia, não de escrita, e com o plano extraído ela precisa virar caminho de rede, fato consumido, ou deixar de existir.
- **o `implementation_status` real.** Os quatro são emitidos como linha de auditoria hoje. Nenhum valor do vocabulário atual diz isso, e eu propus um nome em vez de forçar um valor existente a mentir.

---

## 6. O que seria preciso para isto deixar de ser rascunho

Em ordem, e nenhum dos passos é meu:

1. o titular revisar e corrigir este texto
2. o titular decidir o nome do quarto evento e o rótulo do `implementation_status`
3. o titular aplicar as emendas no Producer Registry, no Contract Registry e no Event Registry
4. rodar `liceu_registry_check.py` — R03, R04, R05, R06, R07 e R08 são as regras que estas entradas atravessam
5. só então, código

Decisão, execução e comprovação são estados distintos. Este documento é o primeiro.
