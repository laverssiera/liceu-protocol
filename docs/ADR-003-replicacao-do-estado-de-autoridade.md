# ADR-003 — Replicação do estado de autoridade (o F3 real)

**Estado:** proposta em 2026-09-21. Sem decisão. Levantamento e desenho; nada implementado.
**Origem:** levantamento do P5/P7 (ciclo 5): as três Mães são linhas na mesma tabela do mesmo Postgres; a Constituição afirma que a Sucessora "mantém estado replicado" e não há mecanismo em código. Três máquinas com as Mães numa tabela só são **um** domínio de falha.

```
PROBLEMA     "F3 = três máquinas em domínios de falha distintos" pressupõe um estado
             de autoridade que exista em três lugares. Ele existe em um.
CAUSA        o control plane vive DENTRO do CORE, num Postgres; as Mães são
             identidades (segredos), não processos; a Testemunha não observa nada
             por conta própria — declara um veredito num POST ao mesmo CORE.
INVARIANTE   P01: ONE AUTHORITATIVE STATE → ONE DOMAIN OWNER. Split-brain aqui não
             é dado inconsistente; é DUAS AUTORIDADES.
```

## 1. O que existe hoje — lido no código

### 1.1 Onde o estado de autoridade vive

Tudo em `cv-backend-core/app/models/authority.py`, quatro tabelas, **um** Postgres (`db_core_os`, volume `db_core_os_data`, compose do CORE):

| tabela | o que guarda | quem escreve |
|---|---|---|
| `authority_state` | uma linha por federação: `authority_epoch` (monotônico), `active_instance_id`, `issuer_instance_id` | só `promote()` |
| `authority_instances` | `instance_id → role` (ACTIVE / SUCCESSOR / WITNESS / RETIRED), `role_since_epoch` | semeadura inicial (`AUTHORITY_INITIAL_ROLES`) e `promote()` |
| `authority_attestations` | o que a WITNESS **declarou** ter observado: `observed_epoch`, `observed_active_instance_id`, `verdict`, `concur_promotion_of`, `expires_at` (TTL), `consumed_by_epoch` | só `attest()` |
| `authority_escalations` | D-040: escalação ao humano com dossiê quando a promoção não tem atestação | `promote()` via `escalate_to_human()` |

Mais o que o control plane **lê** sem ser tabela sua: `EventLog` (o event store, mesma base — o dossiê do D-040 lê os últimos fatos por tipo), `AuditEvent` (mesma base), os segredos de instância (`CANONICAL_SERVICE_INSTANCE_SECRETS`, config), e a **lei** (kit `liceu-protocol` instalado por tag — tetos por produtor no Producer Registry, C2).

### 1.2 O que a promoção precisa ler para decidir

`promote()` (`authority_control_plane.py:341`), na ordem:

1. `authority_state.authority_epoch` — a época vigente (`expected = current + 1`).
2. `authority_instances.role` do chamador (ACTIVE ou SUCCESSOR) e do alvo (tem de ser SUCCESSOR).
3. `authority_attestations`: a mais recente **na época vigente**, não expirada, não consumida, que **concorde** com promover o alvo (`valid_attestation_for`, `:519`). Sem ela: não promove, escala ao humano.

E escreve, na mesma transação: papel antigo → RETIRED, alvo → ACTIVE, `epoch + 1`, `active/issuer`, atestação `consumed_by_epoch`, auditoria.

Isso é **o** estado que precisa existir em mais de um lugar. É pequeno: três linhas e uma lista curta de atestações. O resto (fatos, auditoria) é histórico.

### 1.3 O fencing (F1) — o que já funciona

`enforce()` (`:286–309`): todo fato que carrega `authority_epoch` é comparado com `authority_state.authority_epoch`; menor → 409 `authority_epoch_stale`; maior → 409 `authority_epoch_ahead`; instância de autoridade sem época → 409. O CORE **carimba** a época vigente em todo fato aceito. Testado (`test_stale_epoch_is_rejected_even_with_instance_online`, `test_epoch_ahead_of_current_is_rejected`, `test_epoch_never_decrements_or_jumps`).

