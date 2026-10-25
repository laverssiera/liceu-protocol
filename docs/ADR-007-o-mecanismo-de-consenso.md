# ADR-007 — O mecanismo de consenso da camada A: etcd ou Raft embutido

**Status:** DECIDIDO pelo titular em 2026-10-25: **etcd, Opção A**. A palavra, literal: *"Minha palavra é etcd (Opção A do ADR-007)."* A recomendação e a comparação abaixo são da redação e ficam como estavam no momento da decisão.
**Decisão, execução e comprovação são estados distintos** (regra de 2026-10-09): a escolha está registrada; nenhum etcd foi instalado, e a camada A continua no `authority_state` de cada processo, com a réplica de uma linha do PASSO F.
**Data:** 2026-10-25 · **Responde:** UNK-0001, partes 2 e 3 do PASSO G do roteiro v2 · **Continua:** ADR-003 (as opções), ADR-005 (a decisão da Opção B).

> **O que este documento é.** O ADR-005 registrou, em 2026-10-13, a decisão do titular pela **Opção B**: consenso para a camada A, com três votantes em três domínios e a Testemunha como votante. No §5.1, ele deixou uma escolha em aberto: **etcd ou Raft embutido**. Ela continua aberta, e é ela que este ADR prepara.
>
> **O que mudou desde então, e por que a pergunta voltou à mesa.** O roteiro v2 (20/10) admitiu que a palavra *"pode nem ser necessária, se o passo F mostrar que a arbitragem está na aplicação"*. O passo F mostrou o contrário (§1). Então o consenso fica, e resta escolher qual.

---

## 1. A parte 2 do PASSO G: o mecanismo de dupla gravação **existe**, e está medido

O roteiro pede: *"o que, na topologia, pode produzir duas réplicas graváveis? Nomeie o mecanismo, ou prove que nenhum existe."*

