# ADR-005 — Topologia do estado de autoridade: a decisão, registrada

**Estado:** REGISTRO. Este documento nao decide: registra a escolha da Opcao B,
tomada pelo titular, com as respostas do §7 datadas em 2026-10-09. A UNK-0001
NAO fecha com ele — ver §5.3.

**Data:** 2026-10-13 · **Autor da decisão:** o titular · **Redação:** derivada dos
registros da UNK-0001 no `liceu-genome`, com data e autor de cada resposta.

> **O que este documento é, e o que ele não é.** Ele **registra** uma decisão já
> tomada; não a toma, não a executa e não a comprova. A UNK-0001 vinha carregando
> as respostas do titular dispersas no campo `required_evidence` — medição e
> decisão no mesmo lugar, que é exatamente o arranjo em que uma passa pela outra.
> Este ADR separa: aqui fica **a decisão**; a prova fica nas PRF; a execução não
> existe ainda, e isso está dito abaixo com o nome do que falta.
>
> **Decisão, execução e comprovação são estados distintos.** Nada aqui deve ser
> lido como implementação concluída ou escala promovida.

---

## 1. A decisão

**Opção B do ADR-003 §3 — protocolo de consenso (Raft/etcd) para a camada A.**

Decidida pelo titular; o mecanismo estava decidido antes de 2026-10-09, e as
quatro perguntas abertas do ADR-003 §7 foram respondidas naquela data.

**Forma, pelo §7.1 (decidido 2026-10-09):** control plane **extraído**, **só a
camada A**, com **um CORE por domínio** consumindo-o. É a forma menor e é a que o
ADR diz que B pede. Isso supersede de vez a frase *"duas pontas completas em um
provedor principal e uma Testemunha mínima em segundo provedor"* da primeira
versão da decisão: três nós votantes exigem três domínios distintos, logo as duas
pontas **não** compartilham provedor, e a Testemunha **deixa de ser mínima** —
passa a ser votante de Raft, com certificados e snapshots.

**O que fica no consenso e o que não fica, pelo §3:** só o estado de arbitragem
— época, ativa, papéis, atestações vigentes. O event store e o histórico seguem
em Postgres.

**As outras três respostas do §7, todas de 2026-10-09:**

| § | decisão | razão registrada |
|---|---|---|
| 7.3 camada C | streaming **síncrono** + o backup que já existe; **sem** consenso para o store. A minoria **recusa** fatos. | "recusar é melhor que fingir": minoria que continua aceitando cria uma **segunda história**, e reconciliar histórias de autoridade é problema sem solução automática. Síncrono significa que a escrita **bloqueia** quando a réplica está fora — é *fail-closed*, coerente com a CLM-0003, e **tem de estar escrito porque vai parecer indisponibilidade**. |
| 7.4 `activation_certificate_id` | **junto do F3**: na Opção B o lease **é** o certificado. | a função dele já é cumprida pela época (CLM-0004 TESTED), e duas amarras para a mesma garantia com mecanismos diferentes é pior que uma — regra do próprio ADR-002. **Condição posta pelo titular: adiar é legítimo, deixar silencioso não.** |
| 7.5 promoção não planejada | **automática sim**, e a atestação **continua pré-condição**. | "o **quorum** decide **quem**; a **atestação** decide **se**". Com três votantes, ACTIVE e SUCCESSOR são maioria — as duas partes **interessadas** podem promover uma à outra, e a Testemunha é a única desinteressada. E: o caso automático é o que acontece de madrugada sem ninguém olhando, logo é o que **mais** precisa de supervisão. |

---

## 2. As opções recusadas, e o motivo

**A — replicação física do Postgres (streaming).** Recusada como mecanismo da
camada A. Ela replica bytes, não decide quem manda: numa partição a réplica
promovida e a primária isolada são duas autoridades, e o fencing local não as
distingue — é precisamente o que o §F2 da prova deste ciclo mede acontecendo.
Sobrevive como mecanismo da **camada C**, que é onde o §7.3 a colocou.

