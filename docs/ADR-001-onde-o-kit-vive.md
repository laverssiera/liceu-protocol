# ADR-001 — Onde o kit de protocolo vive

**Estado:** decidida em 2026-09-18.
**Decisão:** repositório próprio (`liceu-protocol`), pacote publicado, migração incremental.

```
FONTE          repositório próprio · dono único · sem governança extra
DISTRIBUIÇÃO   pacote publicado · exigido pelo consumidor externo
                                   e pela coerência das três Mães
MIGRAÇÃO       incremental · ARCHIMEDES e FORNECEDORES primeiro
```

## Contexto

O kit (Constituição 1.15.0, Contract/Producer/Event Registries, conformance kit
0.9.0, Federation SDK 0.4.0, registry checker 1.4.0, boundary checker 1.1.0) era
distribuído por cópia: `tools/liceu_protocol` no ARCHIMEDES e
`backend/tools/liceu_protocol` no FORNECEDORES (piloto), ambos com `MANIFEST`
verificado na CI e a nota *"vendor temporário até a ADR-001"*. Os outros 13
monólitos não tinham o kit. O CORE — o boundary que aceita os eventos — não tinha
kit nem registry.

Levantamento de 2026-09-18 (CORE #32, #34):

- As duas cópias vendorizadas eram **byte a byte idênticas** (MANIFEST 9/9 em ambas).
  A cópia não divergiu — mas não há mecanismo que impeça de divergir, nem que fixe
  versão, nem que sinalize atualização.
- O CORE tem **dois envelopes próprios** (`core_dna/event_envelope.proto`,
  `liceu-6-0/core_dna/events.proto`) que **não descrevem o que o boundary aceita**, e
  um deles traz `decision_id` como campo genérico — contradizendo o
  `forbidden_envelope_fields` da Constituição.
- **Sete definições de envelope vivas** em cinco repositórios; só a do kit tem
  `contract_id`/`contract_version`; só a do kit tem `MANIFEST` verificado.
- **Sete caminhos de publicação** no boundary do CORE; **um** pelo SDK do kit
  (ARCHIMEDES), seis com cliente HTTP próprio — dois deles chamados
  `CanonicalFederationClient` sem ser o SDK.

## Alternativas

| | Opção | Por que não |
|---|---|---|
| A | Registry no CORE | O CORE é **consumidor** do registry, não dono. É o repositório com o pior histórico de consistência de envelope do ecossistema. Colocar a fonte lá é mover a lei para onde ela é menos respeitada. |
| B | Manter vendorizado | Íntegro em dois consumidores não prova nada sobre quinze. Vendor não fixa versão nem sinaliza atualização. Cada consumidor novo é uma cópia a mais para reconciliar — o CORE seria a terceira. |
| **C** | **Repositório próprio + pacote** | Uma fonte, `MANIFEST` na CI da própria fonte, versão fixável pelo consumidor, atualização visível como bump de dependência. |

## O argumento decisivo: as três Mães

O consumidor externo torna o **pacote** necessário. As três Mães (Ativa, Sucessora,
Testemunha — Constituição, `promocao`) tornam a **versão fixa** necessária: se a
Ativa valida contra uma versão da Constituição e a Sucessora contra outra, a
promoção acontece **sob leis diferentes** — e o `authority_epoch` não protege contra
isso, porque ele versiona a autoridade, não a lei sob a qual a autoridade foi
exercida. Só um pacote com versão fixada pelas três garante que a promoção de Mãe
é validada pela mesma Constituição em cada lado.

Esta razão não se recupera depois de seis meses. Por isso está escrita.

## Consequências

- **Contratos ausentes têm onde nascer**: `liceu.legal.admissibility` (Gate C) e o
  planning request do W93F22 (elo 1) — CORE #32.
- **O boundary do CORE consome em vez de copiar**: a terceira cópia não chega a
  existir. O boundary alinhado ao kit nasce em modo ALERTA e passa a BLOQUEANTE por
  produtor conforme cada um migra ao SDK — CORE #34.
- **Convergência dos sete envelopes** tem destino declarado: o do kit.
- **Gates B e C** deixam de esperar por "onde".

## O que fica em aberto

**Onde publicar.** GitHub Packages usa a autenticação que já existe; um PyPI privado
é mais neutro se o consumidor externo não tiver conta GitHub. Depende de quem é
esse consumidor — e **não bloqueia o repositório nascer**. Até a decisão, o pacote é
instalável direto do repositório (`pip install git+…@v0.9.0`), com a versão fixada
pela tag.

## Regras deste repositório

1. **O `MANIFEST` é a identidade do kit.** Toda mudança nos nove arquivos exige
   novo `MANIFEST` e bump de versão em `pyproject.toml`. A CI recusa `MANIFEST`
   divergente.
2. **Os bytes não são normalizados** (`.gitattributes: -text`). Um consumidor que
   instale o pacote obtém os mesmos bytes que a CI verificou.
3. **A suíte do kit roda na fonte**: registry check (0 erros), conformance
   self-test (59/59), SDK self-test (25/25). O que os consumidores verificavam por
   cópia passa a ser verificado uma vez, aqui.
4. **Push direto em `main` não passa em silêncio** (`main-guard.yml`, mesmo check
   pós-fato do ARCHIMEDES) enquanto a proteção de branch não existir.
5. **Migração incremental**: ARCHIMEDES e FORNECEDORES trocam o vendor pelo pacote
   primeiro (já usam o `MANIFEST`); o CORE em seguida (boundary em ALERTA); os
   demais conforme migram ao SDK (CORE #34).