A Constituição diz por que isso funciona sem quórum: *"a monotonicidade da época é arbitrada pelo Event Store, que já é ponto de serialização"* (`liceu_constitution.yaml`, AUTHORITY_EPOCH). **Ponto de serialização = um.** O fencing é correto exatamente porque há um só árbitro. Replicar o árbitro é o problema deste ADR.

### 1.4 A Testemunha — o que ela observa de fato

`attest()` (`:453`): a WITNESS **envia** `observed_active_instance_id` e `verdict` (`ACTIVE_HEALTHY | ACTIVE_DOWN | BOTH_DOWN`) num `POST /authority/attest` ao CORE. O CORE verifica o papel, a época e as regras (não concorda consigo mesma; não concorda com BOTH_DOWN) e **grava o que ela declarou**. Não há sonda: nenhum código no CORE, nem em repositório algum, em que a Testemunha vá até a Ativa e olhe. A "observação" é auto-declarada pelo cliente que detém o segredo de `mother-witness`, e é gravada **no mesmo Postgres** em que a Ativa grava a época.

Consequência: hoje a Testemunha não é independente de nada — não porque o desenho esteja errado, mas porque **ela ainda não existe como processo**. Existe como segredo.

### 1.5 O que as três Mães são hoje

```
Constituição      três instâncias de liceu.authority: mother-a, mother-b, mother-witness
código            três chaves em CANONICAL_SERVICE_INSTANCE_SECRETS + três linhas em authority_instances
processos         UM: o CORE (cv-backend-core), com UM Postgres
control plane     dentro do CORE (authority_control_plane.py)
```

Não há três CORE. Não há "processo Mãe". Quem chama `/authority/promote` com o segredo de `mother-b` *é* a Mãe B naquele instante. O domínio de falha do estado de autoridade é o domínio do `db_core_os`. **Ponto.** Três VPS não mudam isso enquanto o Postgres for um.

Dois detalhes da Constituição que o código não tem: `activation_certificate_id` (campo obrigatório declarado na classe de autoridade; zero ocorrências no CORE) e o "estado replicado" da Sucessora (`o_que_a_Mae_SUCESSORA_precisa.estado_replicado`: tetos, decisões em curso, época). Dos três: os **tetos** hoje vivem no kit (Producer Registry, `teto` por produtor) — replicados por tag de pacote, não por banco; as **decisões em curso e escalações** estão em `authority_escalations` (mesma base); a **época** em `authority_state`.

## 2. O que precisa ser replicado (pergunta 1)

Separar em três camadas, porque têm mecanismos e exigências diferentes:

| camada | conteúdo | tamanho | exigência |
|---|---|---|---|
| **A — estado de arbitragem** | `authority_state` (época, ativa, emissora), `authority_instances` (papéis), `authority_attestations` vigentes (não expiradas, não consumidas) | dezenas de linhas | **linearizável**: uma única sequência de épocas visível igual em todos os domínios; é o que o fencing compara |
| **B — histórico de autoridade** | atestações passadas, `authority_escalations`, `AuditEvent` de fencing/promoção/atestação | cresce | durável e ordenado; pode chegar com atraso |
| **C — o event store** | `EventLog` (os fatos, com época carimbada, `idempotency_key`) | cresce muito | durável; a guarda de identidade (ADR-002) precisa ver a chave já gravada antes de aceitar a próxima |
| **lei** | o kit (contratos, registries, tetos) | por tag | já replicada: `pip install @vX.Y.Z` — as três Mães validam sob a mesma lei se fixarem a mesma tag (ADR-001) |
| **segredos** | `CANONICAL_SERVICE_INSTANCE_SECRETS` | config | por domínio; são seus |

