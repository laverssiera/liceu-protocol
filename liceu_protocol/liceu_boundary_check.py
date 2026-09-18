#!/usr/bin/env python3
"""
LICEU 6.0 — Constitutional Static Conformance Checker
=====================================================

ATENCAO DE ESCOPO: este verificador prova CONFORMIDADE CONSTITUCIONAL ESTATICA.
Ele NAO prova runtime, transicao de autoridade, soberania de estado, topologia
de eventos, completude produtor/consumidor, replay, idempotencia nem lineage
E2E. E um gate ADICIONAL, jamais substituto dos gates de certificacao W88/W89.

Gera o status real de cada monolito A PARTIR DO CODIGO, em vez de manter
uma tabela de status a mao.

Codifica as regras dos documentos de arquitetura como verificacoes
executaveis:

  - as 15 proibicoes de dominio ("o que NAO deve fazer")
  - antipadrao 1: monolito A altera diretamente banco/estado de B
  - antipadrao 2: dado ausente -> inventar valor -> seguir pipeline
  - conformidade do envelope canonico (contract_id/contract_version/artifact_id)
  - higiene de repositorio (artefatos de build, segredos, caminhos malformados)

MODOS DE USO

  # CI, dentro de um repositorio (falha o build se houver violacao)
  python3 liceu_boundary_check.py --repo . --monolith archimedes

  # Auditoria do ecossistema (varios repos clonados lado a lado)
  python3 liceu_boundary_check.py --root /caminho/dos/clones --table

  # Saida JSON para dashboard/artifact
  python3 liceu_boundary_check.py --root . --json status.json

CODIGOS DE SAIDA
  0 = sem violacao de severidade >= --fail-on
  1 = violacao encontrada
  2 = erro de uso
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field, asdict

# ---------------------------------------------------------------------------
# Severidades
# ---------------------------------------------------------------------------

CRITICO = "CRITICO"   # viola a arquitetura de forma que corrompe dado ou autoridade
ALTO = "ALTO"         # viola fronteira de dominio declarada
MEDIO = "MEDIO"       # divergencia de contrato que degrada silenciosamente
BAIXO = "BAIXO"       # higiene

ORDEM_SEVERIDADE = {CRITICO: 0, ALTO: 1, MEDIO: 2, BAIXO: 3}

CHECKER_VERSION = "1.1.0"

# V1.1 (3) — politica de severidade por contexto
PERFIS = {"development": CRITICO, "pull_request": ALTO, "certification": MEDIO}


@dataclass
class Achado:
    regra: str
    severidade: str
    descricao: str
    arquivos: list[str] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.arquivos)


# ---------------------------------------------------------------------------
# Definicao dos 15 monolitos
#
# `proibido`: (rotulo, regex sobre o CAMINHO do arquivo)
#   Deriva da coluna "O que NAO deve fazer" da tabela de papeis.
# `aliases`: nomes de diretorio/repositorio que identificam o monolito.
# ---------------------------------------------------------------------------

MONOLITOS: dict[str, dict] = {
    "core": {
        "nome": "LICEU CORE",
        "wave": "W88",
        "aliases": ["liceu_6.0_construtora_virtual", "liceu-core", "repo"],
        "dono_do_event_store": True,
        "proibido": [
            ("engenharia/BIM", r"(construction|engenharia|arquitetura|bim_engine|viabilidade)"),
            ("planejamento territorial", r"(territorial|planning_engine|where_to_build)"),
            ("procurement", r"(procurement|supplier|fornecedor)"),
        ],
    },
    "archimedes": {
        "nome": "ARCHIMEDES",
        "wave": "W89",
        "aliases": ["archimedes", "arquimedes"],
        "proibido": [
            ("BIM executivo", r"(bim_model|ifc_export|projeto_executivo)"),
            ("BOQ/WBS executivo", r"(\bboq\b|\bwbs\b)"),
            ("aprovacao financeira", r"(funding|financiamento|aprovacao_financeira)"),
            ("aprovacao juridica", r"(legal_approval|aprovacao_juridica)"),
        ],
    },
    "cefeida": {
        "nome": "CEFEIDA / 3C273",
        "wave": "W90",
        "aliases": ["3c273", "cefeida"],
        "proibido": [
            ("motor de decisao", r"(decision_engine|decision_maker|john_decision)"),
            ("autorizacao", r"(authoriz|approval_engine)"),
        ],
    },
    "john": {
        "nome": "JOHN BRASILEIRO",
        "wave": "W91",
        "aliases": ["john-brasileiro", "john_brasileiro", "john"],
        "proibido": [
            ("autoexecucao/autoaprovacao", r"(self_approv|auto_authoriz|self_authoriz)"),
        ],
    },
    "anchor": {
        "nome": "ANCHOR",
        "wave": "W92",
        "aliases": ["anchor.os", "anchor", "anchors"],
        "proibido": [
            ("execucao de dominio tecnico", r"(maintenance_service|asset_service|precon)"),
        ],
    },
    "opera": {
        "nome": "OPERA",
        "wave": "W93",
        "aliases": ["opera-es", "opera"],
        "proibido": [
            ("engenharia propria", r"(bim_model|structural_calc|ifc_parser)"),
            ("autoaprovacao", r"(self_approv|auto_authoriz)"),
        ],
    },
    "bim": {
        "nome": "BIM.ARQ.ENG",
        "wave": "W94",
        "aliases": ["bim.arq.eng", "bimarqeng", "bim"],
        "proibido": [
            ("financiamento/investidores", r"(investor|funding|financiamento)"),
            ("regulacao/compliance", r"(compliance|regulat|juridic)"),
        ],
    },
    "fornecedores": {
        "nome": "FORNECEDORES",
        "wave": "W95",
        "aliases": ["fornecedores"],
        "proibido": [
            ("engenharia propria", r"(structural_calc|bim_model|calculo_estrutural)"),
            ("politica financeira", r"(funding_policy|capital_structure)"),
        ],
    },
    "econotech": {
        "nome": "ECONOTECH",
        "wave": "W96",
        "aliases": ["econo.tech", "econotech", "econo"],
        "proibido": [
            ("capital/investimento (e do CEA)", r"(investment|funding|treasury|capital_alloc)"),
            ("cognicao (e do JOHN)", r"(/john/|john_|_john)"),
        ],
    },
    "cea": {
        "nome": "CEA INVESTIMENTOS",
        "wave": "W97",
        "aliases": ["cea-investimentos", "cea"],
        "proibido": [
            ("compliance juridico (e do JURIDICOTECH)", r"(compliance|legal_|juridic)"),
        ],
    },
    "juridicotech": {
        "nome": "JURIDICOTECH",
        "wave": "W98",
        "aliases": ["juridico-tech", "juridicotech", "juridico"],
        "proibido": [
            ("redesenho tecnico do ativo", r"(bim_model|structural_calc)"),
            ("viabilidade financeira", r"(funding_structure|capital_alloc)"),
        ],
    },
    "gamemkt": {
        "nome": "GAME MKT",
        "wave": "P15",
        "aliases": ["game-mkt", "gamemkt"],
        "proibido": [
            ("economia/capital", r"(economic_impact|capital_alloc|funding)"),
            ("cognicao", r"(decision_engine|john_)"),
        ],
    },
    "hub": {
        "nome": "HUB BACKOFFICE",
        "wave": "W99",
        "aliases": ["hub-backofice", "hub-backoffice", "hub"],
        "proibido": [
            ("reimplementa outro monolito", r"^(archimedes|juridicotech|cefeida|opera|bim|cea)/"),
        ],
    },
    "academia": {
        "nome": "ACADEMIA DO SABER",
        "wave": "W100",
        "aliases": ["academia-do-saber", "academia", "saber"],
        "proibido": [
            ("autoridade operacional", r"(governance/|federation-authority|authority_)"),
        ],
    },
    "ped": {
        "nome": "P&D.IA",
        "wave": "transversal",
        "aliases": ["p-d-liceu", "ped", "p&d"],
        "proibido": [
            ("promocao direta a producao", r"(auto_promote|direct_to_prod)"),
        ],
    },
}

# ---------------------------------------------------------------------------
# Verificacoes globais
# ---------------------------------------------------------------------------

# Antipadrao 1 — acoplamento direto ao banco de outro dominio
RE_DB_CANONICO = re.compile(
    r"(liceu_core_os|FROM\s+public\.events|events_store\s*\()", re.IGNORECASE
)

# Antipadrao 2 — dado ausente vira valor inventado
# NAO usar "simulacao": e palavra de dominio (scenario engine, digital twin).
# Só marcadores inequivocos de implementacao substituta.
RE_MOCK_PRODUCAO = re.compile(
    r"\bmock(ad[ao]|ed)?\b|\bplaceholder\b|para\s+demonstra[cç][aã]o|"
    r"fins\s+l[oó]gicos|substitua\s+por|em\s+produ[cç][aã]o\s+usar",
    re.IGNORECASE,
)

# Sinal forte: acesso a banco/rede comentado. E o padrao "loga sucesso e nao
# persiste" do event_store_pg.py do CORE.
RE_IO_COMENTADO = re.compile(
    r"^\s*#\s*(self\.conn|conn\s*=|cur\.execute|cursor\.execute|"
    r"import\s+psycopg2|from\s+psycopg2|\.commit\(\)|await\s+)",
    re.MULTILINE,
)
# So conta como violacao o default que carrega CREDENCIAL embutida ou que
# aponta para o event store canonico. Default de servico local em dev nao e.
RE_FALLBACK_CREDENCIAL = re.compile(
    r"getenv\([^)]{0,80}[,)]\s*[\"'][^\"']*"
    r"(://[^\"'/@]+:[^\"'/@]+@|liceu_core_os|CANONICAL_EVENT_STORE)",
    re.IGNORECASE,
)

# Campos que o servidor canonico realmente aceita
CAMPOS_ENVELOPE_VALIDOS = {
    "event_type", "source", "payload", "event_id", "source_event_id",
    "trace_id", "parent_event_id", "causation_id", "decision_id",
    "governance_decision_id", "execution_id", "artifact_id", "scope",
    "producer", "contract_id", "contract_version",
}
CAMPOS_ENVELOPE_OBRIGATORIOS = {"contract_id", "contract_version", "artifact_id"}

# Higiene
RE_ARTEFATO_BUILD = re.compile(r"(^|/)(node_modules/|__pycache__/)|\.pyc$|\.db$")
RE_SEGREDO = re.compile(r"(^|/)\.env$|\.pem$|\.key$|(^|/)secrets?\.ya?ml$")
# .env.example / sealedsecret sao os padroes CORRETOS — nunca sinalizar.
RE_SEGREDO_OK = re.compile(r"\.example$|\.sample$|\.template$|sealedsecret", re.IGNORECASE)
RE_ARQUIVO_TESTE = re.compile(r"(^|/)(tests?|spec)/|(^|/)test_|_test\.(py|ts|js)$|\.spec\.")


def caminho_malformado(p: str) -> bool:
    """Espacos no inicio/fim de qualquer componente. NAO trata pontuacao:
    `(app)` do Next.js App Router e sintaxe valida."""
    return any(c != c.strip() or "  " in c for c in p.split("/"))


# ---------------------------------------------------------------------------
# Motor
# ---------------------------------------------------------------------------

def arquivos_rastreados(repo: str) -> list[str]:
    r = subprocess.run(
        ["git", "-C", repo, "ls-files", "-z"], capture_output=True, text=True
    )
    if r.returncode != 0:
        return []
    return [p for p in r.stdout.split("\0") if p]


def ler(repo: str, rel: str, limite: int = 400_000) -> str:
    try:
        with open(os.path.join(repo, rel), "r", encoding="utf-8", errors="ignore") as f:
            return f.read(limite)
    except OSError:
        return ""


CONSTITUICAO_META: dict = {}


def carregar_constituicao(caminho: str) -> bool:
    """Substitui MONOLITOS pelas regras da constituicao. Regras marcadas
    [PENDENTE] sao IGNORADAS ate serem resolvidas por decisao humana."""
    try:
        import yaml
    except ImportError:
        print("[aviso] pyyaml ausente; usando regras embutidas", file=sys.stderr)
        return False
    try:
        with open(caminho, encoding="utf-8") as f:
            c = yaml.safe_load(f)
    except OSError:
        return False

    import hashlib
    with open(caminho, "rb") as fb:
        chash_full = hashlib.sha256(fb.read()).hexdigest()
    chash = chash_full[:16]   # display apenas
    meta = c.get("meta", {})
    reg = c.get("global", {}).get("canonical_producer_ids", {}).get("registro", {})
    CONSTITUICAO_META.update({
        "constitution_version": meta.get("versao"),
        "constitution_status": meta.get("status"),
        # Evidencia criptografica persistida NAO deve ser truncada:
        # DISPLAY -> short | CERTIFICATION -> full
        "constitution_sha256": chash_full,
        "constitution_hash_short": chash,
        "checker_version": CHECKER_VERSION,
    })

    novo = {}
    for chave, m in c.get("monolitos", {}).items():
        novo[chave] = {
            "nome": m.get("canonical_name", chave),
            "wave": m.get("wave", "?"),
            "producer_id": reg.get(chave, {}).get("producer_id"),
            "aliases": [m.get("repository", chave).lower(), chave],
            "dono_do_event_store": chave == "core",
            "proibido": [(f["label"], f["pattern"]) for f in m.get("forbidden", [])],
            # V1.1 (4) — metadados de autoridade vindos do YAML
            "may_decide": m.get("may_decide", []),
            "may_authorize": m.get("may_authorize", []),
            "may_execute": m.get("may_execute", []),
            "state_ownership": m.get("state_ownership", []),
        }
    if novo:
        MONOLITOS.clear()
        MONOLITOS.update(novo)

    pend = c.get("pendencias", []) or []
    adrs = c.get("adrs_pendentes", []) or []
    print(f"[constituicao] v{meta.get('versao','?')} {meta.get('status','')} "
          f"(sha {chash}) | checker v{CHECKER_VERSION}")
    if pend:
        print(f"  {len(pend)} pendencia(s) aberta(s); regras [PENDENTE] nao sao exigidas:")
        for x in pend:
            print(f"    {x['id']}  {x['tema']}")
    for x in adrs:
        print(f"  ADR aberta: {x['id']} — {x['tema']}")
    return True


def _norm(x: str) -> str:
    return re.sub(r"[^a-z0-9]", "", x.lower())


def identificar_monolito(repo: str) -> str | None:
    base = _norm(os.path.basename(os.path.abspath(repo)))
    melhor, tam = None, 0
    for chave, m in MONOLITOS.items():
        for a in m["aliases"]:
            na = _norm(a)
            # casa nos dois sentidos: o dir pode ser prefixo do repo canonico
            if na and (na in base or base in na) and len(na) > tam:
                melhor, tam = chave, len(na)
    return melhor


def verificar(repo: str, chave: str | None) -> tuple[str, list[Achado]]:
    caminhos = arquivos_rastreados(repo)
    if not caminhos:
        return chave or "?", [Achado("repo-vazio", BAIXO, "Nenhum arquivo rastreado")]

    m = MONOLITOS.get(chave or "", {})
    achados: list[Achado] = []
    fontes = [p for p in caminhos if p.endswith((".py", ".ts", ".js", ".tsx", ".jsx"))]
    fontes_prod = [p for p in fontes if not RE_ARQUIVO_TESTE.search(p)]

    # --- Fronteira de dominio -------------------------------------------
    for rotulo, padrao in m.get("proibido", []):
        rx = re.compile(padrao, re.IGNORECASE)
        hits = [p for p in caminhos if rx.search(p)]
        if hits:
            achados.append(Achado(
                f"fronteira: {rotulo}", ALTO,
                f"{m.get('nome', chave)} nao deve conter {rotulo}",
                sorted(hits)[:25],
            ))

    # --- Antipadrao 1: acoplamento direto ao banco canonico --------------
    if not m.get("dono_do_event_store"):
        hits = [p for p in fontes_prod if RE_DB_CANONICO.search(ler(repo, p))]
        if hits:
            achados.append(Achado(
                "antipadrao: DB coupling direto", CRITICO,
                "Acesso direto ao event store canonico contorna validacao de "
                "lineage do FederationEventPublishRequest",
                sorted(hits)[:25],
            ))

    # --- Antipadrao 2: valor inventado em caminho de producao ------------
    mocks, fallbacks = [], []
    for p in fontes_prod:
        txt = ler(repo, p)
        if not txt:
            continue
        if RE_MOCK_PRODUCAO.search(txt) and RE_IO_COMENTADO.search(txt):
            mocks.append(p)
        if RE_FALLBACK_CREDENCIAL.search(txt):
            fallbacks.append(p)
    if mocks:
        achados.append(Achado(
            "antipadrao: mock em producao", CRITICO,
            "Marcado como mock E com I/O comentado: loga sucesso sem persistir. "
            "E o antipadrao 'dado ausente vira valor inventado'",
            sorted(mocks)[:25],
        ))
    if fallbacks:
        achados.append(Achado(
            "antipadrao: fallback silencioso", ALTO,
            "Default para localhost/credencial padrao quando a variavel falta. "
            "Deve falhar fechado (fail-closed)",
            sorted(fallbacks)[:25],
        ))

    # --- Conformidade do envelope canonico -------------------------------
    publicadores = [p for p in fontes_prod
                    if "/federation/events/publish" in ler(repo, p)]
    for p in publicadores:
        txt = ler(repo, p)
        campos = set(re.findall(r"[\"']([a-z_]+)[\"']\s*:", txt))
        campos |= set(re.findall(r"\b([a-z_]+)\s*=", txt))
        invalidos = {c for c in ("contract", "meta", "signature") if c in campos}
        faltando = CAMPOS_ENVELOPE_OBRIGATORIOS - campos
        if invalidos:
            achados.append(Achado(
                "envelope: campo inexistente no schema", MEDIO,
                f"Campos {sorted(invalidos)} nao existem em "
                f"FederationEventPublishRequest e sao descartados silenciosamente",
                [p],
            ))
        if faltando:
            achados.append(Achado(
                "envelope: campo obrigatorio ausente", MEDIO,
                f"Nao define {sorted(faltando)}. Consumidores (CEA, ECONOTECH) "
                f"buscam por artifact_id",
                [p],
            ))

    # --- Higiene ---------------------------------------------------------
    for rotulo, rx, sev, desc in (
        ("higiene: caminho malformado", None, ALTO,
         "Espaco no inicio/fim do nome quebra import, COPY do Docker e clone no Windows"),
        ("higiene: artefato de build", RE_ARTEFATO_BUILD, BAIXO,
         "Artefato de build versionado"),
        ("higiene: segredo versionado", RE_SEGREDO, CRITICO,
         "Arquivo de segredo rastreado (verificar se e SealedSecret ou texto plano)"),
    ):
        hits = ([p for p in caminhos if caminho_malformado(p)] if rx is None
                else [p for p in caminhos
                      if rx.search(p) and not RE_SEGREDO_OK.search(p)])
        if hits:
            achados.append(Achado(rotulo, sev, desc, sorted(hits)[:25]))

    return chave or "?", achados


# ---------------------------------------------------------------------------
# Saida
# ---------------------------------------------------------------------------

def semaforo(achados: list[Achado]) -> str:
    if any(a.severidade == CRITICO for a in achados):
        return "VERMELHO"
    if any(a.severidade == ALTO for a in achados):
        return "AMARELO"
    if achados:
        return "AZUL"
    return "VERDE"


def imprimir_tabela(resultados: dict[str, list[Achado]]) -> None:
    print("\n| Monolito | producer_id | Wave | Conformidade | Crit | Alto | Medio | Baixo | Violacao principal |")
    print("|---|---|---|---|---|---|---|---|")
    for chave, achados in sorted(
        resultados.items(),
        key=lambda kv: (ORDEM_SEVERIDADE[semaforo_sev(kv[1])], kv[0]),
    ):
        m = MONOLITOS.get(chave, {})
        cont = {s: sum(1 for a in achados if a.severidade == s)
                for s in (CRITICO, ALTO, MEDIO, BAIXO)}
        piores = [a for a in achados if a.severidade in (CRITICO, ALTO)]
        principal = piores[0].regra if piores else "—"
        print(f"| {m.get('nome', chave)} | {m.get('producer_id','—')} "
              f"| {m.get('wave','?')} | {semaforo(achados)} "
              f"| {cont[CRITICO]} | {cont[ALTO]} | {cont[MEDIO]} | {cont[BAIXO]} "
              f"| {principal} |")


def semaforo_sev(achados: list[Achado]) -> str:
    s = semaforo(achados)
    return {"VERMELHO": CRITICO, "AMARELO": ALTO, "AZUL": MEDIO, "VERDE": BAIXO}[s]


def imprimir_detalhe(chave: str, achados: list[Achado]) -> None:
    nome = MONOLITOS.get(chave, {}).get("nome", chave)
    print(f"\n{'='*70}\n{nome}  [{semaforo(achados)}]\n{'='*70}")
    if not achados:
        print("  Sem violacoes.")
        return
    for a in sorted(achados, key=lambda x: ORDEM_SEVERIDADE[x.severidade]):
        print(f"\n  [{a.severidade}] {a.regra}  ({a.n} arquivo(s))")
        print(f"    {a.descricao}")
        for f in a.arquivos[:6]:
            print(f"      - {f}")
        if a.n > 6:
            print(f"      ... e mais {a.n - 6}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", help="verificar um repositorio")
    ap.add_argument("--root", help="verificar todos os repositorios sob este diretorio")
    ap.add_argument("--monolith", help="forcar a identidade do monolito")
    ap.add_argument("--table", action="store_true", help="tabela resumida")
    ap.add_argument("--json", metavar="ARQ", help="gravar resultado em JSON")
    ap.add_argument("--constitution", default="liceu_constitution.yaml",
                    help="constituicao canonica (fonte das regras)")
    ap.add_argument("--dev-fallback", action="store_true",
                    help="permite rodar sem constituicao (apenas desenvolvimento)")
    ap.add_argument("--profile", choices=list(PERFIS),
                    help="perfil de severidade: development|pull_request|certification")
    ap.add_argument("--fail-on", default=CRITICO,
                    choices=[CRITICO, ALTO, MEDIO, BAIXO],
                    help="severidade minima que falha o build (padrao: CRITICO)")
    args = ap.parse_args()

    if not args.repo and not args.root:
        ap.error("informe --repo ou --root")

    # V1.1 (1) — constituicao fail-closed. Sem ela, o checker NAO certifica.
    if not carregar_constituicao(args.constitution):
        if args.dev_fallback:
            print(f"[DEV] constituicao nao lida ({args.constitution}); "
                  f"regras embutidas. NAO usar para certificacao.", file=sys.stderr)
        else:
            print(f"ERRO: constituicao nao lida ({args.constitution}). "
                  f"O checker falha fechado. Use --dev-fallback apenas em "
                  f"desenvolvimento.", file=sys.stderr)
            return 1

    if args.profile:
        args.fail_on = PERFIS[args.profile]

    alvos: list[tuple[str, str | None]] = []
    if args.repo:
        alvos.append((args.repo, args.monolith or identificar_monolito(args.repo)))
    else:
        for nome in sorted(os.listdir(args.root)):
            caminho = os.path.join(args.root, nome)
            if os.path.isdir(os.path.join(caminho, ".git")):
                alvos.append((caminho, identificar_monolito(caminho)))

    resultados: dict[str, list[Achado]] = {}
    for caminho, chave in alvos:
        if chave is None:
            print(f"[aviso] monolito nao identificado: {caminho}", file=sys.stderr)
            continue
        k, achados = verificar(caminho, chave)
        resultados[k] = achados

    if args.table:
        imprimir_tabela(resultados)
    else:
        for chave, achados in resultados.items():
            imprimir_detalhe(chave, achados)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            import datetime
            artifact = {
                "artifact_type": "STATIC_CONSTITUTIONAL_CONFORMANCE",
                "lineage": {
                    **CONSTITUICAO_META,
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "fail_on": args.fail_on,
                    "profile": args.profile,
                },
                "monolitos": {
                    k: {
                        "producer_id": MONOLITOS.get(k, {}).get("producer_id"),
                        "static_constitutional_conformance": semaforo(v),
                        "authority": {
                            "may_decide": MONOLITOS.get(k, {}).get("may_decide", []),
                            "may_authorize": MONOLITOS.get(k, {}).get("may_authorize", []),
                            "may_execute": MONOLITOS.get(k, {}).get("may_execute", []),
                        },
                        "achados": [asdict(a) for a in v],
                    }
                    for k, v in resultados.items()
                },
            }
            json.dump(artifact, f, ensure_ascii=False, indent=2)
        print(f"\nJSON gravado em {args.json}")

    limite = ORDEM_SEVERIDADE[args.fail_on]
    violou = any(ORDEM_SEVERIDADE[a.severidade] <= limite
                 for v in resultados.values() for a in v)
    if violou:
        print(f"\nFALHA: violacoes de severidade <= {args.fail_on}", file=sys.stderr)
    return 1 if violou else 0


if __name__ == "__main__":
    sys.exit(main())