**C — estado de autoridade derivado do event store.** Recusada pela objeção do
próprio ADR-003 §3: *"não resolve replicação: transfere a pergunta para o
store"*. E na linha de partição: *"o event store precisa ser ele próprio
replicado — e volta-se a A (streaming) ou a B (consenso para o log de fatos).
Dois stores que divergem numa partição são duas histórias; o replay dá duas
épocas"*. Serve como **forma dos eventos** (auditabilidade), não como mecanismo.

**Não fazer nada.** Recusada por medição, não por preferência: ver §4.

---

## 3. O custo, remedido em 2026-10-13 (C25-04) — e por que o antigo não servia

O orçamento de 2026-10-01 dizia **US$ 12 a 36/mês**. Ele **não se aplica**, e o
motivo não é inflação: aquele orçamento era de **hospedar a aplicação** — porte
medido de 92,5 MiB para a ACTIVE e 24 MiB para a Testemunha. A Opção B põe um
**nó de consenso**, e nó de consenso **não é aplicação**: ele escreve cada
requisição em disco numa **maioria** dos membros.

**Pela recomendação do etcd**, lida em `etcd.io/docs/v3.5/op-guide/hardware/` em
2026-10-13 — *"two to four cores"*, *"Typically 8GB is enough"* —, e pelo preço
do mesmo provedor que o documento de 01/10 já usava:

```
três nós pagos, conforme a recomendação        US$ 144/mês
dois pagos + Oracle Always Free                US$  96/mês
o orçamento de 01/10 (aplicação, não consenso) US$  12 a 36/mês
```

**Ressalva que impede ler isso como veredito:** o etcd apresenta as figuras como
**recomendações, não mínimos**. Rodar em 2 GiB pode funcionar e **não foi
testado**. O que está medido é o preço do que a documentação recomenda.

**A opção gratuita existe, é de porte folgado, e o que a inviabiliza está escrito
pelo fornecedor.** Oracle Always Free dá *"2 OCPUs total"* e *"12 GB total"* por
US$ 0 — acima do que o etcd recomenda. E a mesma página diz: *"Idle Always Free
compute instances may be reclaimed by Oracle"*, onde ocioso é, por 7 dias, CPU
p95 < 20%, rede < 20% e memória < 20%. **Um nó de consenso saudável num sistema
quieto é exatamente esse perfil** — ele existe para não ter trabalho. A cláusula
não cobra dinheiro: cobra **atividade**, e atividade é o que o desenho não tem.

**A cauda do `fsync`, e ela é o número operacional.** Sete execuções em
2026-10-13: mediana estável entre 0,664 e 0,738 ms, p95 ≤ 1,53 ms em seis — e
**uma** com p95 de 92,75 ms e máximo de 123,4 ms. A mediana quase não se move; o
que explode é só a cauda. É o modo de falha que o etcd descreve: *"disk activity
from other processes causes long fsync latencies"* → heartbeat perdido → perda
temporária de líder. **Um droplet de US$ 12 a 48/mês é disco compartilhado, e o
vizinho não é seu.**

---

## 4. A consequência para os 8 repositórios que consomem o pacote pinado

Medido em 2026-10-13 nos 19 repositórios rastreados. Consumidores do pacote: **8**
(o `liceu-protocol` é o pacote, não consumidor).

| repositório | pino hoje |
|---|---|
| `LICEU_6.0_CONSTRUTORA_VIRTUAL` | `@v0.26.0` |
| `liceu-genome` | `@v0.26.0` |
| `3C273-Analytics-Data-Science/cefeida/backend` | `@v0.24.0` |
| `ANCHOR.OS-LICEU6.0/backend` | `@v0.24.0` |
| `Archimedes-ImobTech-LICEU-6.0-` | `@v0.24.0` |
| `FORNECEDORES-LICEU-6.0/backend` | `@v0.24.0` |
| `HUB-BACKOFICE-LICEU-6.0` | `@v0.24.0` |
| `John-Brasileiro-/backend` | `@v0.24.0` |

