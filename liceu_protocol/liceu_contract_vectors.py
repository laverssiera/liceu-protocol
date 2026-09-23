#!/usr/bin/env python3
"""
liceu_contract_vectors — os vetores que o produtor tem de aceitar, e os que tem
de recusar, derivados do payload_schema do proprio contrato.

O gap que este modulo fecha: as fitness conferem o genoma contra o kit, e nunca
a IMPLEMENTACAO contra o contrato. Dois defeitos de 2026-09-22 sao dessa classe,
e os dois so apareceram quando alguem tentou rodar a cadeia:

  o JOHN lia a cadeia ao contrario
  o CEFEIDA exigia `value` numerico, e o contrato admite number, string OU object

O segundo e o que da o nome ao metodo. A falha que importa nao e o produtor
aceitar lixo — e o produtor RECUSAR o que o contrato admite. Um teste escrito
com o payload que o produtor ja sabe gerar nunca encontra isso, porque ele so
exercita o caminho que o autor tinha na cabeca.

Por isso os vetores VALIDOS varrem a faixa inteira que o contrato admite:

  cada membro de uma uniao de tipos       (`["number","string","object"]`)
  cada valor de enum
  cada propriedade opcional, presente
  o limite exato de minItems e minLength

E os INVALIDOS sao o que o produtor tem de recusar:

  cada campo obrigatorio, ausente         (um vetor por campo)
  tipo errado em cada campo tipado
  array abaixo de minItems
  valor fora do enum
  campo a mais, quando additionalProperties e false

Os vetores moram AQUI porque o contrato mora aqui. Cada produtor que publica
roda os do seu contrato na propria CI, com um adaptador de tres linhas que diz
se ele aceitaria aquele payload. Quem ainda nao publica herda a verificacao no
dia em que passar a publicar — sem ninguem escrever quinze suites.

Uso:
    python liceu_contract_vectors.py --self-test
    python liceu_contract_vectors.py --contract liceu.cefeida.evidence --version 2.0.0
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent


# ─────────────────────────────────────────────────────── valores de exemplo

def _exemplo(esquema: dict, semente: str = "x"):
    """Um valor que SATISFAZ este esquema. Nao e aleatorio: o mesmo esquema da
    sempre o mesmo valor, para o vetor ser reproduzivel e o diff, legivel."""
    if "enum" in esquema and esquema["enum"]:
        return esquema["enum"][0]
    if "const" in esquema:
        return esquema["const"]
    # Uma condicional se escreve com `anyOf`/`oneOf` e com `contains`, e sem
    # ler os dois nao da para construir o payload que ACIONA a condicional —
    # e regra que nao se aciona nao vira vetor nenhum.
    for ramo in ("anyOf", "oneOf"):
        if esquema.get(ramo):
            return _exemplo({**{k: v for k, v in esquema.items() if k != ramo},
                             **esquema[ramo][0]}, semente)
    tipos = esquema.get("type")
    tipo = tipos[0] if isinstance(tipos, list) else tipos
    # subesquema de `if` nao declara `type`: quem tem properties/required e objeto
    if tipo is None and ("properties" in esquema or "required" in esquema):
        tipo = "object"
    if tipo is None and "contains" in esquema:
        tipo = "array"
    if tipo == "array" and esquema.get("contains"):
        return [_exemplo(esquema["contains"], semente)]
    if tipo == "object":
        obj = {}
        props = esquema.get("properties") or {}
        for nome in esquema.get("required") or []:
            obj[nome] = _exemplo(props.get(nome) or {"type": "string"}, nome)
        if not obj and not props:
            obj = {"campo": "valor"}
        return obj
    if tipo == "array":
        item = esquema.get("items") or {"type": "string"}
        n = max(1, int(esquema.get("minItems") or 1))
        return [_exemplo(item, f"{semente}{i}") for i in range(n)]
    if tipo == "integer":
        return int(esquema.get("minimum", 1) or 1)
    if tipo == "number":
        return float(esquema.get("minimum", 1) or 1)
    if tipo == "boolean":
        return True
    if tipo == "null":
        return None
    minimo = int(esquema.get("minLength") or 0)
    base = semente if len(semente) >= max(1, minimo) else semente * (minimo // len(semente) + 1)
    return base[:minimo] if minimo and len(base) > minimo else base


def _tipo_errado(esquema: dict):
    """Um valor que o esquema NAO admite, qualquer que seja o tipo declarado."""
    tipos = esquema.get("type")
    admitidos = set(tipos) if isinstance(tipos, list) else ({tipos} if tipos else set())
    for candidato, tipo in ((12345, "integer"), ("nao-e-numero", "string"),
                            ([1, 2], "array"), ({"a": 1}, "object"), (True, "boolean")):
        if tipo not in admitidos and not (tipo == "integer" and "number" in admitidos):
            return candidato
    return object()          # nenhum tipo JSON serve: o esquema admite tudo


# ─────────────────────────────────────────────────────── os vetores

def _fundir(alvo, novo):
    """Funde `novo` em `alvo` sem perder o que o alvo ja tinha.

    Substituir seria facil e errado: o candidate do payload minimo ja carrega
    candidate_id, why e evidence_refs, e o exemplo do `if` so traz o que aciona
    a condicional. Array funde ELEMENTO A ELEMENTO, pelo mesmo motivo.
    """
    if isinstance(alvo, dict) and isinstance(novo, dict):
        for k, v in novo.items():
            alvo[k] = _fundir(alvo.get(k), v) if k in alvo else v
        return alvo
    if isinstance(alvo, list) and isinstance(novo, list) and alvo:
        return [_fundir(a, novo[0]) if i == 0 else a for i, a in enumerate(alvo)]
    return novo if alvo is None else (novo if not isinstance(alvo, (dict, list)) else alvo)


COND_ESQUEMA = ("if", "then", "else", "allOf", "anyOf", "oneOf", "not", "dependentRequired")


def _campos_condicionados(no, dentro: bool = False) -> set:
    """Campos que aparecem SOB construto condicional do esquema.

    Sao eles que viram vetor invalido: tirar um campo que o esquema so exige
    em certas condicoes e a unica forma de a regra condicional virar teste.
    """
    achados: set = set()
    if isinstance(no, dict):
        for k, v in no.items():
            if k in COND_ESQUEMA:
                achados |= _campos_condicionados(v, True)
            elif dentro:
                if k == "required" and isinstance(v, list):
                    achados |= {str(x) for x in v}
                elif k == "properties" and isinstance(v, dict):
                    achados |= set(v)
                    for sub in v.values():
                        achados |= _campos_condicionados(sub, True)
                else:
                    achados |= _campos_condicionados(v, True)
    elif isinstance(no, list):
        for x in no:
            achados |= _campos_condicionados(x, dentro)
    return achados


def _ajustar(payload: dict, esquema: dict, validador) -> tuple[dict | None, list[str]]:
    """Faz o payload OBEDECER as condicionais do esquema, ou diz que nao da.

    Ate a 0.17.0 o gerador so lia `properties`/`required`, entao para um esquema
    com `if`/`then` ele produzia payload que o proprio contrato PROIBE — e depois
    acusava o produtor que corretamente o recusava. Foi o caso do FORECAST sem
    confidence. A saida era uma valvula (`condicionais`) onde o CONSUMIDOR
    declarava a regra a mao.

    Aqui a pergunta vai para quem sabe responder: o esquema. Cada erro de
    `required` que a validacao aponta vira um campo acrescentado, e cada erro
    de `minItems` vira um array preenchido ate o limite — ambos com o exemplo
    do proprio subesquema. Devolve (payload, campos_acrescentados), ou
    (None, ...) quando o payload e invalido por motivo que nao se repara — e ai
    ele nao era um vetor valido, e muda de lado.

    Isto vale para QUALQUER construto do JSON Schema, e nao so `if`/`then`:
    quem responde e a validacao, nao uma leitura minha do esquema.
    """
    props = esquema.get("properties") or {}
    acrescentados: list[str] = []
    for _ in range(8):                      # um reparo pode disparar o proximo
        erros = list(validador.iter_errors(payload))
        if not erros:
            return payload, acrescentados
        reparo = None
        for e in erros:
            for sub in ([e] + list(e.context or [])):
                # So o TOPO se repara. Um `required` que veio de dentro de um
                # item de array tem caminho proprio, e acrescentar aquele nome
                # na raiz do payload inventaria um campo que o contrato nao
                # declara — bug encontrado ao gerar o vetor que aciona a
                # condicional do `crs`.
                if (sub.validator == "required" and sub.validator_value
                        and not list(sub.absolute_path)):
                    ausentes = [c for c in sub.validator_value if c not in payload]
                    if ausentes:
                        reparo = ("required", ausentes[0], sub)
                        break
                # `candidates nao vazio quando state_status = AUTHORITATIVE_OUTPUT`
                # nao e `required`: candidates JA esta em required, e a condicional
                # exige minItems. Sem tratar isto, o vetor valido de
                # AUTHORITATIVE_OUTPUT seria jogado para os invalidos e a faixa
                # que o contrato admite ficaria menor em silencio.
                if sub.validator == "minItems":
                    caminho = list(sub.absolute_path)
                    if len(caminho) == 1 and isinstance(caminho[0], str):
                        reparo = ("minItems", caminho[0], sub)
                        break
            if reparo:
                break
        if reparo is None:
            return None, acrescentados      # invalido por motivo que nao se repara
        tipo, campo, sub = reparo
        esq_campo = props.get(campo) or {"type": "string"}
        if tipo == "required":
            payload = {**payload, campo: _exemplo(esq_campo, campo)}
        else:
            n = int(sub.validator_value)
            itens = esq_campo.get("items") or {"type": "string"}
            payload = {**payload,
                       campo: [_exemplo(itens, f"{campo}{i}") for i in range(n)]}
        acrescentados.append(campo)
    return None, acrescentados


def vetores(payload_schema: dict) -> dict:
    """{validos: [{caso, payload}], invalidos: [{caso, payload, porque}]}"""
    props = payload_schema.get("properties") or {}
    obrigatorios = list(payload_schema.get("required") or [])
    base = _exemplo(payload_schema)

    validos = [{"caso": "minimo: so os campos obrigatorios", "payload": copy.deepcopy(base)}]

    for nome, esq in sorted(props.items()):
        tipos = esq.get("type")
        # A FAIXA INTEIRA de uma uniao de tipos. Foi aqui que o CEFEIDA caiu.
        if isinstance(tipos, list) and len(tipos) > 1:
            for t in tipos:
                if t == "null":
                    continue
                p = copy.deepcopy(base)
                p[nome] = _exemplo({**esq, "type": t}, nome)
                validos.append({"caso": f"{nome}: tipo {t} da uniao {tipos}", "payload": p})
        # cada valor de enum
        if esq.get("enum"):
            for v in esq["enum"]:
                p = copy.deepcopy(base)
                p[nome] = v
                validos.append({"caso": f"{nome}: enum {v!r}", "payload": p})
        # opcional presente
        if nome not in obrigatorios:
            p = copy.deepcopy(base)
            p[nome] = _exemplo(esq, nome)
            validos.append({"caso": f"{nome}: opcional presente", "payload": p})
        # limite exato de minItems
        if esq.get("minItems"):
            p = copy.deepcopy(base)
            p[nome] = [_exemplo(esq.get("items") or {"type": "string"}, f"{nome}{i}")
                       for i in range(int(esq["minItems"]))]
            validos.append({"caso": f"{nome}: exatamente minItems={esq['minItems']}", "payload": p})

    invalidos = []
    for nome in obrigatorios:
        p = copy.deepcopy(base)
        p.pop(nome, None)
        invalidos.append({"caso": f"{nome}: obrigatorio ausente", "payload": p,
                          "porque": "required"})
    for nome, esq in sorted(props.items()):
        if nome in base:
            p = copy.deepcopy(base)
            p[nome] = _tipo_errado(esq)
            if not isinstance(p[nome], object) or p[nome].__class__ is object:
                continue
            invalidos.append({"caso": f"{nome}: tipo errado", "payload": p, "porque": "type"})
        if esq.get("minItems", 0) > 0 and nome in base:
            p = copy.deepcopy(base)
            p[nome] = []
            invalidos.append({"caso": f"{nome}: array abaixo de minItems", "payload": p,
                              "porque": "minItems"})
        if esq.get("enum"):
            p = copy.deepcopy(base)
            p[nome] = "VALOR_FORA_DO_ENUM"
            invalidos.append({"caso": f"{nome}: fora do enum", "payload": p, "porque": "enum"})
    if payload_schema.get("additionalProperties") is False:
        p = copy.deepcopy(base)
        p["campo_que_o_contrato_nao_declara"] = "x"
        invalidos.append({"caso": "campo a mais", "payload": p,
                          "porque": "additionalProperties: false"})

    # ─────────── as condicionais do esquema, respondidas pelo esquema
    # Cada valido passa pela validacao completa. O que so precisa de um campo
    # exigido condicionalmente ganha esse campo — e o payload SEM ele vira um
    # invalido novo, que e exatamente a regra condicional virada vetor. O que
    # nao se repara nunca foi valido, e muda de lado com o motivo.
    from jsonschema import Draft202012Validator
    validador = Draft202012Validator(payload_schema)
    condicionados = _campos_condicionados(payload_schema)

    # Um vetor por CONDICIONAL, construido para ACIONA-LA. Sem isto, uma
    # condicional cujo `if` o payload minimo nao satisfaz fica sem vetor
    # nenhum: a regra entra no contrato e nada a exercita. Foi o caso do
    # `crs obrigatorio quando ha geometria`, em que o `where` do minimo e
    # vazio e a condicional nunca disparava.
    for i, ramo in enumerate(payload_schema.get("allOf") or []):
        if not isinstance(ramo, dict) or "if" not in ramo:
            continue
        gatilho = _fundir(copy.deepcopy(base), _exemplo(ramo["if"]))
        if isinstance(gatilho, dict):
            validos.append({"caso": f"condicional {i + 1}: payload que a ACIONA",
                            "payload": gatilho})

    ok, extras = [], []
    for caso in validos:
        ajustado, acrescentados = _ajustar(caso["payload"], payload_schema, validador)
        if ajustado is None:
            invalidos.append({"caso": f"{caso['caso']} (o esquema proibe)",
                              "payload": caso["payload"],
                              "porque": "condicional do esquema"})
            continue
        if acrescentados:
            caso = {"caso": f"{caso['caso']} + condicional ({', '.join(acrescentados)})",
                    "payload": ajustado}
        ok.append(caso)

        # A REGRA CONDICIONAL VIRA TESTE. Derivar o invalido so do reparo era
        # estreito: quando o payload ja satisfazia a condicional, nao havia
        # reparo e nenhum vetor exercitava a regra — foi o caso de
        # `candidates nao vazio quando state_status = AUTHORITATIVE_OUTPUT`,
        # onde o minimo do gerador ja vinha com um candidate. Aqui a mutacao e
        # deliberada, e so vira vetor se o ESQUEMA a recusar.
        for campo in sorted(condicionados):
            if campo not in ajustado:
                continue
            # campo que ja e obrigatorio SEMPRE nao ganha vetor novo por tira-lo:
            # "obrigatorio ausente" ja o cobre, e dois vetores com o mesmo
            # payload e nomes diferentes so enchem o relatorio
            sem = ({} if campo in obrigatorios
                   else {k: v for k, v in ajustado.items() if k != campo})
            if sem and list(validador.iter_errors(sem)):
                extras.append({"caso": f"{campo}: exigido pela condicional do esquema",
                               "payload": sem, "porque": "condicional do payload_schema"})
            if isinstance(ajustado[campo], list) and ajustado[campo]:
                vazio = {**ajustado, campo: []}
                if list(validador.iter_errors(vazio)):
                    extras.append({"caso": f"{campo}: vazio, proibido pela condicional do esquema",
                                   "payload": vazio, "porque": "condicional do payload_schema"})
    validos = ok
    vistos = {c["caso"] for c in invalidos}
    for e in extras:
        if e["caso"] not in vistos:
            invalidos.append(e)
            vistos.add(e["caso"])

    # E o outro lado: um "invalido" que o esquema ACEITA nao e invalido. Deixa-lo
    # na lista faria o relatorio cobrar do produtor uma recusa que o contrato
    # nao autoriza — o erro que este modulo existe para nao cometer.
    invalidos = [c for c in invalidos if validador.iter_errors(c["payload"])]

    return {"validos": validos, "invalidos": invalidos}


def do_contrato(contract_id: str, version: str, registry: dict | None = None) -> dict:
    if registry is None:
        import yaml
        registry = yaml.safe_load((KIT / "liceu_contract_registry.yaml").read_text(encoding="utf-8"))
    contratos = registry.get("contracts") or registry
    if contract_id not in contratos:
        raise KeyError(f"contrato {contract_id!r} nao esta no registry")
    if version not in contratos[contract_id]:
        raise KeyError(f"{contract_id} nao tem a versao {version!r}")
    esquema = contratos[contract_id][version].get("payload_schema")
    if not esquema:
        raise KeyError(f"{contract_id}@{version} nao declara payload_schema")
    return vetores(esquema)


def conferir(aceita, contract_id: str, version: str, registry: dict | None = None,
             condicionais: list[tuple] | None = None) -> list[str]:
    """`aceita(payload) -> (bool, motivo)`. Devolve os problemas encontrados.

    A falha que importa esta primeiro: RECUSAR o que o contrato admite.

    `condicionais` e a parte honesta e incomoda deste metodo. Alguns contratos
    declaram exigencia CONDICIONAL em prosa — "confidence obrigatorio quando
    kind = FORECAST" — e o payload_schema nao a carrega. Um gerador que le so o
    esquema produz payload que o contrato PROIBE, e o produtor que o recusa
    esta certo. Enquanto a condicional nao estiver no esquema (`if`/`then`,
    `dependentRequired`), quem chama declara aqui:

        condicionais=[(lambda p: p.get("evidence_kind") == "FORECAST"
                                 and "confidence" not in p,
                       'domain_invariant: "confidence obrigatorio quando kind = FORECAST"')]

    Cada par e (predicado, citacao). O predicado verdadeiro move o vetor de
    valido para invalido — o produtor TEM de recusa-lo. A citacao existe para
    que ninguem silencie um vetor sem apontar a linha do contrato que autoriza.
    """
    v = do_contrato(contract_id, version, registry)
    problemas = []
    condicionais = condicionais or []

    def proibido_por_invariante(payload):
        for pred, citacao in condicionais:
            if pred(payload):
                return citacao
        return None

    movidos = []
    restam = []
    for caso in v["validos"]:
        citacao = proibido_por_invariante(caso["payload"])
        if citacao:
            movidos.append({**caso, "porque": citacao})
        else:
            restam.append(caso)
    v["validos"], v["invalidos"] = restam, v["invalidos"] + movidos

    for caso in v["validos"]:
        ok, motivo = aceita(caso["payload"])
        if not ok:
            problemas.append(
                f"RECUSA O QUE O CONTRATO ADMITE — {caso['caso']}: o produtor respondeu "
                f"{motivo!r}. O contrato {contract_id}@{version} admite este payload; o "
                f"produtor esta MAIS ESTREITO que o proprio contrato.")
    for caso in v["invalidos"]:
        ok, _ = aceita(caso["payload"])
        if ok:
            problemas.append(
                f"aceita o que o contrato proibe — {caso['caso']} ({caso['porque']}): o "
                f"produtor deixou passar payload que {contract_id}@{version} nao admite.")
    return problemas


# ─────────────────────────────────────────────────────── self-test

def _self_test() -> int:
    esquema = {
        "type": "object", "additionalProperties": False,
        "required": ["metric", "value", "source_refs"],
        "properties": {
            "metric": {"type": "string", "minLength": 1},
            "value": {"type": ["number", "string", "object"]},
            "unit": {"type": "string"},
            "kind": {"type": "string", "enum": ["OBSERVATION", "METRIC"]},
            "source_refs": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        },
    }
    v = vetores(esquema)
    casos = [c["caso"] for c in v["validos"]]
    ok = True

    def diz(cond, msg):
        nonlocal ok
        print(f"  [{'OK  ' if cond else 'FALHA'}] {msg}")
        ok = ok and cond

    diz(any("tipo number" in c for c in casos) and any("tipo string" in c for c in casos)
        and any("tipo object" in c for c in casos),
        "a uniao de tipos gera um valido por membro — e o caso do CEFEIDA")
    diz(sum(1 for c in casos if "enum" in c) == 2, "um valido por valor de enum")
    diz(any("opcional presente" in c for c in casos), "opcional presente vira valido")
    diz(any("minItems" in c for c in casos), "o limite exato de minItems vira valido")
    invs = [c["caso"] for c in v["invalidos"]]
    diz(sum(1 for c in invs if "obrigatorio ausente" in c) == 3,
        "um invalido por campo obrigatorio")
    diz(any("campo a mais" in c for c in invs), "additionalProperties false vira invalido")
    diz(any("abaixo de minItems" in c for c in invs), "array vazio vira invalido")

    # um produtor MAIS ESTREITO que o contrato: exige value numerico
    def estreito(p):
        if not isinstance(p.get("value"), (int, float)) or isinstance(p.get("value"), bool):
            return False, "value_not_numeric"
        return True, ""

    probs = conferir(estreito, "x", "1.0.0", {"x": {"1.0.0": {"payload_schema": esquema}}})
    diz(any("RECUSA O QUE O CONTRATO ADMITE" in p and "tipo string" in p for p in probs)
        and any("RECUSA O QUE O CONTRATO ADMITE" in p and "tipo object" in p for p in probs),
        "o produtor estreito e PEGO — teria achado o CEFEIDA antes de a cadeia travar")

    # um produtor que aceita tudo: tem de ser pego pelos invalidos
    probs = conferir(lambda p: (True, ""), "x", "1.0.0", {"x": {"1.0.0": {"payload_schema": esquema}}})
    diz(any("aceita o que o contrato proibe" in p for p in probs),
        "o produtor que aceita tudo tambem e pego")

    # a exigencia CONDICIONAL que so existe na prosa do contrato
    esq_cond = {
        "type": "object", "required": ["kind"],
        "properties": {"kind": {"type": "string", "enum": ["OBSERVATION", "FORECAST"]},
                       "confidence": {"type": "number"}},
    }
    reg_cond = {"x": {"1.0.0": {"payload_schema": esq_cond}}}

    def exige_confidence(p):
        if p.get("kind") == "FORECAST" and "confidence" not in p:
            return False, "confidence_missing"
        return True, ""

    citacao = 'domain_invariant: "confidence obrigatorio quando kind = FORECAST"'
    probs = conferir(exige_confidence, "x", "1.0.0", reg_cond,
                     [(lambda p: p.get("kind") == "FORECAST" and "confidence" not in p, citacao)])
    diz(not any("RECUSA O QUE O CONTRATO ADMITE" in p for p in probs),
        "a condicional declarada com citacao tira o falso positivo do FORECAST")

    probs = conferir(exige_confidence, "x", "1.0.0", reg_cond)
    diz(any("RECUSA O QUE O CONTRATO ADMITE" in p and "FORECAST" in p for p in probs),
        "sem a declaracao, a mesma recusa e acusada — a valvula nao e silenciosa")

    # a mesma condicional, agora NO ESQUEMA: o gerador nao precisa mais que
    # ninguem lhe conte a regra
    esq_schema = {
        "type": "object", "required": ["kind"], "additionalProperties": False,
        "properties": {"kind": {"type": "string", "enum": ["OBSERVATION", "FORECAST"]},
                       "confidence": {"type": "number"}},
        "allOf": [{"if": {"properties": {"kind": {"const": "FORECAST"}},
                          "required": ["kind"]},
                   "then": {"required": ["confidence"]}}],
    }
    reg_schema = {"x": {"1.0.0": {"payload_schema": esq_schema}}}
    vs = do_contrato("x", "1.0.0", reg_schema)

    forecasts = [c for c in vs["validos"] if c["payload"].get("kind") == "FORECAST"]
    diz(bool(forecasts) and all("confidence" in c["payload"] for c in forecasts),
        "o valido de FORECAST ja nasce com o campo que a condicional exige")
    diz(any(c["caso"] == "confidence: exigido pela condicional do esquema"
            for c in vs["invalidos"]),
        "a condicional do esquema vira vetor INVALIDO — a regra virou teste")
    diz(all(not list(__import__("jsonschema").Draft202012Validator(esq_schema)
                     .iter_errors(c["payload"])) for c in vs["validos"]),
        "nenhum valido do gerador e recusado pelo proprio esquema")

    probs = conferir(exige_confidence, "x", "1.0.0", reg_schema)   # SEM valvula
    diz(not any("RECUSA O QUE O CONTRATO ADMITE" in p for p in probs),
        "com a condicional no esquema, o produtor passa SEM a valvula — o que a "
        "B3 so conseguia com declaracao a mao")

    # a condicional que NAO e `required`: o campo ja e obrigatorio, e a regra
    # exige que ele nao venha VAZIO — o caso do planning-state
    esq_min = {
        "type": "object", "required": ["status", "itens"],
        "properties": {"status": {"type": "string", "enum": ["RASCUNHO", "FINAL"]},
                       "itens": {"type": "array", "items": {"type": "string"}}},
        "allOf": [{"if": {"properties": {"status": {"const": "FINAL"}},
                          "required": ["status"]},
                   "then": {"properties": {"itens": {"minItems": 1}}}}],
    }
    vm = do_contrato("x", "1.0.0", {"x": {"1.0.0": {"payload_schema": esq_min}}})
    finais = [c for c in vm["validos"] if c["payload"].get("status") == "FINAL"]
    diz(bool(finais) and all(c["payload"].get("itens") for c in finais),
        "o valido de FINAL nao sai com o array vazio que a condicional proibe")
    diz(any(c["caso"] == "itens: vazio, proibido pela condicional do esquema"
            for c in vm["invalidos"]),
        "condicional de minItems tambem vira vetor INVALIDO — nao so as de `required`")
    diz(sum(1 for c in vm["invalidos"]
            if c["caso"].startswith("itens:") and "condicional" in c["caso"]) == 1,
        "campo ja obrigatorio nao ganha vetor repetido por ser condicionado")

    # a condicional que so dispara com o CONTEUDO de um item de array — o caso
    # do `crs obrigatorio quando ha geometria`
    esq_geo = {
        "type": "object", "required": ["itens"], "additionalProperties": False,
        "properties": {"crs": {"type": "string"},
                       "itens": {"type": "array", "minItems": 1, "items": {
                           "type": "object", "required": ["id", "onde"],
                           "properties": {"id": {"type": "string"}, "onde": {"type": "object"}}}}},
        "allOf": [{"if": {"properties": {"itens": {"contains": {
                              "type": "object", "required": ["onde"],
                              "properties": {"onde": {"anyOf": [{"required": ["coordinates"]},
                                                                {"required": ["lat"]}]}}}}},
                          "required": ["itens"]},
                   "then": {"required": ["crs"]}}],
    }
    vg = do_contrato("x", "1.0.0", {"x": {"1.0.0": {"payload_schema": esq_geo}}})
    acionam = [c for c in vg["validos"] if "ACIONA" in c["caso"]]
    diz(bool(acionam), "cada condicional ganha um valido construido para ACIONA-LA")
    diz(any("coordinates" in (c["payload"]["itens"][0].get("onde") or {}) and c["payload"].get("crs")
            for c in acionam),
        "o valido que aciona vem COMPLETO: com a coordenada e com o crs que ela exige")
    diz(all(c["payload"]["itens"][0].get("id") is not None for c in acionam),
        "acionar a condicional nao apaga o que o item ja tinha — a fusao preserva")
    diz(any(c["caso"] == "crs: exigido pela condicional do esquema" for c in vg["invalidos"]),
        "e o payload com coordenada e SEM crs vira o vetor invalido")

    print(f"\n{'TODOS OS CASOS CORRETOS' if ok else 'HOUVE FALHA'}")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--contract")
    ap.add_argument("--version", default=None)
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.contract:
        ap.error("--contract ou --self-test")
    import yaml
    reg = yaml.safe_load((KIT / "liceu_contract_registry.yaml").read_text(encoding="utf-8"))
    contratos = reg.get("contracts") or reg
    versao = a.version or sorted(contratos[a.contract])[-1]
    print(json.dumps(do_contrato(a.contract, versao, reg), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