**Ele existe, e tem três peças.** O split-brain de escrita do PASSO F, no laboratório das três Mães (PRF-0309, CONSTRUTORA #115), executou cada uma delas:

| peça | o que ela faz | por que não arbitra entre planos |
|---|---|---|
| **um plano por armazenamento** | cada processo aceita `promote()` contra o **próprio** `authority_state` | sob partição, há dois planos, e cada um decide sozinho |
| **a porta da atestação** | `promotion_requires_witness_attestation` exige concordância da Testemunha | a atestação é consumida **uma vez por armazenamento** (`consumed_by_epoch`), e cada plano tem a sua |
| **o avanço de exatamente 1** | `authority_epoch_not_monotonic` | é conferido contra a época do **próprio** armazenamento, e os dois estavam na 1 |

A Testemunha, a única peça que vê os dois lados, **concordou duas vezes**, porque nada no código dela registra "já concordei nesta época". **Os dois `promote()` concorrentes deram 200 e escreveram a época 2.** A réplica de uma linha (PRF-0308) só **detecta** o segundo escritor (409 `replica_two_writers`), e detecta depois que as duas escritas já aconteceram.

Pela regra que o roteiro fixou **antes** de medir: *"Se os dois tiverem sucesso, 'durável não linearizável' é insuficiente E ISSO É O RESULTADO — a UNK-0001 volta a pedir consenso."* Logo vale o ramo 3 da parte 2: *"aí, e só aí, entra consenso, e a escolha etcd/PySyncObj volta à mesa — agora contra a lista de propriedades que o model check produziu, e com o I3 já resolvido fora do log."*

---

## 2. A régua: o que o log tem de dar, pelo model check

`liceu-genome/tools/modelo/autoridade.py` foi rodado de novo em 2026-10-25. É busca exaustiva, com as mutações conferidas pelo `--self-test`.

| invariante | exige do log |
|---|---|
| I1 — uma instância por época (o escritor único) | **P4** durabilidade **e P5** líder único por época |
| I2 — época monotônica | P2 **ou** P5 (condicional: só quebra sem os dois) |
| I4 — a Testemunha não inventa | **P4** |

- **Necessárias isoladamente: P4 e P5.** Sem P5, o I1 quebra em 915 estados. Sem P4, o I1 e o I4 quebram em 180.375.
- **P1 e P3 não são exigidas neste modelo.** O próprio verificador avisa que isso **não as torna dispensáveis**: ele não exercita conflito por índice nem leitura obsoleta que leve a violação de segurança.
- **O I3 já está resolvido fora do log.** O PASSO B escolheu validação na escrita, e a PRF-0267 mediu que, com a cerca no efeito, as cinco propriedades bastam. O que faz o fencing valer é a cerca, que é protocolo, e não o log.

**O que a régua implica para a escolha.** Qualquer Raft correto entrega **P5** (um líder por termo) e **P2** (termos que só crescem) por protocolo. A diferença entre os candidatos não está em P5. Está em **P4 de verdade**, ou seja, no que vai ao disco antes de o commit ser confirmado, e em **quanto o candidato perturba o processo que hospeda o CORE**.

---

## 3. As opções

### A — etcd, processo separado (recomendada, e ESCOLHIDA pelo titular em 2026-10-25)

- **P4 tem régua publicada.** O etcd exige p99 de `wal_fsync_duration_seconds` abaixo de **10 ms** e 50 IOPS sequenciais (PRF-0175). Contra essa régua, seis amostras medidas passam com margem de cerca de 6,5×, e uma falha por cerca de 9,3×. Ou seja, o P4 dele **é conferível no host alvo**, e a falha conhecida é de host, não de mecanismo.
- **Não divide o GIL com o CORE.** É um processo em Go, ao lado. A eleição dele não depende de quanto tempo um handler Python segura o interpretador.
- **Custo:** pela recomendação do etcd, o nó custa cerca de 4× mais que o orçamento da aplicação (PRF-0142), e o preço não cai com a carga baixa da camada A (no máximo 288 escritas por dia, PRF-0173), porque o que ele compra é disco, não capacidade. **O custo não é condição deste ADR** (roteiro v2, parte 3): é pergunta de operação.

### B — Raft embutido no CORE: PySyncObj (recusada)

- **É uma opção só, não um campo de opções.** O raftify foi descontinuado em Python pelo próprio autor, e o rraft-py é binding não oficial que entrega só o módulo de consenso. A própria página do rraft-py diz que não há biblioteca Raft padrão em Python (PRF-0174). Escolher B é apostar no PySyncObj 0.3.17 e na manutenção dele.
- **Divide o GIL com o CORE, e a margem medida é estreita.** A retenção do GIL sob 12 threads deu p99 de 50 ms e máximo de 154,7 ms (PRF-0197). Somada à pior cauda de fsync do mesmo dia (183,1 ms), dá **338 ms contra os 400 ms** do `raftMinTimeout`, com folga de 62 ms, **numa máquina que não é o alvo**. E isso é **limite inferior** (PRF-0200): num processador mais lento, a mesma seção segura o GIL por mais tempo. A eleição espúria não está excluída. Também não está provada, e é exatamente por isso que ela é risco.
- **O P4 dele não foi conferido.** Esta redação **não leu** o código do journal do PySyncObj, e não afirma se ele faz fsync a cada entrada antes de confirmar o commit. Para a régua do §2, essa é a pergunta decisiva, e ela fica **em aberto** contra esta opção. Se o titular preferir B, ela é a primeira coisa a medir.

### C — a Testemunha como árbitro único por época (considerada e recusada)

Uma Testemunha que concede concordância **uma vez por época** e **para um plano só** daria P5 sem consenso: seria o "log que recusa o segundo líder" com um nó só. É o que o PASSO F deixou como candidato não medido.

**Foi recusada sem medir, e por desenho, não por custo.** Ela devolve a segurança a um ponto único, o disco da Testemunha. Se esse registro se perder, ela concede de novo, e o P4 do log de concessões, sem o qual o I1 quebra pelo §2, passa a depender de **um** armazenamento. É exatamente a troca que o ADR-005 §6 descreve e recusa: a Opção B existe para tirar a garantia de **"uma linha"** e pô-la numa **maioria**.

### D — não fazer nada além da réplica de uma linha (recusada por medição)

É a PRF-0309: dois escritores na mesma época. A réplica sobrevive (PRF-0308), mas **sobreviver não é ter um escritor só**.

---

## 4. A recomendação, e o motivo

**A — etcd.** Os três motivos são medidos, e nenhum é preferência:

1. **O P4 tem régua publicada e conferível no host alvo** (PRF-0175). O do PySyncObj não foi conferido.
2. **Não acopla a eleição ao GIL do CORE.** Com B, a margem medida contra o timeout de eleição é de 62 ms numa máquina mais rápida que o alvo provável (PRF-0197, PRF-0200).
3. **Não depende de uma biblioteca única** cujo ecossistema o próprio índice de pacotes mostra rarefeito (PRF-0174).

O que **pesaria a favor de B**, para ficar dito: um processo a menos para operar, e o custo do §3.A. Se a cauda de fsync do alvo (§5) e o journal do PySyncObj se mostrarem bons, a balança pode mudar. O custo, sozinho, não muda, porque não é condição deste ADR.

---

## 5. O que fica aberto

### 5.1 O ENVELOPE: pendente de host real e **NÃO-BLOQUEADOR do REGIONAL**

Pela parte 3 do roteiro v2, literalmente: cauda, custo e jitter ficam *"declarado[s] como pendente[s] de host real e declarado[s] NÃO-BLOQUEADOR[es] do REGIONAL"*. São pré-requisitos de **produção**:

- a cauda de `wal_fsync` no host alvo, contra os 10 ms do etcd (há uma amostra conhecida 9,3× fora);
- o RTT e o jitter entre os três domínios;
- o custo dos três nós.

### 5.2 Herdado do ADR-005 §5.1, e ainda aberto

- **"Votar no log" não é "autorizar atos"**, dito em contrato.
- **A preservação explícita da porta `promotion_requires_witness_attestation`** quando `promote()` virar proposta aceita pela maioria. A CLM-0086 segue STALE, e não se presume que o quorum a preserve.
- **Se o portão `P1_07B_extracao_fisica` se aplica** à extração da camada A.

### 5.3 O que esta decisão não fecha

- **Falha correlacionada:** a topologia de produção é o C27-02.
- **O exercício periódico (C27-07):** o laboratório versionado e descartável (`infra/laboratorio/` na CONSTRUTORA) torna o exercício barato. O roteiro manda instalá-lo **no fechamento**. Ainda não está instalado.

---

## 6. Como a UNK-0001 fecha

Com **a palavra do titular** sobre A ou B. Quando ela vier, o fechamento no genoma registra:

- a palavra, com data e autor;
- este ADR como sustentação: a parte 2 respondida pela PRF-0309, a régua do §2 e a comparação do §3;
- o envelope do §5.1 como **não-bloqueador declarado**.

Sem a palavra, a UNK-0001 continua **UNKNOWN**, com a pergunta respondida até onde a medição alcança. É a regra de parada G do roteiro, do lado bom: o mecanismo de dupla gravação está **nomeado**, e o que falta é escolher, não medir.