**Seis dos oito estão duas versões atrás.** Isso não é dívida de arrumação: é a
consequência de topologia aparecendo antes da topologia.

**Por que a Opção B toca esses oito, e não só o CORE.** Com um CORE por domínio
consumindo um control plane extraído, o que hoje é **chamada em processo** vira
**caminho de rede**. Medido em 2026-10-09 (PRF-0115): o módulo tem 763 linhas,
**dez gravações diretas** no banco do CORE e **três leituras do event store por
SQL**; `_audit` grava `AuditEvent` direto, então os quatro `event_type`
`authority.*` que o CORE emite são **linhas de tabela e não fatos contratados**;
e `_latest_fact` lê `archimedes.planning.state` e `cefeida.evidence.published`,
que são **fatos de domínio da cadeia**.

Três consequências que recaem sobre os oito:

1. **Fato que atravessa fronteira precisa de contrato.** Os quatro contratos que
   faltam para os `event_type` `authority.*` deixam de ser lacuna de catálogo e
   passam a ser **pré-requisito da extração** (PRF-0110).
2. **A leitura de fatos de domínio pelo plano de autoridade muda de natureza** —
   ou se mantém um caminho de leitura dentro do store do CORE, e volta a objeção
   que o ADR faz à opção C, ou essa leitura passa a ser outra coisa.
3. **Um pino atrasado deixa de ser atraso e passa a ser incompatibilidade.** Hoje
   os seis em `v0.24.0` funcionam porque falam com o CORE em processo ou por uma
   superfície estável. Com o plano noutro domínio, a versão do kit passa a ser
   **parte do instrumento** da conversa — a mesma classe do escopo da FIT-019,
   aplicada ao tempo em vez do espaço.

**Ordem que isso impõe, e ela não é opinião:** mover os seis pinos é
**pré-requisito** da extração, não limpeza posterior.

---

## 5. O que esta decisão **não** fecha

### 5.1 Não decidido — e é decisão do titular, não medição

- **etcd ou Raft embutido** na camada A. A UNK-0001 nomeia isso como pendente, e
  nada neste ciclo o decidiu. O custo do §3 foi levantado **pela recomendação do
  etcd**; um Raft embutido teria outro porte e outro orçamento.
- **A separação dita em contrato:** *"votar no log"* **não é** *"autorizar
  atos"*. Sem essa separação escrita, ou a Testemunha vota e viola "nunca
  autoriza", ou não vota e volta o caso do §7.2 — dois nós de consenso mais um
  observador **não têm maioria** numa partição. É redação, não infraestrutura, e
  já não espera mais nada.
- **A preservação explícita da porta `promotion_requires_witness_attestation`**
  (PRF-0114). B troca a **fonte** da época, não a **porta**. Com três votantes,
  ACTIVE e SUCCESSOR são maioria: se `promote()` virar "proposta aceita pela
  maioria" sem preservar a porta, promove-se **sem** a Testemunha. E **não se pode
  presumir que o quorum a preserve**: a CLM-0086, que afirma exatamente isso, está
  **STALE** — perdeu toda a sustentação quando a FIT-019 rebaixou a PRF-0114 por
  falta de escopo declarado. Presumir seria apoiar-se numa afirmação sem prova vigente.
- **Se o portão `P1_07B_extracao_fisica` da Constituição se aplica.** Ele é
  `ADR_REQUIRED` com a razão "extração toca migrations, auth, Event Store,
  Codespaces e lineage". Foi escrito para tirar do CORE os domínios que o
  `core_nunca` lista, e esta extração tira uma função que o `core_somente`
  **admite** — então não é óbvio que valha. Mas a razão dele nomeia exatamente o
  que esta extração toca. **Se vale, falta uma ADR antes de qualquer código; se
  não vale, isso tem de ficar dito.**

### 5.2 Não mensurável — com a razão, nunca como estimativa