O que a Constituição chama "estado replicado" é a camada **A**. É pequena e é a única que precisa de linearizabilidade. As camadas B e C precisam de durabilidade — o backup do P7 (CORE #53) já as cobre contra perda, não contra partição.

## 3. As opções — sem escolher

Para cada uma: partição de rede, como a Testemunha observa, o que muda no fencing do F1.

### A — replicação física do Postgres (streaming)

Um primário, réplicas assíncronas/síncronas em outros domínios. O CORE (um ou três) escreve no primário.

| | |
|---|---|
| partição | o primário está **num** domínio. Se esse domínio cai, promover a Mãe B exige promover a **réplica** a primário — e isso é uma segunda eleição, do banco, que precisa de um árbitro (Patroni + etcd/Consul, ou humano). Se dois lados promovem réplicas, há duas épocas: **split-brain de banco = duas autoridades** — exatamente o que P01 proíbe. Com replicação síncrona, a partição para a escrita (fail-closed); com assíncrona, o lado promovido pode não ter a última época |
| Testemunha | lê **a mesma réplica** que replica a Ativa. Confirma o que o armazenamento diz — inclusive quando errado. Não é testemunha; é réplica. Para ser testemunha precisaria de canal próprio até a Ativa (sonda) **e** de um lugar próprio para gravar o que viu que não seja o primário da Ativa |
| fencing F1 | inalterado em código: a época continua na tabela. Mas o **árbitro** da monotonicidade vira "quem for primário agora" — a garantia passa a depender do mecanismo de failover do banco, fora do protocolo |
| custo | conhecido, operável; Postgres gerenciado oferece pronto. Nenhuma mudança no CORE. Move o problema para a camada de infra, onde o protocolo não o vê |

### B — protocolo de consenso (Raft/etcd) para a camada A

Só o estado de arbitragem (época, ativa, papéis, atestações vigentes) vive num cluster de consenso com 3 nós em 3 domínios. O event store e o histórico continuam em Postgres (com A ou com backup).

| | |
|---|---|
| partição | o lado com maioria escreve; o minoritário **não consegue avançar a época nem renovar a ativação**. Uma Mãe isolada continua viva, mas não consegue provar que é ativa — se o CORE consultar o consenso antes de aceitar fato autoritativo (lease/term), os fatos dela param na fronteira. É o desenho canônico de eleição com fencing (term = época) |
| Testemunha | é um **nó do consenso** noutro domínio: observa a Ativa pelo protocolo (heartbeat/lease), não pelo armazenamento. Grava a atestação no log replicado — que não é o banco da Ativa. **Tensão com a Constituição**: um nó Raft **vota**; a Testemunha "só informa, nunca autoriza". Resolvível: o voto de Raft é sobre *quem é líder do log*, não sobre *autorizar atos* — mas isso tem de ser dito no contrato, porque hoje `attest()` proíbe a Testemunha de qualquer ato além de atestar |
| fencing F1 | a época deixa de ser coluna e vira **term** do consenso; `enforce()` passa a ler a época do cluster (ou de um cache com lease curto), não de `authority_state`. A guarda é a mesma; a fonte muda. `promote()` vira "propor no log" |
| custo | dependência nova (etcd ou um Raft embutido), operação nova (3 nós, snapshots, certificados), e o CORE ganha um cliente de consenso no caminho crítico de publish. É o que Kubernetes, Patroni e todo sistema de eleição usam — e é exatamente por isso que existe |

### C — estado de autoridade derivado do event store

Promoção, atestação e semeadura viram **fatos** (`authority.epoch.promoted`, `authority.witness.attested`) no event store; cada Mãe reconstrói época e papéis por replay. "O CORE é o replay." O fato é a replicação.

| | |
|---|---|
| partição | o event store **precisa ser ele próprio replicado** — e volta-se a A (streaming: um primário, mesma eleição de banco) ou a B (consenso para o log de fatos: mais caro que consenso só para a camada A). Dois stores que divergem numa partição são **duas histórias**; o replay dá duas épocas. Sem árbitro único de ordem, o replay não resolve o que a partição criou |
| Testemunha | lê o mesmo store. Mesma objeção de A, a menos que a atestação seja gravada num store que não seja o da Ativa — e aí há dois stores a reconciliar |
| fencing F1 | a época é derivada (último `authority.epoch.promoted` no replay). `enforce()` precisa do replay atualizado a cada aceite ou de um cache — e o cache é a camada A de novo |
| custo | coerente com a ideia do ecossistema, mas não resolve replicação: **transfere** a pergunta para o store. Serve como *forma* dos eventos (auditabilidade), não como *mecanismo* |

### Comparação em uma tela

```
                         A · streaming        B · consenso (camada A)   C · replay do store
árbitro da época         primário do banco    o quórum                  o store (que precisa de A ou B)
partição                 2 primários = 2      minoria não avança        2 stores = 2 histórias
                         autoridades          época (fail-closed)
Testemunha observa       a réplica (=Ativa)   o protocolo (heartbeat)   o store (=Ativa)
Testemunha grava em      primário da Ativa    log replicado (próprio)   store (=Ativa)
é testemunha?            não — é réplica      sim, se o contrato        não, sem store próprio
                                              separar votar de autorizar
fencing F1               inalterado, mas      época = term; enforce lê   época derivada; enforce
                         árbitro fora do      do cluster                 precisa de replay/cache
                         protocolo
muda no CORE             nada                 enforce/promote/attest     modelo de eventos +
                                              leem/escrevem no cluster   reconstrução
dependência nova         failover do banco    etcd/Raft                  nenhuma (mas herda A ou B)
```

A e B não são excludentes: B para a camada A (arbitragem), A ou backup para B e C (histórico e fatos). C é forma, não mecanismo — pode conviver com qualquer uma como o **registro** do que o consenso decidiu.

## 4. A pergunta que decide (pergunta 3)

> A Testemunha pode observar a Ativa por um caminho que não passe pelo mesmo armazenamento? Se não puder, ela não é testemunha — é réplica.

Hoje: **não pode, porque não observa.** `attest()` recebe um veredito e o grava. Para a Testemunha ser testemunha, duas coisas têm de existir, independentemente da opção:

1. **Uma sonda própria**: a Testemunha, como processo no seu domínio, verifica a Ativa por um canal que não seja o banco — HTTP `/authority/state` assinado pela instância (com época), ou heartbeat no NATS com o segredo de `mother-a`. O que ela grava em `observed_active_instance_id`/`verdict` passa a ser **resultado de sonda**, não declaração.
2. **Um lugar próprio para gravar**: a atestação não pode viver só no Postgres da Ativa. Em B, é o log de consenso. Em A ou C, é preciso um store da Testemunha (mínimo: um arquivo/log assinado no domínio dela) que `promote()` consulte além do próprio banco — e aí `valid_attestation_for()` lê de dois lugares e exige que batam.

Sem (1), qualquer opção replica uma declaração. Sem (2), qualquer opção grava a declaração onde a Ativa manda. **A opção escolhida para a camada A determina se (2) vem de graça (B) ou tem de ser construído (A, C).**

## 5. O que muda no fencing do F1, por opção — resumo

| | onde `enforce()` lê a época | quem incrementa | o que a partição faz |
|---|---|---|---|
| A | `authority_state` no primário | `promote()` no primário | depende do failover do banco; pode dar 2 épocas |
| B | term do cluster (lease curto) | proposta aceita pela maioria | minoria não incrementa; Ativa isolada perde a prova de ativação |
| C | último fato de promoção (replay/cache) | fato aceito no store | depende de como o store é replicado |

Em B, o teste `test_stale_epoch_is_rejected_even_with_instance_online` continua verdadeiro **e ganha a partição** como caso: a antiga Ativa isolada tenta publicar com a época que tinha e é recusada — pela maioria, não por uma tabela que ela mesma poderia ter.

## 6. Custo operacional para quem opera sozinho

O §3 dá o custo de cada opção em termos de sistema. Falta a pergunta que decide na prática de quem mantém isto sem equipe: **o que acontece às 3h da manhã, sozinho.**

```
                          A · streaming          B · consenso            C · replay do store
o que sobe a mais         1 réplica + árbitro    3 nós (etcd/Raft)       nada
                          de failover
quem decide o failover    você, ou um árbitro    o quórum, sozinho       você (o store não decide)
                          que também precisa
                          ser operado
falha típica              lag silencioso: a      cluster perde quórum    projeção atrasada: um
                          réplica esta atrás     e TODO publish para,    publish entra sob época
                          e ninguem avisa        se enforce depender     antiga numa janela curta
                                                 dele sem cache
o que voce faz as 3h      decidir promover sem   restaurar um nó; nada   reprocessar o replay;
                          saber o lag; e a       de decisao humana no    o store nao perdeu nada
                          decisao mais cara      caminho critico
                          do conjunto
reversivel?               sim — e topologia,     dificil: o estado de    sim — a projecao se
                          o dado nao muda        autoridade migrou       reconstroi dos fatos
                          de forma               para fora do Postgres
ensaio necessario         failover manual        matar 1 de 3 nos e      derrubar e reconstruir a
                          cronometrado           medir o publish         projecao com o store vivo
```

Três leituras deste quadro, sem escolher por você:

- **A é a mais barata de subir e a mais cara de usar**: a única em que a decisão difícil (promover ou não, com lag desconhecido) cai sobre uma pessoa, acordada, sob pressão. E é a única que **não** responde ao §4 — a Testemunha continua lendo a Ativa.
- **B é a única que não exige presença humana no failover**, e é a que mais exige presença no resto: três nós, certificados, snapshots. Para um operador único, o risco muda de forma — deixa de ser "eu decido errado" e passa a ser "o quórum cai e o ecossistema inteiro para de publicar". Esse segundo risco é mitigável (cache com lease no `enforce`), e a mitigação tem de estar no plano, não no improviso.
- **C não sobe nada novo e cobra em código**: contratos, projeção, replay, e cuidado com a circularidade no boot (o CORE precisa saber a época para aceitar fatos, e a época vem de fatos). Em compensação, é a única cujo modo de falha é *reversível lendo o que já existe* — e a única que casa com o resto do ecossistema, onde "o que é verdade" já é fato publicado.

Nenhuma das três dispensa o item (1) do §4 — a sonda própria da Testemunha. Ela é trabalho seu em qualquer topologia, e sem ela a `CLM-0006` continua REFUTED mesmo com a replicação pronta. Seria falso dizer o contrário.

## 7. Perguntas em aberto para quem decide

1. **Quem é a Mãe: o CORE ou um processo à parte?** Três Mães = três CORE completos (cada um com kit, boundary, store) ou um control plane extraído do CORE (só a camada A) e um CORE por domínio consumindo-o? A segunda é menor e é a que B pede.
2. **A Testemunha vota?** Em B, é nó de consenso. A Constituição diz "só informa". Ou se separa em contrato *votar no log* de *autorizar atos*, ou a Testemunha fica fora do quórum (2 nós de consenso + 1 observador — e 2 nós não têm maioria numa partição: volta-se a "duas Mães sem quórum", que a própria Constituição reconhece).
3. **Camada C (event store) — A ou backup?** O store não precisa de consenso se a guarda de identidade (ADR-002) aceitar que, numa partição, o lado minoritário **não aceita fatos** (fail-closed pelo item B). Se aceitar, streaming síncrono + backup basta. Se não, é consenso para tudo — e o custo muda de escala.
4. **`activation_certificate_id`** — a Constituição o exige; o código não o tem. Em B ele é natural (o lease). Fica para o F3 ou para antes?
5. **Promoção não planejada** — a Constituição deixa `modo: A DEFINIR`. B a torna possível (lease expira → sucessora propõe); A e C a deixam manual ou dependente do banco. A decisão sobre o mecanismo é também a decisão sobre se a promoção automática existe.

Sem implementação até a decisão. O 5/5 não depende disto (é LOCAL, uma Mãe, um domínio). Continental depende: é a primeira vez que um ato acima de LOCAL exige que a Mãe prove que é ativa — e hoje ela prova consultando a si mesma.
