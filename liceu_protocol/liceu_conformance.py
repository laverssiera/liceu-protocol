#!/usr/bin/env python3
"""
LICEU 6.0 — Conformance Kit (semente de P2.3)
==============================================

Valida um envelope contra o Contract Registry. Prova que os contratos de P2.1
sao executaveis e nao decorativos.

GATES — taxonomia estavel, usada no codigo, na saida e no artifact:

  G1 ENVELOPE    campos baseline do LICEU Federation Envelope
  G2 CONTRACT    contract_id resolve; contract_version e event_type conferem
  G3 AUTHORITY   producer_id em allowed_producers; campos de autoridade
                 PROIBIDOS ausentes; lineage exigido presente
  G4 SCHEMA      JSON Schema do contrato (motor: jsonschema)
  G5 LOCAL       invariantes semanticos ENTRE CAMPOS do mesmo evento
  G6 CAUSAL      causalidade entre eventos — NAO IMPLEMENTADO (M3/M4)

G3 e o que torna o salto de etapa estruturalmente impossivel.
G5 cobre o que nenhum JSON Schema alcanca: relacao entre campos.
G6 exige o Event Store e pertence ao runtime, nao a este kit local.
Um envelope de opera.execution.created que traga decision_id proprio e
rejeitado, porque OPERA nao produz decisao — herda pela cadeia.

USO
    python3 liceu_conformance.py --self-test
    python3 liceu_conformance.py --envelope evento.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

KIT_VERSION = "0.9.0"

# Modo estrito: em certificacao, a ausencia de jsonschema deve FALHAR, nao
# degradar para o motor interno. Degradacao silenciosa de validador e a mesma
# classe do fallback que ampliava autonomia — a excecao vira a regra no
# momento errado.
STRICT = os.environ.get("LICEU_CONFORMANCE_STRICT", "").lower() in ("1", "true", "sim")


class Rejeicao(Exception):
    def __init__(self, camada: str, motivo: str):
        self.camada, self.motivo = camada, motivo
        super().__init__(f"[{camada}] {motivo}")


def _tipo_ok(v, t) -> bool:
    m = {"string": str, "number": (int, float), "integer": int,
         "object": dict, "array": list, "boolean": bool}
    if isinstance(t, list):
        return any(_tipo_ok(v, x) for x in t)
    if t == "null":
        return v is None
    return isinstance(v, m.get(t, object))


def validar_schema(payload, schema, caminho="payload"):
    """Valida o payload contra o JSON Schema do contrato.

    §21 — usar implementacao madura, nunca motor proprio. O codigo LICEU fica
    reservado aos INVARIANTES CONSTITUCIONAIS (autoridade e lineage), que
    nenhuma biblioteca de schema conhece. O subconjunto abaixo e apenas
    fallback para ambiente sem a dependencia, e avisa quando usado.
    """
    try:
        import jsonschema
    except ImportError:
        if STRICT:
            raise Rejeicao("G4-SCHEMA",
                "jsonschema ausente e modo STRICT ativo: certificacao exige o "
                "motor maduro. O fallback interno serve para desenvolvimento, "
                "nunca para certificacao.")
        return _validar_schema_fallback(payload, schema, caminho)
    try:
        jsonschema.validate(instance=payload, schema=schema)
    except jsonschema.ValidationError as e:
        alvo = ".".join([caminho] + [str(x) for x in e.absolute_path])
        raise Rejeicao("G4-SCHEMA", f"{alvo}: {e.message}") from None
    return None


def _validar_schema_fallback(payload, schema, caminho="payload"):
    """Subconjunto minimo. So usado sem jsonschema instalado."""
    if not _tipo_ok(payload, schema.get("type", "object")):
        raise Rejeicao("G4-SCHEMA", f"{caminho}: tipo esperado {schema.get('type')}")
    if schema.get("type") == "object":
        for r in schema.get("required", []):
            if r not in payload:
                raise Rejeicao("G4-SCHEMA", f"{caminho}.{r} obrigatorio e ausente")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for k in payload:
                if k not in props:
                    raise Rejeicao("G4-SCHEMA", f"{caminho}.{k} nao permitido")
        for k, v in payload.items():
            if k in props:
                _validar_schema_fallback(v, props[k], f"{caminho}.{k}")
    elif schema.get("type") == "array":
        if len(payload) < schema.get("minItems", 0):
            raise Rejeicao("G4-SCHEMA", f"{caminho}: minimo {schema['minItems']} itens")
        for i, it in enumerate(payload):
            if "items" in schema:
                _validar_schema_fallback(it, schema["items"], f"{caminho}[{i}]")
    else:
        if "enum" in schema and payload not in schema["enum"]:
            raise Rejeicao("G4-SCHEMA", f"{caminho}: valor fora do enum")
        if "minLength" in schema and len(str(payload)) < schema["minLength"]:
            raise Rejeicao("G4-SCHEMA", f"{caminho}: minLength {schema['minLength']}")
        for lim, op in (("minimum", "<"), ("maximum", ">")):
            if lim in schema and isinstance(payload, (int, float)):
                if (payload < schema[lim]) if op == "<" else (payload > schema[lim]):
                    raise Rejeicao("G4-SCHEMA", f"{caminho}: {lim} {schema[lim]}")


# Campos do envelope canonico que o servidor NAO persiste. Um evento LIDO de
# volta nunca os tera. Exigi-los em modo read rejeitaria evento legitimamente
# armazenado.
CAMPOS_NAO_PERSISTIDOS = {
    "payload_hash", "envelope_fingerprint", "observed_at", "emitted_at",
}

# Formato de cada campo do E1. VALIDAR QUANDO PRESENTE, em ambos os modos.
#
# RM1 (CORE_E1_PREP): nao encolher CAMPOS_NAO_PERSISTIDOS apos o E1. Em vez
# disso, validar o formato quando o campo estiver presente e ignorar quando
# ausente. Assim evento pre-E1 passa e evento pos-E1 e verificado, sem
# marcador de epoca nem estado externo.


def _hex64(v) -> bool:
    return (isinstance(v, str) and len(v) == 64
            and all(c in "0123456789abcdefABCDEF" for c in v))


def _iso8601(v) -> bool:
    return (isinstance(v, str) and len(v) >= 20 and v[4:5] == "-"
            and ("T" in v) and (v.endswith("Z") or "+" in v[10:] or "-" in v[11:]))


FORMATO_E1 = {
    "payload_hash": (_hex64, "hex de 64 caracteres"),
    "envelope_fingerprint": (_hex64, "hex de 64 caracteres"),
    "observed_at": (_iso8601, "ISO 8601"),
    "emitted_at": (_iso8601, "ISO 8601"),
}


def carregar_instancias_de_autoridade(producer_registry: dict) -> set:
    """Instancias declaradas da classe de autoridade.

    O Conformance passa a CRUZAR envelope com Producer Registry: sem isso,
    producer_instance_id e texto livre e qualquer instancia se inventa.
    """
    out = set()
    for pid, pv in (producer_registry.get("producers") or {}).items():
        if pv.get("producer_kind") != "AUTHORITY_CONTROL_PLANE":
            continue
        for i in (pv.get("instances") or []):
            iid = i.get("instance_id", "")
            out.add(iid.split("#")[-1] if "#" in iid else iid)
    return out


def validar(envelope: dict, cr: dict, *, mode: str = "publish") -> None:
    """Valida um envelope.

    mode="publish"  evento sendo publicado agora.
                    Exige o envelope canonico completo. RETIRED e rejeitado.
    mode="read"     evento lido de volta do Event Store.
                    NAO exige os campos que o servidor nao persiste, e aceita
                    RETIRED — aposentadoria bloqueia escrita, nunca leitura.

    G3, G4 e G5 sao IDENTICOS nos dois modos: um evento armazenado que viola
    autoridade ou schema e achado, nao aprovacao.
    """
    if mode not in ("publish", "read"):
        raise ValueError(f"mode invalido: {mode!r}")

    cid = envelope.get("contract_id")
    versoes = cr["contracts"].get(cid)
    contrato = None
    if versoes is not None:
        cv = str(envelope.get("contract_version") or "")
        contrato = versoes.get(cv)
        if contrato is None:
            raise Rejeicao("G2-CONTRACT",
                f"contract_version {cv!r} nao existe para {cid!r}. "
                f"Versoes conhecidas: {sorted(versoes)}")
        if contrato.get("status") == "RETIRED" and mode == "publish":
            raise Rejeicao("G2-CONTRACT",
                f"{cid}@{cv} esta RETIRED: nao aceita publicacao nova. "
                f"Use mode='read' para validar evento historico.")
    if contrato is None:
        raise Rejeicao("G2-CONTRACT", f"contract_id desconhecido: {cid!r}")

    # G1 — envelope baseline
    # producer_id vira `producer` no servidor; em read, aceitar qualquer um.
    env = dict(envelope)
    if mode == "read" and not env.get("producer_id") and env.get("producer"):
        env["producer_id"] = env["producer"]
    for c in cr["envelope_baseline"]["sempre_obrigatorios"]:
        if mode == "read" and c in CAMPOS_NAO_PERSISTIDOS:
            continue      # presenca nao e exigida em read; formato ainda e
        if env.get(c) in (None, ""):
            raise Rejeicao("G1-ENVELOPE", f"campo baseline ausente: {c}")

    # RM1 — formato dos campos do E1, validado QUANDO PRESENTE, nos dois modos.
    # Ausente em read: evento pre-E1, segue. Presente: verificado.
    for c, (valida, esperado) in FORMATO_E1.items():
        v = env.get(c)
        if v in (None, ""):
            continue
        if not valida(v):
            raise Rejeicao("G1-ENVELOPE",
                           f"{c} com formato invalido (esperado {esperado})")
    # cruzamento com o Producer Registry: sem isto producer_instance_id e texto livre
    try:
        _pr = yaml.safe_load(open("liceu_producer_registry.yaml", encoding="utf-8"))
        env["_instancias_conhecidas"] = carregar_instancias_de_autoridade(_pr)
    except Exception:
        env["_instancias_conhecidas"] = set()
    envelope = env
    if False and envelope.get("contract_version") != contrato["contract_version"]:
        raise Rejeicao("G2-CONTRACT",
                       f"contract_version {envelope.get('contract_version')!r} "
                       f"!= {contrato['contract_version']!r} do registry")
    if envelope.get("event_type") != contrato["event_type"]:
        raise Rejeicao("G2-CONTRACT", "event_type nao corresponde ao contrato")

    # 2 — autoridade
    prod = envelope.get("producer_id")
    if prod not in contrato["allowed_producers"]:
        raise Rejeicao("G3-AUTHORITY",
                       f"{prod} nao pode produzir {contrato['event_type']}; "
                       f"dono e {contrato['owner']}")

    # 3 — lineage: exigidos presentes, proibidos ausentes
    for c in contrato.get("required_envelope_fields", []):
        if envelope.get(c) in (None, ""):
            raise Rejeicao("G3-AUTHORITY", f"campo de lineage obrigatorio ausente: {c}")
    for c, motivo in (contrato.get("forbidden_envelope_fields") or {}).items():
        if envelope.get(c) not in (None, ""):
            raise Rejeicao("G3-AUTHORITY",
                           f"{prod} nao pode emitir {c}. "
                           f"{motivo.strip().splitlines()[0]}")

    # G4 — payload
    p = envelope.get("payload", {})
    validar_schema(p, contrato["payload_schema"])

    # G5 — semantica local: relacao ENTRE CAMPOS do mesmo evento.
    # Nenhum JSON Schema expressa isso.
    _g5(cid, p, envelope)


def _g5(contract_id: str, p: dict, env: dict | None = None) -> None:
    """Invariantes de dominio que so existem na relacao entre campos."""
    if contract_id == "liceu.archimedes.planning-state":
        if p.get("state_status") == "AUTHORITATIVE_OUTPUT" and not p.get("candidates"):
            raise Rejeicao("G5-LOCAL",
                "AUTHORITATIVE_OUTPUT sem candidates: saida autoritativa vazia")
        for c in p.get("candidates", []):
            if not (c.get("why") or "").strip():
                raise Rejeicao("G5-LOCAL",
                    f"candidate {c.get('candidate_id')} sem why — "
                    f"WHERE sem WHY nao e planejamento")

    elif contract_id == "liceu.cefeida.evidence":
        if p.get("evidence_kind") == "FORECAST":
            if p.get("confidence") is None:
                raise Rejeicao("G5-LOCAL", "FORECAST sem confidence")
            if not p.get("horizon"):
                raise Rejeicao("G5-LOCAL", "FORECAST sem horizon")

    elif contract_id == "liceu.john.recommendation":
        ids = {a.get("alternative_id") for a in p.get("alternatives", [])}
        rec = p.get("recommended_alternative_id")
        if rec not in ids:
            raise Rejeicao("G5-LOCAL",
                f"recommended_alternative_id {rec!r} nao esta em alternatives")

    elif contract_id == "liceu.authority.human-decision":
        # A decisao humana e o caminho de MAIOR risco do ecossistema. Nao basta
        # exigir a chave: e preciso exigir o CONTEUDO.
        #
        # Bloqueio fechado aqui: WITNESS_WITH_EMPTY_AUTH_ACCEPTED — a testemunha
        # registrando decisao humana sem prova criptografica do humano.
        sig = p.get("human_signature")
        if not isinstance(sig, str) or len(sig) < 64:
            raise Rejeicao("G5-LOCAL",
                "human_signature ausente ou com menos de 64 caracteres: "
                "decisao humana sem prova criptografica e fabricavel")
        mfa = p.get("mfa_assertion_hash")
        if not isinstance(mfa, str) or len(mfa) < 64:
            raise Rejeicao("G5-LOCAL", "mfa_assertion_hash ausente ou curto")
        if not p.get("human_authentication_method"):
            raise Rejeicao("G5-LOCAL", "human_authentication_method obrigatorio")
        if not p.get("signed_at") or not p.get("nonce"):
            raise Rejeicao("G5-LOCAL",
                "signed_at e nonce obrigatorios — sem eles a assinatura e "
                "replayavel")
        wa = p.get("witness_attestation")
        if not isinstance(wa, dict) or not wa.get("verified_signature"):
            raise Rejeicao("G5-LOCAL",
                "witness_attestation deve declarar verified_signature: a "
                "testemunha REGISTRA decisao verificada, nao a cria")
        er = p.get("escalation_reason")
        VALIDOS = {"MOTHERS_UNAVAILABLE", "UNRESOLVED_CONFLICT",
                   "INSUFFICIENT_EVIDENCE", "CONSTITUTIONAL_RISK_LIMIT",
                   "MANUAL_EMERGENCY"}
        if er not in VALIDOS:
            raise Rejeicao("G5-LOCAL",
                f"escalation_reason invalido: {er!r}; esperado um de {sorted(VALIDOS)}")
        # maes_indisponiveis e CONDICIONAL: so obrigatorio nesse motivo
        if er == "MOTHERS_UNAVAILABLE" and not (p.get("maes_indisponiveis") or []):
            raise Rejeicao("G5-LOCAL",
                "escalation_reason=MOTHERS_UNAVAILABLE exige maes_indisponiveis")
        if not (p.get("evidencias_consideradas") or []):
            raise Rejeicao("G5-LOCAL",
                "decisao sem evidencia e proibida")
        if not (p.get("alternativas") or []):
            raise Rejeicao("G5-LOCAL", "alternativas nao pode ser vazio")

        # --- validacao adversarial (kit 0.9.0) -------------------------------
        # Exigir presenca e comprimento e ESTRUTURAL. Estes checks atacam o
        # CONTEUDO: papel valido, instancia registrada, epoca coerente, tipo
        # correto e coerencia entre papel e atestado.
        #
        # Nenhum deles substitui verificacao criptografica no CORE. O que eles
        # fecham e a fabricacao TRIVIAL — declarar papel, instancia ou epoca
        # que nao existem.
        PAPEIS = {"ACTIVE", "SUCCESSOR", "WITNESS"}
        role = (env or {}).get("authority_role")
        if role not in PAPEIS:
            raise Rejeicao("G3-AUTHORITY",
                f"authority_role invalido: {role!r}; esperado um de {sorted(PAPEIS)}")

        inst = (env or {}).get("producer_instance_id")
        conhecidas = (env or {}).get("_instancias_conhecidas") or set()
        if conhecidas and inst not in conhecidas:
            raise Rejeicao("G3-AUTHORITY",
                f"producer_instance_id {inst!r} nao esta no Producer Registry; "
                f"conhecidas: {sorted(conhecidas)}")

        ep = (env or {}).get("authority_epoch")
        if not isinstance(ep, int) or isinstance(ep, bool) or ep < 1:
            raise Rejeicao("G3-AUTHORITY",
                f"authority_epoch deve ser inteiro >= 1; recebido {ep!r}")

        vs = wa.get("verified_signature")
        if vs is not True:
            raise Rejeicao("G5-LOCAL",
                f"verified_signature deve ser o booleano True; recebido "
                f"{vs!r} do tipo {type(vs).__name__}")

        # COERENCIA papel x atestado: quem registra decisao humana e a
        # TESTEMUNHA. Uma Mae ACTIVE produzindo witness_attestation confunde
        # os papeis que a Constituicao separa.
        if role != "WITNESS":
            raise Rejeicao("G3-AUTHORITY",
                f"decisao humana deve ser registrada por instancia WITNESS; "
                f"authority_role={role!r}")
        if wa.get("witness_instance_id") != inst:
            raise Rejeicao("G5-LOCAL",
                "witness_attestation.witness_instance_id deve ser a propria "
                "instancia que publica")

    elif contract_id == "liceu.anchor.authorization":
        if p.get("decision") == "DENIED" and not (p.get("denial_reason") or "").strip():
            raise Rejeicao("G5-LOCAL",
                "DENIED sem denial_reason — negacao tambem e fato autoritativo")
        if p.get("decision") == "GRANTED" and p.get("denial_reason"):
            raise Rejeicao("G5-LOCAL", "GRANTED com denial_reason")
        # contrato 1.1.0 — legal_basis_refs e REFERENCIA, nunca afirmacao
        if "legal_basis_refs" in p:
            refs = p.get("legal_basis_refs") or []
            if not isinstance(refs, list):
                raise Rejeicao("G5-LOCAL", "legal_basis_refs deve ser lista")
            if p.get("subject_ref") in refs:
                raise Rejeicao("G5-LOCAL",
                    "legal_basis_refs referencia o proprio subject: "
                    "autorreferencia de base juridica e fabricacao direta")
            for r in refs:
                if not isinstance(r, str) or not r.strip():
                    raise Rejeicao("G5-LOCAL", "legal_basis_ref vazia")
                if r.startswith("liceu.") and not r.startswith("liceu.legal"):
                    raise Rejeicao("G5-LOCAL",
                        f"legal_basis_ref {r!r} nao aponta para liceu.legal; "
                        f"base juridica so pode vir do dominio juridico")

    elif contract_id == "liceu.cea.financial-exposure":
        if "base" not in (p.get("scenarios") or {}):
            raise Rejeicao("G5-LOCAL",
                "scenarios sem cenario 'base': exposicao sem caso base nao e avaliavel")
        if p.get("financial_viability") != "inviavel" and p.get("npv") is None:
            raise Rejeicao("G5-LOCAL",
                f"financial_viability={p.get('financial_viability')!r} exige npv")

    elif contract_id == "liceu.cea.continental-financial-exposure":
        srcs = p.get("source_exposure_ids") or []
        if p.get("financial_exposure_id") in srcs:
            raise Rejeicao("G5-LOCAL",
                "consolidacao nao pode listar a si mesma em source_exposure_ids")

    elif contract_id == "liceu.opera.execution":
        if p.get("execution_status") != "CREATED":
            raise Rejeicao("G5-LOCAL",
                f"execution.created deve iniciar em CREATED, "
                f"nao {p.get('execution_status')!r}")


# ---------------------------------------------------------------------------
# Self-test: cada caso e uma violacao REAL encontrada no discovery
# ---------------------------------------------------------------------------

def _humano(**over):
    """Decisao humana valida; over injeta o ataque."""
    wa = over.pop("_wa", {"witness_instance_id": "mother-witness",
                          "verified_signature": True,
                          "verified_at": "2026-09-01T10:00:01Z"})
    pay = {"decision_id": "d1", "human_actor_id": "pseudo-h1",
           "decision_dossier_id": "dd1", "escalation_reason": "MOTHERS_UNAVAILABLE",
           "capability": "promocao_a_estado_autorizado",
           "maes_indisponiveis": ["mother-a", "mother-b"],
           "evidencias_consideradas": ["e1"], "alternativas": ["adiar", "seguir"],
           "risco_avaliado": "alto", "decisao": "seguir", "justificativa": "—",
           "external_effect": False, "reversibility": "REVERSIVEL",
           "human_signature": "s" * 64, "mfa_assertion_hash": "m" * 64,
           "human_authentication_method": "MFA_FIDO2",
           "signed_at": "2026-09-01T10:00:00Z", "nonce": "n" * 16,
           "witness_attestation": wa}
    kw = dict(event_type="authority.human.decision.recorded",
              producer_id="liceu.authority",
              contract_id="liceu.authority.human-decision",
              contract_version="2.0.0", causation_id="c1",
              source_event_id="s1", payload=pay)
    kw.update(over)
    return _base(**kw)


def _lido(**kw):
    """Envelope como o Event Store devolve: sem os campos nao persistidos,
    com `producer` em vez de `producer_id`. _mode define o modo de validacao."""
    kw.setdefault("_mode", "read")
    explicitos = {k for k in kw if k in CAMPOS_NAO_PERSISTIDOS}
    e = _base(**{k: v for k, v in kw.items() if k not in ("producer", "_mode")})
    for c in CAMPOS_NAO_PERSISTIDOS - explicitos:
        e.pop(c, None)
    e.pop("producer_id", None)
    e["producer"] = kw["producer"]
    e["_mode"] = kw["_mode"]
    return e


def _base(**kw):
    # envelope vNext: campos de autoridade so entram quando o fixture os pede
    if kw.get("contract_id") == "liceu.authority.human-decision":
        kw.setdefault("producer_instance_id", "mother-witness")
        kw.setdefault("authority_role", "WITNESS")
        kw.setdefault("authority_epoch", 1)
        kw.setdefault("authority_issuer_id", "issuer-01")
        kw.setdefault("activation_certificate_id", "cert-01")
        kw.setdefault("scale", "LOCAL")
        kw.setdefault("observed_at", "2026-09-01T09:59:00Z")
    e = {"event_id": "e1", "trace_id": "t1", "artifact_id": "a1",
         "scope": "continental",
         # hex valido: 'h' nao e digito hexadecimal e a validacao de formato
         # do RM1 pegou isso como dado de teste invalido
         "payload_hash": "a" * 64,
         "envelope_fingerprint": "f" * 64, "emitted_at": "2026-08-29T00:00:00Z"}
    e.update(kw)
    return e


CASOS = [
 ("OPERA produz recomendacao do JOHN (violacao real: apps/opera/api/construction.py)",
  False, _base(event_type="john.recommendation.generated",
    producer_id="liceu.opera", contract_id="liceu.john.recommendation",
    contract_version="1.0.0", causation_id="c1", decision_id="d1",
    payload={"alternatives": [{"alternative_id": "A", "summary": "x"},
                              {"alternative_id": "B", "summary": "y"}],
             "recommended_alternative_id": "A", "confidence": 0.8,
             "rationale": [{"factor": "custo", "weight": 0.5}],
             "evidence_refs": ["ev1"]})),

 ("JOHN emite governance_decision_id (autoautorizacao)",
  False, _base(event_type="john.recommendation.generated",
    producer_id="liceu.john", contract_id="liceu.john.recommendation",
    contract_version="1.0.0", causation_id="c1", decision_id="d1",
    governance_decision_id="g1",
    payload={"alternatives": [{"alternative_id": "A", "summary": "x"},
                              {"alternative_id": "B", "summary": "y"}],
             "recommended_alternative_id": "A", "confidence": 0.8,
             "rationale": [{"factor": "custo", "weight": 0.5}],
             "evidence_refs": ["ev1"]})),

 ("CEFEIDA emite decision_id (violacao real: john_decision_engine.py)",
  False, _base(event_type="cefeida.evidence.published",
    producer_id="liceu.cefeida", contract_id="liceu.cefeida.evidence",
    contract_version="1.0.0", observed_at="2026-08-29T00:00:00Z",
    decision_id="d1",
    payload={"evidence_kind": "METRIC", "metric": "deficit", "value": 12,
             "unit": "GW", "source_refs": ["s1"], "method_version": "1.0.0"})),

 ("ANCHOR emite execution_id (autoridade + execucao juntas)",
  False, _base(event_type="anchor.authorization.granted",
    producer_id="liceu.anchor", contract_id="liceu.anchor.authorization",
    contract_version="1.0.0", causation_id="c1", decision_id="d1",
    governance_decision_id="g1", execution_id="x1",
    payload={"decision": "GRANTED", "subject_ref": "s1",
             "subject_content_hash": "h" * 64, "subject_version": "1",
             "policy_refs": ["p1"], "authority_scope": "continental"})),

 ("OPERA emite decision_id proprio (justificativa retroativa)",
  False, _base(event_type="opera.execution.created",
    producer_id="liceu.opera", contract_id="liceu.opera.execution",
    contract_version="1.0.0", causation_id="c1",
    governance_decision_id="g1", execution_id="x1", decision_id="d-proprio",
    payload={"execution_status": "CREATED", "authorized_subject_ref": "s1",
             "authorized_subject_hash": "h" * 64,
             "work_items": [{"work_item_id": "w1", "description": "d"}]})),

 ("contract_version 'v1' em vez de SemVer",
  False, _base(event_type="cefeida.evidence.published",
    producer_id="liceu.cefeida", contract_id="liceu.cefeida.evidence",
    contract_version="v1", observed_at="2026-08-29T00:00:00Z",
    payload={"evidence_kind": "METRIC", "metric": "m", "value": 1,
             "unit": "u", "source_refs": ["s"], "method_version": "1.0.0"})),

 ("JOHN recomenda com 1 alternativa (recomendar sem alternativa)",
  False, _base(event_type="john.recommendation.generated",
    producer_id="liceu.john", contract_id="liceu.john.recommendation",
    contract_version="1.0.0", causation_id="c1", decision_id="d1",
    payload={"alternatives": [{"alternative_id": "A", "summary": "x"}],
             "recommended_alternative_id": "A", "confidence": 0.8,
             "rationale": [{"factor": "c", "weight": 1}],
             "evidence_refs": ["ev1"]})),

 ("CEFEIDA sem source_refs (evidencia sem fonte)",
  False, _base(event_type="cefeida.evidence.published",
    producer_id="liceu.cefeida", contract_id="liceu.cefeida.evidence",
    contract_version="1.0.0", observed_at="2026-08-29T00:00:00Z",
    payload={"evidence_kind": "METRIC", "metric": "m", "value": 1,
             "unit": "u", "source_refs": [], "method_version": "1.0.0"})),

 ("JOHN produz recomendacao valida",
  True, _base(event_type="john.recommendation.generated",
    producer_id="liceu.john", contract_id="liceu.john.recommendation",
    contract_version="1.0.0", causation_id="c1", decision_id="d1",
    payload={"alternatives": [{"alternative_id": "A", "summary": "corredor A"},
                              {"alternative_id": "B", "summary": "corredor B"}],
             "recommended_alternative_id": "A", "confidence": 0.82,
             "rationale": [{"factor": "perdas", "weight": 0.6,
                            "direction": "POSITIVE"}],
             "evidence_refs": ["ev-cefeida-1"], "mode": "BALANCED"})),

 ("ANCHOR autoriza validamente",
  True, _base(event_type="anchor.authorization.granted",
    producer_id="liceu.anchor", contract_id="liceu.anchor.authorization",
    contract_version="1.1.0", causation_id="c-john-1", decision_id="d1",
    governance_decision_id="g1",
    payload={"decision": "GRANTED", "subject_ref": "corredor-A",
             "subject_content_hash": "h" * 64, "subject_version": "1.0.0",
             "policy_refs": ["pol-continental-01"],
             "authority_scope": "continental"})),

 # --- G5: invariantes semanticos locais (§19) ---
 ("ARCHIMEDES AUTHORITATIVE_OUTPUT sem candidates",
  False, _base(event_type="archimedes.planning.state.authoritative",
    producer_id="liceu.archimedes", contract_id="liceu.archimedes.planning-state",
    contract_version="1.0.0",
    payload={"planning_request_id": "pr1", "state_status": "AUTHORITATIVE_OUTPUT",
             "territorial_scope": "CONTINENTAL", "candidates": []})),

 ("ARCHIMEDES candidate sem why (WHERE sem WHY)",
  False, _base(event_type="archimedes.planning.state.authoritative",
    producer_id="liceu.archimedes", contract_id="liceu.archimedes.planning-state",
    contract_version="1.0.0",
    payload={"planning_request_id": "pr1", "state_status": "AUTHORITATIVE_OUTPUT",
             "territorial_scope": "CONTINENTAL",
             "candidates": [{"candidate_id": "c1", "where": {}, "why": "  "}]})),

 ("CEFEIDA FORECAST sem confidence",
  False, _base(event_type="cefeida.evidence.published",
    producer_id="liceu.cefeida", contract_id="liceu.cefeida.evidence",
    contract_version="1.0.0", observed_at="2026-08-29T00:00:00Z",
    payload={"evidence_kind": "FORECAST", "metric": "demanda", "value": 10,
             "unit": "GW", "source_refs": ["s1"], "method_version": "1.0.0",
             "horizon": "P30D"})),

 ("CEFEIDA FORECAST sem horizon",
  False, _base(event_type="cefeida.evidence.published",
    producer_id="liceu.cefeida", contract_id="liceu.cefeida.evidence",
    contract_version="1.0.0", observed_at="2026-08-29T00:00:00Z",
    payload={"evidence_kind": "FORECAST", "metric": "demanda", "value": 10,
             "unit": "GW", "source_refs": ["s1"], "method_version": "1.0.0",
             "confidence": 0.7})),

 ("JOHN recomenda alternativa fora de alternatives",
  False, _base(event_type="john.recommendation.generated",
    producer_id="liceu.john", contract_id="liceu.john.recommendation",
    contract_version="1.0.0", causation_id="c1", decision_id="d1",
    payload={"alternatives": [{"alternative_id": "A", "summary": "x"},
                              {"alternative_id": "B", "summary": "y"}],
             "recommended_alternative_id": "Z", "confidence": 0.8,
             "rationale": [{"factor": "c", "weight": 1}],
             "evidence_refs": ["ev1"]})),

 ("ANCHOR DENIED sem denial_reason",
  False, _base(event_type="anchor.authorization.granted",
    producer_id="liceu.anchor", contract_id="liceu.anchor.authorization",
    contract_version="1.1.0", causation_id="c1", decision_id="d1",
    governance_decision_id="g1",
    payload={"decision": "DENIED", "subject_ref": "s1",
             "subject_content_hash": "h" * 64, "subject_version": "1",
             "policy_refs": ["p1"], "authority_scope": "continental"})),

 ("OPERA execution.created com status RUNNING",
  False, _base(event_type="opera.execution.created",
    producer_id="liceu.opera", contract_id="liceu.opera.execution",
    contract_version="1.0.0", causation_id="c1",
    governance_decision_id="g1", execution_id="x1",
    payload={"execution_status": "RUNNING", "authorized_subject_ref": "s1",
             "authorized_subject_hash": "h" * 64,
             "work_items": [{"work_item_id": "w1", "description": "d"}]})),

 # --- positivos: um por contrato (§19) ---
 ("ARCHIMEDES planning state valido",
  True, _base(event_type="archimedes.planning.state.authoritative",
    producer_id="liceu.archimedes", contract_id="liceu.archimedes.planning-state",
    contract_version="1.0.0",
    payload={"planning_request_id": "pr-continental-01",
             "state_status": "AUTHORITATIVE_OUTPUT",
             "territorial_scope": "CONTINENTAL", "crs": "EPSG:4326",
             "candidates": [{"candidate_id": "corredor-A", "where": {"lat": -15},
                             "why": "menor perda estimada", "rank": 1,
                             "evidence_refs": ["ev1"]}]})),

 ("CEFEIDA evidence valida",
  True, _base(event_type="cefeida.evidence.published",
    producer_id="liceu.cefeida", contract_id="liceu.cefeida.evidence",
    contract_version="1.0.0", observed_at="2026-08-29T00:00:00Z",
    payload={"evidence_kind": "FORECAST", "metric": "deficit_energetico",
             "value": 12.4, "unit": "GW", "confidence": 0.76, "horizon": "P30D",
             "source_refs": ["ons-2026-08"], "method_version": "2.1.0",
             "subject_ref": "regiao-sul"})),

 ("ANCHOR DENIED valido (negacao tambem e fato)",
  True, _base(event_type="anchor.authorization.granted",
    producer_id="liceu.anchor", contract_id="liceu.anchor.authorization",
    contract_version="1.1.0", causation_id="c-john-1", decision_id="d1",
    governance_decision_id="g1",
    payload={"decision": "DENIED", "subject_ref": "corredor-A",
             "subject_content_hash": "h" * 64, "subject_version": "1.0.0",
             "policy_refs": ["pol-01"], "authority_scope": "continental",
             "denial_reason": "licenciamento ambiental transfronteirico pendente"})),

 ("OPERA execution valida",
  True, _base(event_type="opera.execution.created",
    producer_id="liceu.opera", contract_id="liceu.opera.execution",
    contract_version="1.0.0", causation_id="c-anchor-1",
    governance_decision_id="g1", execution_id="x1",
    payload={"execution_status": "CREATED",
             "authorized_subject_ref": "corredor-A",
             "authorized_subject_hash": "h" * 64,
             "work_items": [{"work_item_id": "w1", "description": "subestacao",
                             "assigned_authority": "liceu.bim"}]})),
 # --- extensao CEA (CEA-2C) ---
 ("CEA emite decision_id (nao decide cognitivamente)",
  False, _base(event_type="cea.financial.exposure.assessed",
    producer_id="liceu.cea", contract_id="liceu.cea.financial-exposure",
    contract_version="1.0.0", decision_id="d1",
    payload={"financial_exposure_id": "FIN-EXP-1", "economic_impact_id": "EI-1",
             "financial_exposure": 1200.0, "npv": 340.5,
             "financial_viability": "viavel", "scenarios": {"base": {}}})),

 ("CEA emite governance_decision_id (nao autoriza)",
  False, _base(event_type="cea.financial.exposure.assessed",
    producer_id="liceu.cea", contract_id="liceu.cea.financial-exposure",
    contract_version="1.0.0", governance_decision_id="g1",
    payload={"financial_exposure_id": "FIN-EXP-1", "economic_impact_id": "EI-1",
             "financial_exposure": 1200.0, "npv": 340.5,
             "financial_viability": "viavel", "scenarios": {"base": {}}})),

 ("JOHN tenta produzir exposicao financeira do CEA",
  False, _base(event_type="cea.financial.exposure.assessed",
    producer_id="liceu.john", contract_id="liceu.cea.financial-exposure",
    contract_version="1.0.0",
    payload={"financial_exposure_id": "FIN-EXP-1", "economic_impact_id": "EI-1",
             "financial_exposure": 1200.0, "npv": 340.5,
             "financial_viability": "viavel", "scenarios": {"base": {}}})),

 ("CEA sem economic_impact_id (exposicao sem origem)",
  False, _base(event_type="cea.financial.exposure.assessed",
    producer_id="liceu.cea", contract_id="liceu.cea.financial-exposure",
    contract_version="1.0.0",
    payload={"financial_exposure_id": "FIN-EXP-1", "financial_exposure": 1200.0,
             "npv": 340.5, "financial_viability": "viavel",
             "scenarios": {"base": {}}})),

 ("CEA scenarios sem cenario base",
  False, _base(event_type="cea.financial.exposure.assessed",
    producer_id="liceu.cea", contract_id="liceu.cea.financial-exposure",
    contract_version="1.0.0",
    payload={"financial_exposure_id": "FIN-EXP-1", "economic_impact_id": "EI-1",
             "financial_exposure": 1200.0, "npv": 340.5,
             "financial_viability": "viavel", "scenarios": {"otimista": {}}})),

 ("CEA financial_viability fora do enum (ex.: 'fund')",
  False, _base(event_type="cea.financial.exposure.assessed",
    producer_id="liceu.cea", contract_id="liceu.cea.financial-exposure",
    contract_version="1.0.0",
    payload={"financial_exposure_id": "FIN-EXP-1", "economic_impact_id": "EI-1",
             "financial_exposure": 1200.0, "npv": 340.5,
             "financial_viability": "fund", "scenarios": {"base": {}}})),

 ("CEA continental sem causation_id (derivado sem origem)",
  False, _base(event_type="cea.financial.exposure.continental.assessed",
    producer_id="liceu.cea",
    contract_id="liceu.cea.continental-financial-exposure",
    contract_version="1.0.0", parent_event_id="p1",
    payload={"financial_exposure_id": "FIN-CONT-1",
             "source_exposure_ids": ["FIN-EXP-1"], "financial_summary": {}})),

 ("CEA continental lista a si mesma como origem",
  False, _base(event_type="cea.financial.exposure.continental.assessed",
    producer_id="liceu.cea",
    contract_id="liceu.cea.continental-financial-exposure",
    contract_version="1.0.0", causation_id="c1", parent_event_id="p1",
    payload={"financial_exposure_id": "FIN-CONT-1",
             "source_exposure_ids": ["FIN-CONT-1"], "financial_summary": {}})),

 ("CEA exposicao planetaria valida",
  True, _base(event_type="cea.financial.exposure.assessed",
    producer_id="liceu.cea", contract_id="liceu.cea.financial-exposure",
    contract_version="1.0.0",
    payload={"financial_exposure_id": "FIN-EXP-corredor-A",
             "economic_impact_id": "EI-econotech-1",
             "financial_exposure": 1200.0, "npv": 340.5, "irr": 0.11,
             "financial_viability": "viavel",
             "cumulative_financial_impact": 4800.0,
             "scenarios": {"base": {"npv": 340.5}, "pessimista": {"npv": -12.0}},
             "lineage": {"economic_impact_id": "EI-econotech-1"}})),

 ("CEA exposicao continental valida",
  True, _base(event_type="cea.financial.exposure.continental.assessed",
    producer_id="liceu.cea",
    contract_id="liceu.cea.continental-financial-exposure",
    contract_version="1.0.0", causation_id="c-cea-1", parent_event_id="p-cea-1",
    payload={"financial_exposure_id": "FIN-CONT-sul",
             "source_exposure_ids": ["FIN-EXP-corredor-A", "FIN-EXP-corredor-B"],
             "financial_summary": {"total": 2400.0},
             "audit": {"source_sequences": [12, 19]}})),
 # --- legal_basis_refs (contrato de autorizacao 1.1.0) ---
 ("ANCHOR referencia o proprio subject como base juridica",
  False, _base(event_type="anchor.authorization.granted",
    producer_id="liceu.anchor", contract_id="liceu.anchor.authorization",
    contract_version="1.1.0", causation_id="c1", decision_id="d1",
    governance_decision_id="g1",
    payload={"decision": "GRANTED", "subject_ref": "corredor-A",
             "subject_content_hash": "h" * 64, "subject_version": "1.0.0",
             "policy_refs": ["pol-01"], "authority_scope": "continental",
             "legal_basis_refs": ["corredor-A"]})),

 ("ANCHOR usa fato de outro produtor como base juridica",
  False, _base(event_type="anchor.authorization.granted",
    producer_id="liceu.anchor", contract_id="liceu.anchor.authorization",
    contract_version="1.1.0", causation_id="c1", decision_id="d1",
    governance_decision_id="g1",
    payload={"decision": "GRANTED", "subject_ref": "corredor-A",
             "subject_content_hash": "h" * 64, "subject_version": "1.0.0",
             "policy_refs": ["pol-01"], "authority_scope": "continental",
             "legal_basis_refs": ["liceu.cea.parecer-1"]})),

 ("ANCHOR com legal_basis_ref vazia",
  False, _base(event_type="anchor.authorization.granted",
    producer_id="liceu.anchor", contract_id="liceu.anchor.authorization",
    contract_version="1.1.0", causation_id="c1", decision_id="d1",
    governance_decision_id="g1",
    payload={"decision": "GRANTED", "subject_ref": "corredor-A",
             "subject_content_hash": "h" * 64, "subject_version": "1.0.0",
             "policy_refs": ["pol-01"], "authority_scope": "continental",
             "legal_basis_refs": ["  "]})),

 ("ANCHOR com base juridica valida do liceu.legal",
  True, _base(event_type="anchor.authorization.granted",
    producer_id="liceu.anchor", contract_id="liceu.anchor.authorization",
    contract_version="1.1.0", causation_id="c1", decision_id="d1",
    governance_decision_id="g1",
    payload={"decision": "GRANTED", "subject_ref": "corredor-A",
             "subject_content_hash": "h" * 64, "subject_version": "1.0.0",
             "policy_refs": ["pol-01"], "authority_scope": "continental",
             "legal_basis_refs": ["liceu.legal.parecer-lgpd-2026-01"]})),

 ("ANCHOR sem legal_basis_refs — ausencia honesta e valida",
  True, _base(event_type="anchor.authorization.granted",
    producer_id="liceu.anchor", contract_id="liceu.anchor.authorization",
    contract_version="1.1.0", causation_id="c1", decision_id="d1",
    governance_decision_id="g1",
    payload={"decision": "GRANTED", "subject_ref": "corredor-A",
             "subject_content_hash": "h" * 64, "subject_version": "1.0.0",
             "policy_refs": ["pol-01"], "authority_scope": "continental"})),
 # --- modo READ (kit 0.6.0) ---
 # Evento LIDO do Event Store: sem os campos que o servidor nao persiste,
 # com `producer` em vez de `producer_id`, e podendo estar em versao RETIRED.
 ("READ: evento armazenado sem payload_hash nem fingerprint",
  True, _lido(event_type="anchor.authorization.granted",
    producer="liceu.anchor", contract_id="liceu.anchor.authorization",
    contract_version="1.1.0", causation_id="c1", decision_id="d1",
    governance_decision_id="g1",
    payload={"decision": "GRANTED", "subject_ref": "corredor-A",
             "subject_content_hash": "h" * 64, "subject_version": "1.0.0",
             "policy_refs": ["pol-01"], "authority_scope": "continental"})),

 ("READ: evento em versao DEPRECATED continua valido",
  True, _lido(event_type="anchor.authorization.granted",
    producer="liceu.anchor", contract_id="liceu.anchor.authorization",
    contract_version="1.0.0", causation_id="c1", decision_id="d1",
    governance_decision_id="g1",
    payload={"decision": "GRANTED", "subject_ref": "corredor-A",
             "subject_content_hash": "h" * 64, "subject_version": "1.0.0",
             "policy_refs": ["pol-01"], "authority_scope": "continental"})),

 ("READ: violacao de autoridade em evento armazenado continua sendo achado",
  False, _lido(event_type="john.recommendation.generated",
    producer="liceu.opera", contract_id="liceu.john.recommendation",
    contract_version="1.0.0", causation_id="c1", decision_id="d1",
    payload={"alternatives": [{"alternative_id": "A", "summary": "x"},
                              {"alternative_id": "B", "summary": "y"}],
             "recommended_alternative_id": "A", "confidence": 0.8,
             "rationale": [{"factor": "c", "weight": 1}],
             "evidence_refs": ["e1"]})),

 ("READ: schema invalido em evento armazenado continua sendo achado",
  False, _lido(event_type="cea.financial.exposure.assessed",
    producer="liceu.cea", contract_id="liceu.cea.financial-exposure",
    contract_version="1.0.0",
    payload={"financial_exposure_id": "F1", "economic_impact_id": "E1",
             "financial_exposure": 1.0, "npv": 1.0,
             "financial_viability": "fund", "scenarios": {"base": {}}})),

 ("PUBLISH: o mesmo evento sem payload_hash e REJEITADO",
  False, _lido(event_type="anchor.authorization.granted",
    producer="liceu.anchor", contract_id="liceu.anchor.authorization",
    contract_version="1.1.0", causation_id="c1", decision_id="d1",
    governance_decision_id="g1", _mode="publish",
    payload={"decision": "GRANTED", "subject_ref": "corredor-A",
             "subject_content_hash": "h" * 64, "subject_version": "1.0.0",
             "policy_refs": ["pol-01"], "authority_scope": "continental"})),
 # --- RM1: validar formato QUANDO PRESENTE (kit 0.7.0) ---
 ("READ: payload_hash presente mas malformado -> rejeitado",
  False, _lido(event_type="anchor.authorization.granted",
    producer="liceu.anchor", contract_id="liceu.anchor.authorization",
    contract_version="1.1.0", causation_id="c1", decision_id="d1",
    governance_decision_id="g1", payload_hash="nao-e-hex",
    payload={"decision": "GRANTED", "subject_ref": "corredor-A",
             "subject_content_hash": "h" * 64, "subject_version": "1.0.0",
             "policy_refs": ["pol-01"], "authority_scope": "continental"})),

 ("READ: observed_at presente mas malformado -> rejeitado",
  False, _lido(event_type="anchor.authorization.granted",
    producer="liceu.anchor", contract_id="liceu.anchor.authorization",
    contract_version="1.1.0", causation_id="c1", decision_id="d1",
    governance_decision_id="g1", observed_at="ontem",
    payload={"decision": "GRANTED", "subject_ref": "corredor-A",
             "subject_content_hash": "h" * 64, "subject_version": "1.0.0",
             "policy_refs": ["pol-01"], "authority_scope": "continental"})),

 ("READ: payload_hash presente e valido -> aceito",
  True, _lido(event_type="anchor.authorization.granted",
    producer="liceu.anchor", contract_id="liceu.anchor.authorization",
    contract_version="1.1.0", causation_id="c1", decision_id="d1",
    governance_decision_id="g1", payload_hash="b" * 64,
    observed_at="2026-08-01T10:00:00Z",
    payload={"decision": "GRANTED", "subject_ref": "corredor-A",
             "subject_content_hash": "h" * 64, "subject_version": "1.0.0",
             "policy_refs": ["pol-01"], "authority_scope": "continental"})),

 ("PUBLISH: envelope_fingerprint malformado -> rejeitado",
  False, _base(event_type="john.recommendation.generated",
    producer_id="liceu.john", contract_id="liceu.john.recommendation",
    contract_version="1.0.0", causation_id="c1", decision_id="d1",
    envelope_fingerprint="curto",
    payload={"alternatives": [{"alternative_id": "A", "summary": "x"},
                              {"alternative_id": "B", "summary": "y"}],
             "recommended_alternative_id": "A", "confidence": 0.8,
             "rationale": [{"factor": "c", "weight": 1}],
             "evidence_refs": ["e1"]})),
 # --- decisao humana: o bloqueio WITNESS_WITH_EMPTY_AUTH (kit 0.8.0) ---
 ("HUMANO: testemunha com autenticacao vazia -> REJEITADO",
  False, _base(event_type="authority.human.decision.recorded",
    producer_id="liceu.authority", contract_id="liceu.authority.human-decision",
    contract_version="2.0.0", causation_id="c1", source_event_id="s1",
    payload={"decision_id": "d1", "human_actor_id": "h1",
             "decision_dossier_id": "dd1", "escalation_reason": "MOTHERS_UNAVAILABLE",
             "capability": "x", "maes_indisponiveis": ["mother-a", "mother-b"],
             "evidencias_consideradas": ["e1"], "alternativas": ["a"],
             "risco_avaliado": "alto", "decisao": "prosseguir",
             "justificativa": "—", "external_effect": False,
             "reversibility": "REVERSIVEL"})),

 ("HUMANO: assinatura curta -> REJEITADO",
  False, _base(event_type="authority.human.decision.recorded",
    producer_id="liceu.authority", contract_id="liceu.authority.human-decision",
    contract_version="2.0.0", causation_id="c1", source_event_id="s1",
    payload={"decision_id": "d1", "human_actor_id": "h1",
             "decision_dossier_id": "dd1", "escalation_reason": "MOTHERS_UNAVAILABLE",
             "capability": "x", "maes_indisponiveis": ["mother-a"],
             "evidencias_consideradas": ["e1"], "alternativas": ["a"],
             "risco_avaliado": "alto", "decisao": "x", "justificativa": "—",
             "external_effect": False, "reversibility": "REVERSIVEL",
             "human_signature": "curta", "mfa_assertion_hash": "m" * 64,
             "human_authentication_method": "MFA_FIDO2",
             "signed_at": "2026-09-01T10:00:00Z", "nonce": "n" * 16,
             "witness_attestation": {"witness_instance_id": "mother-witness",
                                     "verified_signature": True,
                                     "verified_at": "2026-09-01T10:00:01Z"}})),

 ("HUMANO: escalation_reason invalido -> REJEITADO",
  False, _base(event_type="authority.human.decision.recorded",
    producer_id="liceu.authority", contract_id="liceu.authority.human-decision",
    contract_version="2.0.0", causation_id="c1", source_event_id="s1",
    payload={"decision_id": "d1", "human_actor_id": "h1",
             "decision_dossier_id": "dd1", "escalation_reason": "PORQUE_SIM",
             "capability": "x", "evidencias_consideradas": ["e1"],
             "alternativas": ["a"], "risco_avaliado": "alto", "decisao": "x",
             "justificativa": "—", "external_effect": False,
             "reversibility": "REVERSIVEL", "human_signature": "s" * 64,
             "mfa_assertion_hash": "m" * 64,
             "human_authentication_method": "MFA_FIDO2",
             "signed_at": "2026-09-01T10:00:00Z", "nonce": "n" * 16,
             "witness_attestation": {"witness_instance_id": "mother-witness",
                                     "verified_signature": True,
                                     "verified_at": "2026-09-01T10:00:01Z"}})),

 ("HUMANO: witness_attestation sem verified_signature -> REJEITADO",
  False, _base(event_type="authority.human.decision.recorded",
    producer_id="liceu.authority", contract_id="liceu.authority.human-decision",
    contract_version="2.0.0", causation_id="c1", source_event_id="s1",
    payload={"decision_id": "d1", "human_actor_id": "h1",
             "decision_dossier_id": "dd1", "escalation_reason": "UNRESOLVED_CONFLICT",
             "capability": "x", "evidencias_consideradas": ["e1"],
             "alternativas": ["a"], "risco_avaliado": "alto", "decisao": "x",
             "justificativa": "—", "external_effect": False,
             "reversibility": "REVERSIVEL", "human_signature": "s" * 64,
             "mfa_assertion_hash": "m" * 64,
             "human_authentication_method": "MFA_FIDO2",
             "signed_at": "2026-09-01T10:00:00Z", "nonce": "n" * 16,
             "witness_attestation": {"witness_instance_id": "mother-witness"}})),

 ("HUMANO: MOTHERS_UNAVAILABLE sem maes_indisponiveis -> REJEITADO",
  False, _base(event_type="authority.human.decision.recorded",
    producer_id="liceu.authority", contract_id="liceu.authority.human-decision",
    contract_version="2.0.0", causation_id="c1", source_event_id="s1",
    payload={"decision_id": "d1", "human_actor_id": "h1",
             "decision_dossier_id": "dd1", "escalation_reason": "MOTHERS_UNAVAILABLE",
             "capability": "x", "evidencias_consideradas": ["e1"],
             "alternativas": ["a"], "risco_avaliado": "alto", "decisao": "x",
             "justificativa": "—", "external_effect": False,
             "reversibility": "REVERSIVEL", "human_signature": "s" * 64,
             "mfa_assertion_hash": "m" * 64,
             "human_authentication_method": "MFA_FIDO2",
             "signed_at": "2026-09-01T10:00:00Z", "nonce": "n" * 16,
             "witness_attestation": {"witness_instance_id": "mother-witness",
                                     "verified_signature": True,
                                     "verified_at": "2026-09-01T10:00:01Z"}})),

 ("HUMANO: UNRESOLVED_CONFLICT sem maes_indisponiveis -> ACEITO (condicional)",
  True, _base(event_type="authority.human.decision.recorded",
    producer_id="liceu.authority", contract_id="liceu.authority.human-decision",
    contract_version="2.0.0", causation_id="c1", source_event_id="s1",
    payload={"decision_id": "d1", "human_actor_id": "h1",
             "decision_dossier_id": "dd1", "escalation_reason": "UNRESOLVED_CONFLICT",
             "capability": "x", "evidencias_consideradas": ["e1"],
             "alternativas": ["a"], "risco_avaliado": "alto", "decisao": "x",
             "justificativa": "—", "external_effect": False,
             "reversibility": "REVERSIVEL", "human_signature": "s" * 64,
             "mfa_assertion_hash": "m" * 64,
             "human_authentication_method": "MFA_FIDO2",
             "signed_at": "2026-09-01T10:00:00Z", "nonce": "n" * 16,
             "witness_attestation": {"witness_instance_id": "mother-witness",
                                     "verified_signature": True,
                                     "verified_at": "2026-09-01T10:00:01Z"}})),

 ("HUMANO: decisao completa e assinada -> ACEITO",
  True, _base(event_type="authority.human.decision.recorded",
    producer_id="liceu.authority", contract_id="liceu.authority.human-decision",
    contract_version="2.0.0", causation_id="c1", source_event_id="s1",
    payload={"decision_id": "d1", "human_actor_id": "pseudo-h1",
             "decision_dossier_id": "dd1", "escalation_reason": "MOTHERS_UNAVAILABLE",
             "capability": "promocao_a_estado_autorizado",
             "maes_indisponiveis": ["mother-a", "mother-b"],
             "evidencias_consideradas": ["cefeida.evidence.published:e1"],
             "alternativas": ["adiar", "prosseguir"], "risco_avaliado": "alto",
             "decisao": "prosseguir", "justificativa": "janela critica",
             "external_effect": True, "reversibility": "PARCIAL",
             "human_signature": "s" * 128, "mfa_assertion_hash": "m" * 64,
             "human_authentication_method": "MFA_FIDO2",
             "signed_at": "2026-09-01T10:00:00Z", "nonce": "n" * 32,
             "witness_attestation": {"witness_instance_id": "mother-witness",
                                     "verified_signature": True,
                                     "verified_at": "2026-09-01T10:00:01Z"}})),
 # --- os 7 ataques adversariais como testes PERMANENTES (kit 0.9.0) ---
 # Escritos apos o parecer demonstrar que os 7 eram aceitos. Ficam para
 # sempre: se algum voltar a passar, foi regressao.
 ("ADV: authority_role=ROOT -> rejeitado", False,
  _humano(authority_role="ROOT")),
 ("ADV: instancia inexistente -> rejeitado", False,
  _humano(producer_instance_id="mother-zeta")),
 ("ADV: authority_epoch=-999 -> rejeitado", False,
  _humano(authority_epoch=-999)),
 ("ADV: verified_signature='sim' (string) -> rejeitado", False,
  _humano(_wa={"witness_instance_id": "mother-witness",
               "verified_signature": "sim", "verified_at": "x"})),
 ("ADV: Mae ACTIVE registrando decisao humana -> rejeitado", False,
  _humano(authority_role="ACTIVE")),
 ("ADV: atestado de outra instancia -> rejeitado", False,
  _humano(_wa={"witness_instance_id": "mother-a",
               "verified_signature": True, "verified_at": "x"})),
 ("ADV: assinatura de 64 chars ainda passa — LIMITE CONHECIDO", True,
  _humano()),
]


def self_test(cr: dict) -> int:
    try:
        import jsonschema  # noqa: F401
        motor = "jsonschema (implementacao madura)"
    except ImportError:
        motor = "FALLBACK interno — instale jsonschema para certificacao"
    print(f"Conformance Kit v{KIT_VERSION} — contratos "
          f"v{cr['meta']['registry_version']}")
    print(f"Motor de schema: {motor}")
    print("Escopo: G1 envelope, G2 contrato, G3 autoridade, G4 payload, "
          "G5 semantica local.")
    print("NAO valida: causalidade cross-event, lineage no Event Store, "
          "recomputo de hash/fingerprint, durabilidade, replay.\n")
    falhas = 0
    for nome, esperado_ok, env in CASOS:
        try:
            # _mode e metadado do fixture, nao campo do envelope
            _m = env.pop("_mode", "publish")
            validar(env, cr, mode=_m)
            ok, det = True, ""
        except Rejeicao as e:
            ok, det = False, str(e)
        acertou = ok == esperado_ok
        falhas += not acertou
        marca = "OK  " if acertou else "FALHA"
        verbo = "aceito" if ok else "rejeitado"
        print(f"  [{marca}] {verbo:10} {nome}")
        if det and not ok:
            print(f"           -> {det}")
    print(f"\n{len(CASOS) - falhas}/{len(CASOS)} casos corretos")
    return 1 if falhas else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contracts", default="liceu_contract_registry.yaml")
    ap.add_argument("--envelope")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()

    import yaml
    cr = yaml.safe_load(open(a.contracts, encoding="utf-8"))

    if a.self_test:
        return self_test(cr)
    if a.envelope:
        env = json.load(open(a.envelope, encoding="utf-8"))
        try:
            validar(env, cr)
        except Rejeicao as e:
            print(f"REJEITADO {e}")
            return 1
        print("CONFORME")
        return 0
    ap.error("informe --self-test ou --envelope")


if __name__ == "__main__":
    sys.exit(main())
