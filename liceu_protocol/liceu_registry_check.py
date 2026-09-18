#!/usr/bin/env python3
"""
LICEU 6.0 — Registry Consistency Checker
=========================================
Fase P2.2B

Prova a INTEGRIDADE INTERNA do protocolo, antes de qualquer runtime.

Os quatro artifacts referenciam uns aos outros. Sem um verificador, um
`allowed_producers` apontando para um producer_id que nao existe, ou um
`contract_version` fora de SemVer, so seria descoberto quando o SDK falhasse
em producao — ou pior, quando nao falhasse.

VERIFICACOES

  R01  os 15 producer_id SOBERANOS existem exatamente uma vez
  R01B classe de autoridade sem estado de dominio; 3 papeis declarados
  R02  producer_id segue o padrao canonico e nao carrega geografia
  R03  todo `owner` de evento resolve no Producer Registry
  R04  todo `allowed_producers` resolve no Producer Registry
  R05  todo contract_id do Event Registry resolve no Contract Registry
  R06  contract_version bate entre Event Registry e Contract Registry
  R07  event_type <-> contrato consistente nos dois sentidos
  R08  toda contract_version e SemVer estrito
  R09  toda referencia de payload_schema resolve
  R10  a cadeia de lineage nao tem conflito (exigido e proibido ao mesmo tempo)
  R11  a cadeia causal minima esta completa e ordenada
  R12  capacidades declaradas coerentes com o plano de autoridade
  R00  integridade do pacote: todo artifact governado presente
  R0C  autoconsistencia da Constituicao: meta.versao == milestone.
       current_constitution_version (M1.baseline_constitution_version e
       historico e pode divergir de proposito)
  R13A todo artifact governado declara constitution_version
  R13B todo artifact governado declara constitution_sha256
  R13C todo hash declarado == constituicao fornecida
  R13D toda versao declarada == constituicao fornecida, OU ha declaracao
       explicita de compatibilidade

USO
    python3 liceu_registry_check.py
    python3 liceu_registry_check.py --json registry-consistency.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import datetime

CHECKER_VERSION = "1.4.0"

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
PRODUCER_ID = re.compile(r"^liceu\.[a-z][a-z0-9-]*$")
# Geografia NUNCA entra no producer_id — vive em federation_id / node_id / scope
GEOGRAFIA = re.compile(r"\b(earth|terra|mars|marte|luna|moon|orbital|"
                       r"southamerica|europe|asia)\b", re.I)

ERRO, AVISO = "ERRO", "AVISO"


class Resultado:
    def __init__(self):
        self.itens: list[tuple[str, str, str, str]] = []

    def add(self, regra, nivel, msg, detalhe=""):
        self.itens.append((regra, nivel, msg, detalhe))

    def ok(self, regra, msg):
        self.itens.append((regra, "OK", msg, ""))

    @property
    def erros(self):
        return [i for i in self.itens if i[1] == ERRO]

    @property
    def avisos(self):
        return [i for i in self.itens if i[1] == AVISO]


# P2.2E — artifacts que o protocolo EXIGE. Ausencia e erro, nunca omissao.
ARTIFACTS_GOVERNADOS = {
    "liceu_constitution.yaml": "lei",
    "liceu_producer_registry.yaml": "identidade",
    "liceu_contract_registry.yaml": "contratos e schemas",
    "liceu_event_registry.yaml": "eventos canonicos",
    "liceu_event_reconciliation_ledger.yaml": "migracao e historia",
}
FERRAMENTAL = {
    "liceu_registry_check.py": "consistencia dos registries",
    "liceu_conformance.py": "G1-G5",
    "liceu_federation_sdk.py": "publicacao canonica",
    "liceu_boundary_check.py": "conformidade estatica de fronteira",
}


def verificar_pacote(diretorio: str) -> Resultado:
    """R00 — roda ANTES de tudo. Um pacote incompleto nao e um pacote."""
    import os
    r = Resultado()
    faltando = [(f, p) for f, p in ARTIFACTS_GOVERNADOS.items()
                if not os.path.exists(os.path.join(diretorio, f))]
    for f, papel in faltando:
        r.add("R00", ERRO, f"artifact governado ausente: {f}", f"papel: {papel}")
    if not faltando:
        r.ok("R00", f"{len(ARTIFACTS_GOVERNADOS)} artifacts governados presentes")
    sem_ferr = [f for f in FERRAMENTAL
                if not os.path.exists(os.path.join(diretorio, f))]
    if sem_ferr:
        r.add("R00", AVISO, f"ferramental ausente: {sem_ferr}",
              "os gates correspondentes nao podem ser reproduzidos")
    return r


def gerar_manifest(diretorio: str) -> dict:
    """MANIFEST com sha256 de cada peca. Torna o pacote autoverificavel."""
    import os
    m = {}
    for f in list(ARTIFACTS_GOVERNADOS) + list(FERRAMENTAL):
        cam = os.path.join(diretorio, f)
        if os.path.exists(cam):
            with open(cam, "rb") as fh:
                m[f] = hashlib.sha256(fh.read()).hexdigest()
    return m


def verificar(const, prod_reg, contract_reg, event_reg, ledger, hashes) -> Resultado:
    r = Resultado()

    # R0C — a Constituicao precisa concordar consigo mesma. R13 compara a
    # Constituicao com os OUTROS artifacts e nao pegava divergencia interna:
    # meta.versao 1.4.1 convivia com milestone.current_constitution_version 1.3.0.
    mv = str(const["meta"]["versao"])
    ms = const.get("milestone", {})
    cur = ms.get("current_constitution_version")
    if cur is None:
        r.add("R0C", AVISO, "milestone.current_constitution_version ausente")
    elif str(cur) != mv:
        r.add("R0C", ERRO,
              f"Constituicao inconsistente consigo mesma: meta.versao={mv} "
              f"mas milestone.current_constitution_version={cur}")
    else:
        base = ms.get("M1_CONSTITUTION_DEFINITION", {}).get(
            "baseline_constitution_version")
        r.ok("R0C", f"Constituicao autoconsistente (corrente {mv}; "
                    f"baseline historico M1 {base})")

    produtores = prod_reg["producers"]
    # Registry 2.0.0: contract_id -> contract_version -> definicao.
    # `contratos` achatado como (cid, versao) -> definicao para as regras que
    # operam sobre definicoes; `versoes_por_id` para as que operam sobre identidade.
    _raw = contract_reg["contracts"]
    versoes_por_id = {cid: dict(vs) for cid, vs in _raw.items()}
    contratos = {cid: vs[max(vs, key=lambda v: [int(x) for x in v.split(".")])]
                 for cid, vs in _raw.items()}
    todas_versoes = [(cid, v, d) for cid, vs in _raw.items() for v, d in vs.items()]
    eventos = event_reg["events"]
    ownership = {k: v for k, v in const["global"]["event_ownership"].items()
                 if isinstance(v, dict) and "authoritative_owner" in v}

    # R01 — 15 producers SOBERANOS, exatamente um por monolito.
    #
    # liceu.authority nao e monolito: e CLASSE de autoridade do control plane
    # (producer_kind=AUTHORITY_CONTROL_PLANE). Ela produz fatos de autoridade e
    # governanca, e nao possui estado de dominio. Conta-la como monolito
    # significaria dar a ela soberania de dominio, que a Constituicao nega.
    monos = const["monolitos"]
    soberanos = {k: v for k, v in produtores.items()
                 if v.get("producer_kind") != "AUTHORITY_CONTROL_PLANE"}
    classes = {k: v for k, v in produtores.items()
               if v.get("producer_kind") == "AUTHORITY_CONTROL_PLANE"}
    if len(soberanos) != len(monos):
        r.add("R01", ERRO,
              f"{len(soberanos)} producers soberanos para {len(monos)} monolitos")
    else:
        r.ok("R01", f"{len(soberanos)} producer_id soberanos, um por monolito"
                    + (f" + {len(classes)} classe(s) de autoridade" if classes else ""))

    # R01B — a classe de autoridade nao pode ter estado de dominio
    for cid, cv in classes.items():
        caps = cv.get("capabilities") or {}
        if caps.get("may_decide") or caps.get("may_execute"):
            r.add("R01B", ERRO,
                  f"{cid}: classe de autoridade nao pode ter may_decide nem "
                  f"may_execute — isso seria estado de dominio")
        papeis = [i.get("authority_role") for i in (cv.get("instances") or [])]
        if "WITNESS" in papeis and "ACTIVE" in papeis and "SUCCESSOR" in papeis:
            r.ok("R01B", f"{cid}: ACTIVE, SUCCESSOR e WITNESS declarados")
        else:
            r.add("R01B", ERRO,
                  f"{cid}: instancias devem declarar ACTIVE, SUCCESSOR e WITNESS; "
                  f"encontrado {papeis}")
    chaves = [v.get("canonical_key") for v in produtores.values()]
    dup = {k for k in chaves if chaves.count(k) > 1}
    if dup:
        r.add("R01", ERRO, f"canonical_key duplicada: {sorted(dup)}")

    # R02 — formato canonico, sem geografia
    ruins = [p for p in produtores if not PRODUCER_ID.match(p)]
    geo = [p for p in produtores if GEOGRAFIA.search(p)]
    if ruins:
        r.add("R02", ERRO, f"producer_id fora do padrao: {ruins}")
    elif geo:
        r.add("R02", ERRO,
              f"producer_id carrega geografia: {geo}",
              "localizacao pertence a federation_id/node_id/scope, nao a identidade")
    else:
        r.ok("R02", "producer_id canonico e independente de geografia")

    # R03/R04 — owner e allowed_producers resolvem
    faltando = set()
    for ev, decl in ownership.items():
        if decl["authoritative_owner"] not in produtores:
            faltando.add((ev, decl["authoritative_owner"], "owner"))
        for ap in decl.get("allowed_producers", []):
            if ap not in produtores:
                faltando.add((ev, ap, "allowed_producer"))
    for cid, v, d in todas_versoes:
        if d["owner"] not in produtores:
            faltando.add((f"{cid}@{v}", d["owner"], "owner"))
        for ap in d.get("allowed_producers", []):
            if ap not in produtores:
                faltando.add((f"{cid}@{v}", ap, "allowed_producer"))
    if faltando:
        for o, p, t in sorted(faltando):
            r.add("R03/R04", ERRO, f"{t} nao resolve: {p}", f"em {o}")
    else:
        r.ok("R03/R04", "todo owner e allowed_producer resolve no Producer Registry")

    # R05/R06 — contract_id resolve e version bate
    prob = []
    for ev, e in eventos.items():
        cid, cv = e.get("contract_id"), e.get("contract_version")
        if cid is None:
            prob.append((ev, "contract_id nulo"))
            continue
        if cid not in contratos:
            prob.append((ev, f"contract_id nao resolve: {cid}"))
            continue
        if str(cv) not in versoes_por_id[cid]:
            prob.append((ev, f"version {cv} nao existe para {cid}; "
                             f"conhecidas: {sorted(versoes_por_id[cid])}"))
        elif versoes_por_id[cid][str(cv)].get("status") == "RETIRED":
            prob.append((ev, f"{cid}@{cv} esta RETIRED e nao aceita publicacao nova"))
    for ev, m in prob:
        r.add("R05/R06", ERRO, m, f"evento {ev}")
    if not prob:
        r.ok("R05/R06", f"{len(eventos)} eventos com contract_id e version resolvidos")

    # R07 — event_type <-> contrato nos dois sentidos
    ida = {ev: eventos[ev].get("contract_id") for ev in eventos}
    volta = {ct["event_type"]: cid for cid, ct in contratos.items()}
    incoerente = [ev for ev, cid in ida.items() if volta.get(ev) != cid]
    orfaos_ct = [cid for cid, ct in contratos.items() if ct["event_type"] not in eventos]
    if incoerente:
        r.add("R07", ERRO, f"mapeamento inconsistente: {incoerente}")
    if orfaos_ct:
        r.add("R07", AVISO, f"contrato sem evento no registry: {orfaos_ct}")
    if not incoerente and not orfaos_ct:
        r.ok("R07", "event_type <-> contract_id consistente nos dois sentidos")

    # R08 — SemVer estrito
    mal = [f"{cid}@{v}" for cid, v, d in todas_versoes
           if not SEMVER.match(str(v)) or str(d.get("contract_version")) != str(v)]
    if mal:
        r.add("R08", ERRO, f"contract_version fora de SemVer: {mal}",
              "invalidos por politica: v1, 1.0, latest, vazio")
    else:
        r.ok("R08", f"{len(todas_versoes)} versoes em SemVer estrito e chave == campo")

    # R09 — payload_schema resolve
    sem = [f"{cid}@{v}" for cid, v, d in todas_versoes
           if not isinstance(d.get("payload_schema"), dict)]
    refs_ruins = []
    for ev, e in eventos.items():
        ref = e.get("payload_schema")
        if isinstance(ref, str) and "#/contracts/" in ref:
            alvo = ref.split("#/contracts/")[1].split("/")[0]
            if alvo not in contratos:
                refs_ruins.append((ev, ref))
    if sem:
        r.add("R09", ERRO, f"contrato sem payload_schema: {sem}")
    for ev, ref in refs_ruins:
        r.add("R09", ERRO, f"payload_schema nao resolve: {ref}", f"evento {ev}")
    if not sem and not refs_ruins:
        r.ok("R09", "todo payload_schema resolve")

    # R10 — lineage sem conflito
    conflitos = []
    for cid, v, d in todas_versoes:
        req = set(d.get("required_envelope_fields") or [])
        forb = set((d.get("forbidden_envelope_fields") or {}).keys())
        both = req & forb
        if both:
            conflitos.append((f"{cid}@{v}", sorted(both)))
    for cid, campos in conflitos:
        r.add("R10", ERRO, f"campo exigido E proibido em {cid}: {campos}")
    if not conflitos:
        r.ok("R10", "nenhum campo simultaneamente exigido e proibido")

    # R11 — cadeia causal minima completa e ordenada
    cadeia = const["minimum_federated_causal_thread"]["cadeia"]
    faltam = [e for e in cadeia if e not in eventos]
    # R11 depende de R05/R06: sem contract_id resolvido nao ha o que ordenar.
    # Degradar com mensagem, nunca explodir.
    nao_resolve = [e for e in cadeia if e in eventos and
                   str(eventos[e].get("contract_version"))
                   not in (versoes_por_id.get(eventos[e].get("contract_id")) or {})]
    if faltam:
        r.add("R11", ERRO, f"elo da cadeia minima fora do Event Registry: {faltam}")
    elif nao_resolve:
        r.add("R11", ERRO,
              f"elo com contract_id irresolvivel: {nao_resolve}",
              "corrigir R05/R06 antes de avaliar a ordem da cadeia")
    else:
        pos = [versoes_por_id[eventos[e]["contract_id"]]
               [str(eventos[e]["contract_version"])]["posicao_na_cadeia"] for e in cadeia]
        if pos != sorted(pos) or pos != list(range(1, len(cadeia) + 1)):
            r.add("R11", ERRO, f"posicao_na_cadeia inconsistente: {pos}")
        else:
            r.ok("R11", f"cadeia causal minima completa e ordenada ({len(cadeia)} elos)")

        # a separacao de autoridade deve ser monotonica ao longo da cadeia:
        # cada elo pode emitir o que o anterior nao podia, nunca o contrario
        acumulado: set[str] = set()
        for i, e in enumerate(cadeia, 1):
            _vs = versoes_por_id.get(eventos[e].get("contract_id")) or {}
            ct = _vs.get(str(eventos[e].get("contract_version")))
            if ct is None:
                continue
            forb = set((ct.get("forbidden_envelope_fields") or {}).keys())
            req = set(ct.get("required_envelope_fields") or [])
            regressao = acumulado & forb
            if regressao and i > 1:
                r.add("R11", AVISO,
                      f"elo {i} ({e}) proibe campo ja exigido a montante: {sorted(regressao)}",
                      "esperado quando o campo pertence a etapa anterior e nao se propaga")
            acumulado |= req

    # R12 — capacidades coerentes com o plano
    incoer = []
    for k, m in monos.items():
        pid = produtores.get(
            const["global"]["canonical_producer_ids"]["registro"][k]["producer_id"], {})
        cap = pid.get("capabilities", {})
        plano = pid.get("authority_class", "")
        if "Authority Plane" in plano and not cap.get("may_authorize"):
            incoer.append(f"{k}: Authority Plane sem may_authorize")
        if "Authority Plane" in plano and cap.get("may_execute"):
            incoer.append(f"{k}: Authority Plane com may_execute (autoridade + execucao)")
        if "Cognition Plane" in plano and cap.get("may_authorize"):
            incoer.append(f"{k}: Cognition Plane com may_authorize (recomenda != autoriza)")
    for m in incoer:
        r.add("R12", ERRO, m)
    if not incoer:
        r.ok("R12", "capacidades coerentes com o plano de autoridade")

    # R13A-D — lineage constitucional de TODO artifact governado.
    # Antes so comparava quem declarava hash; quem nao declarava passava
    # em silencio, que e o pior comportamento possivel num verificador.
    ref_sha = hashes["constitution_sha256"]
    ref_ver = str(const["meta"]["versao"])
    falhas13 = []
    for nome, meta in hashes["governados"].items():
        ver = meta.get("constitution_version")
        sha = meta.get("constitution_sha256")
        compat = meta.get("constitution_compatibility")
        if ver is None:
            falhas13.append(("R13A", nome, "nao declara constitution_version"))
        if sha is None:
            falhas13.append(("R13B", nome, "nao declara constitution_sha256"))
        if sha and sha != ref_sha:
            falhas13.append(("R13C", nome,
                             f"hash {sha[:16]}... != {ref_sha[:16]}... fornecido"))
        if ver and str(ver) != ref_ver and not compat:
            falhas13.append(("R13D", nome,
                             f"versao {ver} != {ref_ver} sem declaracao "
                             f"explicita de compatibilidade"))
    for regra, nome, msg in falhas13:
        r.add(regra, ERRO, f"{nome}: {msg}")
    if not falhas13:
        r.ok("R13A-D", f"{len(hashes['governados'])} artifacts governados "
                       f"com lineage constitucional completo")

    return r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--constitution", default="liceu_constitution.yaml")
    ap.add_argument("--producers", default="liceu_producer_registry.yaml")
    ap.add_argument("--contracts", default="liceu_contract_registry.yaml")
    ap.add_argument("--events", default="liceu_event_registry.yaml")
    ap.add_argument("--ledger", default="liceu_event_reconciliation_ledger.yaml")
    ap.add_argument("--json")
    ap.add_argument("--package-dir", default=".",
                    help="diretorio do pacote a verificar (R00)")
    ap.add_argument("--write-manifest", metavar="ARQ",
                    help="gera MANIFEST com sha256 de cada peca")
    a = ap.parse_args()

    # --package-dir precisa resolver TAMBEM os caminhos dos artifacts, nao so
    # o R00. Sem isto, rodar de um cwd diferente do pacote (o caso do CI, que
    # executa da raiz do repo com o pacote em .liceu/) quebra com
    # FileNotFoundError. Achado pelo teste de shell do workflow.
    import os as _os
    if a.package_dir and a.package_dir != ".":
        for campo in ("constitution", "producers", "contracts", "events", "ledger"):
            v = getattr(a, campo)
            if not _os.path.isabs(v) and not _os.path.exists(v):
                setattr(a, campo, _os.path.join(a.package_dir, v))

    import yaml

    def carregar(p):
        with open(p, "rb") as f:
            b = f.read()
        return yaml.safe_load(b), hashlib.sha256(b).hexdigest()

    const, csha = carregar(a.constitution)
    prod, _ = carregar(a.producers)
    ctr, ctsha = carregar(a.contracts)
    evr, _ = carregar(a.events)
    try:
        led, _ = carregar(a.ledger)
    except OSError:
        led = {"meta": {}}

    hashes = {
        "constitution_sha256": csha,
        "contract_registry_sha256": ctsha,
        # TODO artifact governado entra aqui. Ausencia de lineage e ERRO,
        # nunca omissao silenciosa.
        "governados": {
            "producer_registry": prod.get("meta", {}),
            "contract_registry": ctr.get("meta", {}),
            "event_registry": evr.get("meta", {}),
            "reconciliation_ledger": led.get("meta", {}),
        },
    }

    if a.write_manifest:
        man = gerar_manifest(a.package_dir)
        with open(a.write_manifest, "w", encoding="utf-8") as f:
            f.write("# LICEU 6.0 — MANIFEST do pacote de protocolo\n")
            f.write("# Verifique com: sha256sum -c MANIFEST\n")
            for nome, h in sorted(man.items()):
                f.write(f"{h}  {nome}\n")
        print(f"MANIFEST gravado: {a.write_manifest} ({len(man)} pecas)")

    print(f"Registry Consistency Checker v{CHECKER_VERSION}")
    print(f"constituicao v{const['meta']['versao']} ({csha[:16]})\n")

    # R00 primeiro: nao adianta verificar coerencia de um pacote incompleto
    r0 = verificar_pacote(a.package_dir)
    r = verificar(const, prod, ctr, evr, led, hashes)
    r.itens = r0.itens + r.itens

    for regra, nivel, msg, det in r.itens:
        marca = {"OK": "OK   ", ERRO: "ERRO ", AVISO: "AVISO"}[nivel]
        print(f"  [{marca}] {regra:9} {msg}")
        if det:
            print(f"                     {det}")

    print(f"\n{len(r.erros)} erro(s), {len(r.avisos)} aviso(s)")

    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({
                "artifact_type": "REGISTRY_CONSISTENCY",
                "lineage": {
                    "constitution_version": const["meta"]["versao"],
                    "constitution_sha256": csha,
                    "contract_registry_sha256": ctsha,
                    "registry_checker_version": CHECKER_VERSION,
                    "timestamp": datetime.datetime.now(
                        datetime.timezone.utc).isoformat(),
                },
                "erros": len(r.erros),
                "avisos": len(r.avisos),
                "itens": [{"regra": a_, "nivel": b_, "mensagem": c_, "detalhe": d_}
                          for a_, b_, c_, d_ in r.itens],
            }, f, ensure_ascii=False, indent=2)
        print(f"Artifact: {a.json}")

    return 1 if r.erros else 0


if __name__ == "__main__":
    sys.exit(main())
