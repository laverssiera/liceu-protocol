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
    tipos = esquema.get("type")
    tipo = tipos[0] if isinstance(tipos, list) else tipos
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


def conferir(aceita, contract_id: str, version: str, registry: dict | None = None) -> list[str]:
    """`aceita(payload) -> (bool, motivo)`. Devolve os problemas encontrados.

    A falha que importa esta primeiro: RECUSAR o que o contrato admite.
    """
    v = do_contrato(contract_id, version, registry)
    problemas = []
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