| o quê | por quê |
|---|---|
| **IOPS sequencial** dos provedores | nenhum dos dois publica. A Oracle não publica IOPS nenhum; a DigitalOcean diz só *"high-performance Solid State Drives (SSDs)"*. E o etcd exige **sequencial**, avisando que o concorrente publicado *"can be 10x greater"*. **O único número que o etcd exige é o único que ninguém publica** — resolve-se medindo na máquina alugada, o que exige alugá-la. |
| **RTT entre os provedores escolhidos** | não há provedores escolhidos. |
| **o multiplicador do caminho quente** | o C25-03 mediu que `enforce()` roda **a cada fato federado publicado** e lê duas coisas do lado que migraria. Logo o custo de B é **por fato publicado**, não por promoção, que é rara. Não existe série medida de publicação por unidade de tempo neste ecossistema. **Medir a taxa de publicação é pré-requisito de qualquer orçamento honesto da Opção B.** |
| **latência de `fsync` no alvo de deploy** | o alvo não existe: `docker-compose.vps.yml` exige `LICEU_PUBLIC_HOST` provisionado externamente e nenhum arquivo dos repositórios nomeia provedor ou máquina. |

### 5.3 Por que a UNK-0001 **não** fecha com este ADR

A incógnita pede a decisão **e** a sustentação dela. A decisão está aqui. O que
falta para fechá-la é o §5.1 — e, em particular, **etcd ou Raft embutido**, porque
sem isso o orçamento do §3 vale para um mecanismo que ainda não foi escolhido.

Fechar a UNK-0001 agora seria registrar como resolvida uma incógnita cujo custo
foi levantado para uma das duas alternativas. **É decisão do titular, e não deste
documento.**

---

## 6. O que o ciclo 25 mediu e que esta decisão passa a carregar

A prova de sucessão de 2026-10-13 (`infra/authority/prova_de_sucessao.py`, 16
passa / 0 falha / 1 não-mensurável, três execuções idênticas) mediu três coisas
que mudam como a Opção B deve ser lida.

**Primeira: hoje a segurança vem de COMPARTILHAR UMA LINHA, não de consenso.**
Com as duas Mães no mesmo store, a Mãe revivida lê a época nova e se declara
`RETIRED`, e não serve nem sob a época velha nem sob a nova. As duas **não**
servem a mesma época — porque **há uma só linha**. Isso é o ponto único que a
Opção B existe para remover, e a remoção **troca** a garantia de lugar: sai de
"uma linha" para "uma maioria". Até que a maioria exista, remover a linha é
perder a garantia.

**Segunda: com dois stores, nada amarra os dois lados.** Medido: duas Mães se
declaram `ACTIVE` ao mesmo tempo, em épocas diferentes, **e as duas servem** —
HTTP 200 nas duas. Nenhum mecanismo detecta o outro lado: busca em
`cv-backend-core/app` em 2026-10-13 dá `replica` 0, `replication` 0, `etcd` 0,
`quorum` 0, `consensus` 0, `streaming` 0, `standby` 0 (as ocorrências de `raft` e
`lease` são "draft" e "release"). **Este é o split-brain do §F2, e é o argumento
mais forte que existe a favor de B** — e também a medida exata do que B tem de
entregar.

**Terceira: a assinatura não arbitra.** No mesmo passo, as **duas** respostas de
`/authority/whoami` saem com assinatura **VALIDA**: cada processo diz a verdade
sobre o próprio store. O Ed25519 do ciclo 25 dá **atribuição**, não arbitragem.
**Ele identifica quem respondeu; não decide quem manda** — e registrar isso aqui
é o que impede de parecer que o trabalho de identidade resolveu replicação.

---

## 7. Consequência imediata, e ela é curta

Três trabalhos já não esperam mais nada, e nenhum é infraestrutura:

1. a separação **"votar no log" × "autorizar atos"** dita em contrato;
2. os **quatro contratos** dos `event_type` `authority.*`;
3. a preservação explícita da porta `promotion_requires_witness_attestation`.

E um quarto, que a medição deste ciclo acrescentou e que é pré-requisito e não
arrumação: **mover os seis pinos de `v0.24.0`**.
