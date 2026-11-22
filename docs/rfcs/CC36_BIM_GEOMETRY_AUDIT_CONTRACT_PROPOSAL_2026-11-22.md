# CC-36.8 — RFC de contrato canônico para auditoria geométrica BIM

**Estado:** PROPOSTA PARA REVISÃO — NÃO REGISTRADO, NÃO HOMOLOGADO, NÃO ATIVO.

**Origem:** CC-34/CC-36, PR de testes no repositório LICEU_6.0_CONSTRUTORA_VIRTUAL #153. A implementação hoje usa dados sintéticos; os dados de cliente são restritos ao Drive.

## Identidade proposta

| Propriedade | Proposta (não oficial) |
|---|---|
| contract_id | `liceu.bim.geometry-audit` |
| contract_version | `1.0.0` |
| event_type | `bim.geometry.audit.published` |
| owner / allowed_producers | `liceu.bim` |
| classification | `DOMAIN_EVENT` |
| authority | Nenhuma; não comprova dimensionamento nem aprova construção |
| estado inicial | `DECLARED_BUT_NOT_IMPLEMENTED` somente após aprovação dos registries |
| envelope / scope | `scope: tenant` com vínculo do tenant exigido no CORE |
| transport | HTTP boundary do CORE; downstream somente após ACL comprovada |

A nomenclatura acima **não** está no Contract Registry nem no Event Registry do protocolo consultado. A proposta não cria automaticamente contrato em execução. Não use `bim.geometry.audit` como contrato registrado: foi uma string sintética dos testes exploratórios.

## Esquema pretendido do payload — proposta JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["tenant_id","case_ref","schema_version","model_version","source_sha256","generator_version","evidence_sha256","scope","findings","approved_for_construction"],
  "properties": {
    "tenant_id": {"type":"string","pattern":"^[A-Za-z0-9][A-Za-z0-9_.:-]{1,119}$"},
    "case_ref": {"type":"string","pattern":"^[A-Z0-9][A-Z0-9_-]{2,63}$"},
    "schema_version": {"const":"cc36-evidence-v1"},
    "model_version": {"type":"string","minLength":1,"maxLength":80},
    "source_sha256": {"type":"string","pattern":"^[a-f0-9]{64}$"},
    "generator_version": {"type":"string","minLength":1,"maxLength":80},
    "evidence_sha256": {"type":"string","pattern":"^[a-f0-9]{64}$"},
    "scope": {"const":"GEOMETRY_ONLY_NOT_STRUCTURAL_DESIGN"},
    "findings": {
      "type":"array","maxItems":100000,
      "items": {
        "type":"object","additionalProperties":false,
        "required":["element_ref","status","structural_connection_verified"],
        "properties": {
          "element_ref":{"type":"string","minLength":1,"maxLength":80},
          "status":{"enum":["GEOMETRIC_3D_COINCIDENCE","PLAN_ONLY_DIFFERENT_ELEVATION","UNKNOWN_VERTICAL_EXTENT"]},
          "structural_connection_verified":{"const":false}
        }
      }
    },
    "approved_for_construction": {"const":false}
  }
}
```

O `evidence_sha256` deve ser calculado de forma determinística sobre a evidência canônica, não sobre qualquer serialização arbitrária. O `source_sha256` atesta identidade dos bytes de origem, **não** fidelidade de engenharia ao DWG nem aprovação técnica.

## Invariantes de domínio

1. Um evento de auditoria é consultivo e geométrico. Coincidência de eixos não demonstra transmissão de esforço nem apoio resistente.
2. Nenhum campo pode elevar aprovação técnica por inferência. `approved_for_construction=false` e `structural_connection_verified=false`.
3. A origem deve ser versionada e auditável; arquivos brutos de clientes não devem ser colocados em repositórios públicos.
4. O `tenant_id` do payload precisa coincidir com vínculo servidor de identidade federativa. Atributo fornecido pelo cliente não é prova de autorização.
5. Toda leitura por ID, listagem, referência causal, referência de evidência e consumo downstream precisa fazer autorização sobre o objeto. Referência não autorizada deve se comportar como não resolvida.
6. Reenvio do mesmo evento com mesma identidade e conteúdo é idempotente; identidade reutilizada com conteúdo divergente precisa ser rejeitada e auditada.
7. Não transportar nome, endereço, CPF/CNPJ, geometria proprietária ou dados de outros clientes nos eventos sintéticos de CI.

## Lacunas a resolver antes de promover a contrato

- Decidir nomenclatura, SemVer, classificação, escala e contrato canônico com responsáveis por BIM/CORE, em conformidade com a Constituição e ADR-001/002/004.
- Incluir entrada em `liceu_contract_registry.yaml` e `liceu_event_registry.yaml`, atualizar metadados, dependências, event type e checksums/manifests, preservando coerência do pacote.
- Checar os invariantes reais e a compatibilidade com o SDK, schema, allowed_producers, contract registry checker e conformance checker, no próprio repositório `liceu-protocol`.
- Não declarar `ACTIVE` / implementado sem contrato, conformance e produtor reais. Usar estado inicial de declaração e promoção explícita.
- Atualizar o adaptador candidato de CC-36 para IDs **oficiais** somente após promoção e instalação do protocolo no CORE. Não usar sinalizador local de `registry_record` como confirmação autenticada.
- Testar controle de leitura e escrita por tenant no PostgreSQL efêmero, inclusive replays, referências, acesso por outros produtores, versões antigas e restart de serviço.
- Auditar consumidores secundários (analytics, NATS, event bus, logs, backups, busca), retenção, exclusão e gestão de credenciais.
- Reconciliar sete provas PRF divergentes do Genoma; não reescrever hashes para silenciar o detector.
- Exigir o gate CC36 na política de branch, revisão humana e ART quando aplicável. Sem homologação ou gravação em produção antes de aprovação.

## Evidência disponível

Na PR #153 de LICEU_6.0_CONSTRUTORA_VIRTUAL, o workflow PostgreSQL 16 efêmero executou 4 testes de persistência federativa e 11 testes de autorização de cliente com sucesso no commit 718a05b. O teste comprova somente os cenários do laboratório, não o contrato descrito nesta RFC. O workflow CI geral #315 falhou, portanto não há liberação para merge.

**Decisão desta RFC:** documentar e submeter para revisão, sem tocar nos registries soberanos ainda.
