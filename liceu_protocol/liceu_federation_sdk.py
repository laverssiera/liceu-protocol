#!/usr/bin/env python3
"""
LICEU 6.0 — Federation SDK
===========================
Fase P2.3B · versao 0.1.0

A UNICA forma normal de um monolito publicar um fato canonico.

    identidade do produtor
            v
    resolucao do contrato
            v
    construcao do envelope canonico
            v
    conformidade local G1-G5   (falha ANTES da rede)
            v
    payload_hash + envelope_fingerprint
            v
    publish HTTP autenticado -> Event Store canonico do CORE
            v
    propagacao JetStream do MESMO fato

=============================================================================
O QUE O SDK NAO E  (§14 — restricao fundamental)
=============================================================================

O SDK NAO pode virar um CORE embutido.

    SDK      valida, constroi, autentica, publica
    CORE     persiste a verdade canonica, resolve contratos,
             detem a autoridade de identidade

Concretamente, este SDK NUNCA:

  - acessa banco de dados diretamente        (antipadrao 1 da Constituicao)
  - faz fallback silencioso                  (antipadrao 3)
  - assina JWT localmente                    (JWT_SECRET_KEY nunca sai do CORE)
  - mantem registry de contratos proprio como AUTORIDADE
  - cria uma segunda identidade de evento para o NATS

O registry local existe apenas como cache de PRE-VOO: permite falhar rapido,
offline, antes de gastar rede. A autoridade continua sendo o CORE. Em modo
`strict`, o SDK exige que o CORE confirme o contrato antes de publicar.

=============================================================================
INVARIANTES EXTRAIDOS DE IMPLEMENTACOES INTERNAS  (§15)
=============================================================================

  fail-closed        <- liceu.suppliers
                        configuracao federativa ausente -> erro explicito,
                        nunca default para localhost
  envelope canonico  <- liceu.john
                        contract_id + contract_version + artifact_id sempre;
                        fingerprint deterministico

O invariante foi extraido. O codigo de origem nao foi copiado, nem a divida
incidental dos repositorios de origem.

=============================================================================
UM FATO, DOIS CAMINHOS
=============================================================================

HTTP e JetStream nao produzem dois eventos. Produzem o MESMO fato por dois
caminhos. O SDK garante que `event_id`, `envelope_fingerprint` e o lineage
sao identicos nos dois, calculando o envelope UMA vez.

USO
    python3 liceu_federation_sdk.py --self-test
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
import datetime
from dataclasses import dataclass, field
from typing import Any, Callable

SDK_VERSION = "0.4.0"

# Variaveis canonicas. Aliases sao PROIBIDOS: ARCHIMEDES aceitava
# FEDERATION_API_URL / CANONICAL_SERVICE_SECRET, que nenhum outro monolito
# reconhece. Um nome por coisa.
ENV_URL = "CANONICAL_EVENT_STORE_API_URL"
ENV_SECRET = "CANONICAL_EVENT_STORE_API_SECRET"


class FederationError(Exception):
    """Base. Toda falha do SDK e explicita — nunca degradacao silenciosa."""


class ConfigError(FederationError):
    """Configuracao federativa ausente ou incompleta (fail-closed)."""


class ContractError(FederationError):
    """Contrato nao resolve, ou produtor sem autoridade sobre o evento."""


class CollisionError(FederationError):
    """409 do CORE: event_id colidiu com semantica divergente.

    NAO e falha transitoria. Significa que o event_id ja pertence a um fato
    diferente — possivelmente de OUTRO produtor. A correcao e humana.

    O SDK NUNCA resolve isso sozinho. Ver PROIBICOES em publish().
    """

    def __init__(self, mensagem: str, *, event_id: str = "",
                 diverging_fields: list | None = None,
                 conflict_token: str = "", mode: str = "FOREIGN"):
        super().__init__(mensagem)
        self.event_id = event_id
        self.diverging_fields = list(diverging_fields or [])
        self.conflict_token = conflict_token
        self.mode = mode

    def relatorio(self) -> str:
        """Linha unica para log. NAO inclui valor algum do fato alheio."""
        return (f"COLLISION event_id={self.event_id} mode={self.mode} "
                f"diverging={','.join(self.diverging_fields) or '-'} "
                f"token={self.conflict_token or '-'}")


class ReadError(FederationError):
    """Leitura canonica falhou. Fail-closed: nunca degrada para banco local."""


class ConformanceError(FederationError):
    """Envelope reprovado em G1-G5 antes de sair para a rede."""


# ---------------------------------------------------------------------------
# Configuracao — fail-closed, invariante do liceu.suppliers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FederationConfig:
    api_url: str
    api_secret: str
    producer_id: str
    instance_id: str
    scope: str
    strict_contract_resolution: bool = True

    @staticmethod
    def from_env(producer_id: str, scope: str,
                 instance_id: str | None = None) -> "FederationConfig":
        """Le do ambiente. Falha FECHADO: sem default, sem localhost.

        Este metodo e a razao de o SDK existir. Nove dos quinze monolitos
        faziam `os.getenv(X, "http://localhost:...")` — e um deles publicava
        com sucesso aparente contra um endereco que nao era o Event Store.
        """
        faltando = [v for v in (ENV_URL, ENV_SECRET) if not os.getenv(v)]
        if faltando:
            raise ConfigError(
                f"configuracao federativa ausente: {', '.join(faltando)}. "
                f"O SDK falha fechado por decisao constitucional: nao existe "
                f"default para localhost nem credencial embutida."
            )
        for alias in ("FEDERATION_API_URL", "CANONICAL_SERVICE_SECRET"):
            if os.getenv(alias):
                raise ConfigError(
                    f"{alias} e alias proibido. Use {ENV_URL} / {ENV_SECRET}. "
                    f"Aliases criam configuracao que funciona em um monolito "
                    f"e falha em todos os outros."
                )
        if not producer_id.startswith("liceu."):
            raise ConfigError(f"producer_id fora do padrao canonico: {producer_id}")
        return FederationConfig(
            api_url=os.environ[ENV_URL].rstrip("/"),
            api_secret=os.environ[ENV_SECRET],
            producer_id=producer_id,
            # producer_id != instance_id. A localizacao vive aqui, nunca
            # na identidade da autoridade.
            instance_id=instance_id or f"{producer_id}#local",
            scope=scope,
        )


# ---------------------------------------------------------------------------
# Determinismo — invariante do liceu.john
# ---------------------------------------------------------------------------

def canonical_json(obj: Any) -> bytes:
    """Serializacao deterministica. Duas execucoes, mesmo byte, mesmo hash."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def payload_hash(payload: dict) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def envelope_fingerprint(envelope: dict) -> str:
    """Fingerprint sobre o envelope SEM o proprio campo, para ser estavel."""
    base = {k: v for k, v in envelope.items() if k != "envelope_fingerprint"}
    return hashlib.sha256(canonical_json(base)).hexdigest()


# ---------------------------------------------------------------------------
# Resolucao de contrato — cache de pre-voo, NUNCA autoridade
# ---------------------------------------------------------------------------

class ContractResolver:
    """Resolve contratos. A autoridade e o CORE; o registry local so
    antecipa a falha para nao gastar rede com envelope invalido."""

    def __init__(self, contract_registry: dict, http: Callable | None = None):
        self._local = contract_registry.get("contracts", {})
        self._http = http
        self._confirmado: set[str] = set()

    def resolve(self, contract_id: str, cfg: FederationConfig,
                contract_version: str | None = None) -> dict:
        """Resolve (contract_id, contract_version).

        Registry 2.0.0 e indexado por contract_id -> versao -> definicao.
        Sem versao pedida, usa a maior ACTIVE — nunca uma RETIRED.
        """
        versoes = self._local.get(contract_id)
        if versoes is None:
            raise ContractError(f"contract_id nao resolve localmente: {contract_id}")
        if contract_version is not None:
            ct = versoes.get(str(contract_version))
            if ct is None:
                raise ContractError(
                    f"contract_version {contract_version!r} nao existe para "
                    f"{contract_id}; conhecidas: {sorted(versoes)}")
        else:
            ativas = {v: d for v, d in versoes.items() if d.get("status") == "ACTIVE"}
            if not ativas:
                raise ContractError(
                    f"{contract_id} nao tem versao ACTIVE; publicacao nova bloqueada")
            ct = ativas[max(ativas, key=lambda v: [int(x) for x in v.split(".")])]
        if ct.get("status") == "RETIRED":
            raise ContractError(
                f"{contract_id}@{ct['contract_version']} esta RETIRED: "
                f"nao aceita publicacao nova")
        if cfg.strict_contract_resolution and contract_id not in self._confirmado:
            self._confirmar_no_core(contract_id, ct, cfg)
        return ct

    def _confirmar_no_core(self, contract_id: str, ct: dict,
                           cfg: FederationConfig) -> None:
        """Pergunta ao CORE se o contrato existe e bate. O registry local
        jamais substitui essa autoridade."""
        if self._http is None:
            raise ContractError(
                f"strict_contract_resolution exige transporte para confirmar "
                f"{contract_id} no CORE. O registry local e cache, nao autoridade."
            )
        v = ct["contract_version"]
        r = self._http("GET",
                       f"{cfg.api_url}/core-dna/contracts/{contract_id}/{v}",
                       None, cfg)
        if r.get("status") != 200:
            raise ContractError(
                f"CORE nao confirmou {contract_id}@{v} (HTTP {r.get('status')})")
        self._confirmado.add(contract_id)


# ---------------------------------------------------------------------------
# Cliente
# ---------------------------------------------------------------------------

@dataclass
class PublishResult:
    event_id: str
    envelope_fingerprint: str
    http_status: int
    jetstream_subject: str | None
    jetstream_ack: bool
    envelope: dict = field(repr=False, default_factory=dict)


@dataclass
class TypeQueryResult:
    """Resultado de consulta por event_type pelo boundary oficial."""
    event_type: str
    items: list
    total: int
    returned: int
    # O servidor varre 5000 eventos ANTES de filtrar; `total` e pos-filtro,
    # entao a resposta nao revela se houve truncamento a montante.
    truncamento_indetectavel: bool = True


@dataclass
class VerificationResult:
    """Resultado deterministico de verify_persistence.

    NAO compara payload byte a byte: o servidor normaliza campos e descarta os
    que nao estao em FederationEventPublishRequest. Compara identidade e
    contrato, e RECOMPUTA o hash a partir do payload devolvido.
    """
    event_id: str
    persisted: bool
    campos_conferidos: dict = field(default_factory=dict)
    campos_nao_verificaveis: dict = field(default_factory=dict)
    motivo: str = ""


# Campos do LICEU Federation Envelope que o servidor canonico NAO aceita hoje
# (FederationEventPublishRequest). Enviados, sao descartados em silencio —
# mesma classe do campo `contract` do ARCHIMEDES.
CAMPOS_NAO_ACEITOS_PELO_SERVIDOR = {
    "producer_id": "servidor usa `producer`; o SDK mapeia no boundary",
    "payload_hash": "nao persistido; deve ser RECOMPUTADO do payload devolvido",
    "envelope_fingerprint": "nao persistido; nao verificavel server-side",
    "observed_at": "nao persistido",
    "emitted_at": "nao persistido",
}


class FederationClient:
    def __init__(self, cfg: FederationConfig, resolver: ContractResolver,
                 conformance, contract_registry: dict,
                 http: Callable | None = None, jetstream: Callable | None = None):
        self.cfg = cfg
        self.resolver = resolver
        self._conf = conformance          # modulo liceu_conformance
        self._cr = contract_registry
        self._http = http
        self._js = jetstream

    # -- construcao ---------------------------------------------------------
    def build_envelope(self, contract_id: str, payload: dict,
                       artifact_id: str, *, trace_id: str | None = None,
                       lineage: dict | None = None,
                       observed_at: str | None = None) -> dict:
        cfg = self.cfg
        ct = self.resolver.resolve(contract_id, cfg)

        # Autoridade verificada ANTES de construir. G3 tambem revalida, mas
        # falhar aqui produz erro mais claro para quem chama.
        if cfg.producer_id not in ct["allowed_producers"]:
            raise ContractError(
                f"{cfg.producer_id} nao pode produzir {ct['event_type']}; "
                f"dono constitucional e {ct['owner']}")

        agora = datetime.datetime.now(datetime.timezone.utc).isoformat()
        env: dict[str, Any] = {
            "event_id": str(uuid.uuid4()),
            "event_type": ct["event_type"],
            "producer_id": cfg.producer_id,
            "contract_id": contract_id,
            "contract_version": ct["contract_version"],
            "trace_id": trace_id or str(uuid.uuid4()),
            "artifact_id": artifact_id,
            "scope": cfg.scope,
            "payload": payload,
            "payload_hash": payload_hash(payload),
            "emitted_at": agora,
        }
        if observed_at:
            env["observed_at"] = observed_at

        # Lineage: apenas os campos que ESTE produtor pode emitir. O SDK nao
        # deixa o chamador contrabandear um campo de outra etapa.
        proibidos = set((ct.get("forbidden_envelope_fields") or {}).keys())
        for k, v in (lineage or {}).items():
            if k in proibidos:
                raise ConformanceError(
                    f"{cfg.producer_id} nao pode emitir {k} em "
                    f"{ct['event_type']}: "
                    f"{ct['forbidden_envelope_fields'][k].strip().splitlines()[0]}")
            env[k] = v

        env["envelope_fingerprint"] = envelope_fingerprint(env)
        return env

    # -- conformidade local -------------------------------------------------
    def validate(self, envelope: dict) -> None:
        """G1-G5 locais. Reutiliza o Conformance Kit: o SDK NAO reimplementa
        validacao — duas implementacoes divergiriam em algum momento."""
        try:
            self._conf.validar(envelope, self._cr)
        except self._conf.Rejeicao as e:
            raise ConformanceError(str(e)) from None

    # -- leitura canonica ---------------------------------------------------
    def get_event(self, event_id: str) -> dict:
        """Le um fato pelo boundary oficial. Fail-closed.

        NUNCA le banco. NUNCA cai para caminho alternativo. Se o boundary nao
        responde, o resultado e BLOCKED, nao um otimismo.

        O endpoint devolve {"status": "ok", "item": {...}}. Ler o envelope
        inteiro em vez do `item` foi o defeito real do get_event_by_id do
        ECONOTECH, que por isso sempre caia em varredura de 2000 eventos.
        """
        if self._http is None:
            raise ReadError(
                "transporte HTTP ausente. O SDK nao le banco nem usa caminho "
                "alternativo para verificar persistencia."
            )
        r = self._http("GET",
                       f"{self.cfg.api_url}/federation/events/{event_id}",
                       None, self.cfg)
        if r.get("status") != 200:
            raise ReadError(
                f"leitura canonica falhou para {event_id}: HTTP {r.get('status')}"
            )
        corpo = r.get("body") or {}
        item = corpo.get("item")
        if not isinstance(item, dict):
            raise ReadError(
                f"resposta sem `item` para {event_id}. NAO interpretar o envelope "
                f"da resposta como o evento."
            )
        return item

    def get_events_by_type(self, event_type: str, *, limit: int = 1,
                           offset: int = 0) -> "TypeQueryResult":
        """Lista fatos por event_type, do mais recente para o mais antigo.

        Substitui `SELECT ... FROM public.events WHERE event_type = %s
        ORDER BY created_at DESC LIMIT n` sem tocar banco.

        O servidor ordena por created_at DESC em _recent_serialized_events e
        depois filtra, entao items[0] equivale ao LIMIT 1 da query direta.

        LIMITE CONHECIDO DO SERVIDOR: ele varre no maximo 5000 eventos recentes
        ANTES de filtrar por tipo. Se o ecossistema passar de 5000 eventos, um
        fato antigo do tipo pedido fica invisivel — e a resposta NAO permite
        detectar isso, porque `total` ja e o total pos-filtro. E a mesma classe
        do teto de 2000 do ECONOTECH. Por isso TypeQueryResult carrega
        `truncamento_indetectavel=True`: quem consome precisa saber que
        ausencia aqui nao prova inexistencia.
        """
        if self._http is None:
            raise ReadError(
                "transporte HTTP ausente. O SDK nao le banco nem usa caminho "
                "alternativo para consultar por tipo."
            )
        if limit < 1 or limit > 2000:
            raise ReadError(f"limit fora do aceito pelo servidor (1..2000): {limit}")

        url = (f"{self.cfg.api_url}/federation/events/by-type/{event_type}"
               f"?limit={limit}&offset={offset}")
        r = self._http("GET", url, None, self.cfg)
        if r.get("status") != 200:
            raise ReadError(
                f"consulta por tipo falhou para {event_type!r}: HTTP {r.get('status')}")
        corpo = r.get("body") or {}
        itens = corpo.get("items")
        if not isinstance(itens, list):
            raise ReadError(
                f"resposta sem `items` para {event_type!r}. NAO interpretar o "
                f"envelope da resposta como a lista.")
        return TypeQueryResult(
            event_type=event_type, items=itens,
            total=corpo.get("total", len(itens)),
            returned=corpo.get("returned", len(itens)))

    def get_latest_by_type(self, event_type: str) -> dict:
        """O fato mais recente do tipo. Fail-closed se nao houver nenhum.

        Ausencia NAO e sucesso com resultado vazio: e ReadError. Quem precisar
        tratar ausencia como caso valido usa get_events_by_type e inspeciona.
        """
        res = self.get_events_by_type(event_type, limit=1)
        if not res.items:
            raise ReadError(
                f"nenhum fato do tipo {event_type!r} no boundary canonico. "
                f"Ausencia nao prova inexistencia: o servidor varre no maximo "
                f"5000 eventos recentes antes de filtrar.")
        return res.items[0]

    def verify_persistence(self, resultado: "PublishResult") -> VerificationResult:
        """Prova que o fato esta durável no Event Store canonico.

        Substitui a leitura direta de banco. Compara IDENTIDADE e CONTRATO, e
        recomputa o hash do payload devolvido. Nao compara payload byte a byte.
        """
        env = resultado.envelope
        try:
            item = self.get_event(resultado.event_id)
        except ReadError as e:
            return VerificationResult(
                event_id=resultado.event_id, persisted=False,
                motivo=f"BLOCKED: {e}")

        conferidos, divergentes = {}, []
        for campo, esperado in (
            ("event_id", env.get("event_id")),
            ("contract_id", env.get("contract_id")),
            ("contract_version", env.get("contract_version")),
            ("event_type", env.get("event_type")),
            ("artifact_id", env.get("artifact_id")),
        ):
            obtido = item.get(campo)
            ok = obtido == esperado
            conferidos[campo] = ok
            if not ok:
                divergentes.append(f"{campo}: esperado {esperado!r}, obtido {obtido!r}")

        # producer_id do envelope <-> producer do servidor
        obtido_prod = item.get("producer") or item.get("producer_id")
        ok_prod = obtido_prod == env.get("producer_id")
        conferidos["producer"] = ok_prod
        if not ok_prod:
            divergentes.append(
                f"producer: esperado {env.get('producer_id')!r}, obtido {obtido_prod!r}")

        # hash RECOMPUTADO do payload devolvido, nao lido de campo armazenado
        ok_hash = payload_hash(item.get("payload", {})) == env.get("payload_hash")
        conferidos["payload_hash_recomputado"] = ok_hash
        if not ok_hash:
            divergentes.append("payload_hash recomputado nao confere")

        return VerificationResult(
            event_id=resultado.event_id,
            persisted=all(conferidos.values()),
            campos_conferidos=conferidos,
            campos_nao_verificaveis=dict(CAMPOS_NAO_ACEITOS_PELO_SERVIDOR),
            motivo="" if all(conferidos.values()) else "; ".join(divergentes))

    # -- publicacao ---------------------------------------------------------
    def publish(self, contract_id: str, payload: dict, artifact_id: str,
                **kw) -> PublishResult:
        env = self.build_envelope(contract_id, payload, artifact_id, **kw)
        self.validate(env)                       # falha ANTES da rede

        if self._http is None:
            raise ConfigError("transporte HTTP ausente — o SDK nao publica "
                              "por caminho alternativo nem grava localmente")

        # O servidor usa `producer`; o envelope canonico usa `producer_id`.
        # Mapear no boundary evita que o campo seja descartado em silencio.
        corpo = dict(env)
        corpo["producer"] = corpo.get("producer_id")
        r = self._http("POST", f"{self.cfg.api_url}/federation/events/publish",
                       corpo, self.cfg)

        # 409 — colisao de event_id com semantica divergente.
        #
        # PROIBIDO, e o SDK nao faz nada disso:
        #   - reenviar com event_id novo: esconderia o conflito e criaria dois
        #     fatos onde o produtor via um
        #   - retry com backoff: 409 nao e transitorio
        #   - alterar producer_id para obter mais detalhe: e exatamente o ataque
        #     que o modo SELF do CORE precisa impedir
        #   - gravar localmente: P04, BLOCKED e a resposta correta
        if r.get("status") == 409:
            corpo_erro = r.get("body") or {}
            raise CollisionError(
                f"event_id {env['event_id']} colidiu com fato de semantica "
                f"divergente. BLOCKED: a correcao e humana.",
                event_id=corpo_erro.get("event_id") or env["event_id"],
                diverging_fields=corpo_erro.get("diverging_fields"),
                conflict_token=corpo_erro.get("conflict_token", ""),
                mode=("SELF" if "diverging_values" in corpo_erro else "FOREIGN"))

        if r.get("status") not in (200, 201):
            raise FederationError(
                f"publicacao canonica falhou: HTTP {r.get('status')} "
                f"{r.get('body', '')}")

        # MESMO fato pelo segundo caminho. Nao ha novo event_id, nao ha novo
        # fingerprint, nao ha nova identidade.
        subject, ack = None, False
        if self._js is not None:
            subject = f"{env['event_type']}"
            ack = bool(self._js(subject, env))

        return PublishResult(
            event_id=env["event_id"],
            envelope_fingerprint=env["envelope_fingerprint"],
            http_status=r["status"],
            jetstream_subject=subject,
            jetstream_ack=ack,
            envelope=env,
        )


# ---------------------------------------------------------------------------
# Self-test — sem rede, com transportes falsos, mas com o mesmo caminho de codigo
# ---------------------------------------------------------------------------

def _self_test() -> int:
    import yaml
    import liceu_conformance as conf

    cr = yaml.safe_load(open("liceu_contract_registry.yaml", encoding="utf-8"))

    enviados: list[dict] = []
    propagados: list[tuple[str, dict]] = []

    def http(metodo, url, body, cfg):
        if not url.startswith(cfg.api_url):
            return {"status": 400}
        # Autenticacao pelo secret do Event Store. JWT NUNCA e assinado aqui.
        assert cfg.api_secret, "secret ausente"
        if "/core-dna/contracts/" in url:
            return {"status": 200}
        enviados.append(body)
        return {"status": 201}

    def jetstream(subject, env):
        propagados.append((subject, env))
        return True

    resultados: list[tuple[str, bool]] = []

    def caso(nome, esperado_ok, fn):
        try:
            fn()
            ok = True
            det = ""
        except FederationError as e:
            ok, det = False, f"{type(e).__name__}: {e}"
        acertou = ok == esperado_ok
        resultados.append((nome, acertou))
        print(f"  [{'OK  ' if acertou else 'FALHA'}] "
              f"{'aceito' if ok else 'rejeitado':10} {nome}")
        if det and not ok:
            print(f"           -> {det.splitlines()[0][:110]}")

    print(f"Federation SDK v{SDK_VERSION}\n")

    # -- fail-closed --------------------------------------------------------
    for v in (ENV_URL, ENV_SECRET, "FEDERATION_API_URL", "CANONICAL_SERVICE_SECRET"):
        os.environ.pop(v, None)
    caso("configuracao ausente -> falha fechado", False,
         lambda: FederationConfig.from_env("liceu.john", "continental"))

    os.environ[ENV_URL] = "https://core.liceu.local"
    os.environ[ENV_SECRET] = "s3cr3t"
    os.environ["FEDERATION_API_URL"] = "https://outro"
    caso("alias proibido presente -> rejeita", False,
         lambda: FederationConfig.from_env("liceu.john", "continental"))
    os.environ.pop("FEDERATION_API_URL")

    cfg = FederationConfig.from_env("liceu.john", "continental",
                                    instance_id="liceu.john#earth-01")
    resolver = ContractResolver(cr, http)
    cli = FederationClient(cfg, resolver, conf, cr, http, jetstream)

    # -- autoridade ---------------------------------------------------------
    cfg_opera = FederationConfig.from_env("liceu.opera", "continental")
    cli_opera = FederationClient(cfg_opera, ContractResolver(cr, http),
                                 conf, cr, http, jetstream)
    caso("OPERA publica recomendacao do JOHN -> rejeita", False,
         lambda: cli_opera.publish("liceu.john.recommendation",
             {"alternatives": [{"alternative_id": "A", "summary": "x"},
                               {"alternative_id": "B", "summary": "y"}],
              "recommended_alternative_id": "A", "confidence": 0.8,
              "rationale": [{"factor": "c", "weight": 1}],
              "evidence_refs": ["e1"]},
             "art-1", lineage={"causation_id": "c1", "decision_id": "d1"}))

    # -- lineage proibido ---------------------------------------------------
    caso("JOHN tenta emitir governance_decision_id -> rejeita", False,
         lambda: cli.publish("liceu.john.recommendation",
             {"alternatives": [{"alternative_id": "A", "summary": "x"},
                               {"alternative_id": "B", "summary": "y"}],
              "recommended_alternative_id": "A", "confidence": 0.8,
              "rationale": [{"factor": "c", "weight": 1}],
              "evidence_refs": ["e1"]},
             "art-2", lineage={"causation_id": "c1", "decision_id": "d1",
                               "governance_decision_id": "g1"}))

    # -- G5 ------------------------------------------------------------------
    caso("JOHN recomenda alternativa inexistente -> rejeita", False,
         lambda: cli.publish("liceu.john.recommendation",
             {"alternatives": [{"alternative_id": "A", "summary": "x"},
                               {"alternative_id": "B", "summary": "y"}],
              "recommended_alternative_id": "Z", "confidence": 0.8,
              "rationale": [{"factor": "c", "weight": 1}],
              "evidence_refs": ["e1"]},
             "art-3", lineage={"causation_id": "c1", "decision_id": "d1"}))

    # -- caminho feliz -------------------------------------------------------
    resultado: dict = {}

    def feliz():
        r = cli.publish("liceu.john.recommendation",
            {"alternatives": [{"alternative_id": "A", "summary": "corredor A"},
                              {"alternative_id": "B", "summary": "corredor B"}],
             "recommended_alternative_id": "A", "confidence": 0.82,
             "rationale": [{"factor": "perdas", "weight": 0.6}],
             "evidence_refs": ["ev-cefeida-1"]},
            "art-ok", lineage={"causation_id": "c-cefeida-1", "decision_id": "d1"})
        resultado["r"] = r

    caso("JOHN publica recomendacao valida", True, feliz)

    # -- um fato, dois caminhos ---------------------------------------------
    r = resultado.get("r")
    if r:
        env_http = enviados[-1]
        subj, env_js = propagados[-1]
        mesmo = (env_http["event_id"] == env_js["event_id"] ==
                 r.event_id and
                 env_http["envelope_fingerprint"] ==
                 env_js["envelope_fingerprint"] == r.envelope_fingerprint)
        resultados.append(("HTTP e JetStream carregam o MESMO fato", mesmo))
        print(f"  [{'OK  ' if mesmo else 'FALHA'}] identidade   "
              f"HTTP e JetStream carregam o MESMO fato")
        print(f"           event_id={r.event_id[:8]}  "
              f"fingerprint={r.envelope_fingerprint[:16]}  subject={subj}")

        # Determinismo do fingerprint sobre o ENVELOPE CANONICO.
        # INVARIANTE: o mapeamento de boundary (producer_id -> producer) e
        # representacao de transporte e NAO pode alterar o fingerprint. Por isso
        # se recomputa sobre r.envelope, nunca sobre o corpo enviado no fio.
        det = envelope_fingerprint(r.envelope) == r.envelope_fingerprint
        wire_nao_altera = (env_js["envelope_fingerprint"] == r.envelope_fingerprint
                           and env_http.get("producer") == r.envelope["producer_id"])
        resultados.append(("fingerprint deterministico sobre o envelope canonico", det))
        resultados.append(("mapeamento de boundary nao altera o fingerprint", wire_nao_altera))
        print(f"  [{'OK  ' if det else 'FALHA'}] determinismo "
              f"fingerprint recomputavel sobre o envelope canonico")
        print(f"  [{'OK  ' if wire_nao_altera else 'FALHA'}] boundary     "
              f"mapeamento producer_id->producer nao altera o fingerprint")

    # -- o SDK nao publica por caminho alternativo ---------------------------
    cli_sem = FederationClient(cfg, ContractResolver(cr, http), conf, cr,
                               None, jetstream)
    caso("sem transporte HTTP -> nao grava por caminho alternativo", False,
         lambda: cli_sem.publish("liceu.john.recommendation",
             {"alternatives": [{"alternative_id": "A", "summary": "x"},
                               {"alternative_id": "B", "summary": "y"}],
              "recommended_alternative_id": "A", "confidence": 0.8,
              "rationale": [{"factor": "c", "weight": 1}],
              "evidence_refs": ["e1"]},
             "art-4", lineage={"causation_id": "c1", "decision_id": "d1"}))

    # -- registry local nao e autoridade -------------------------------------
    cli_off = FederationClient(cfg, ContractResolver(cr, None), conf, cr,
                               http, jetstream)
    caso("strict sem canal para o CORE -> registry local nao vira autoridade",
         False,
         lambda: cli_off.publish("liceu.john.recommendation",
             {"alternatives": [{"alternative_id": "A", "summary": "x"},
                               {"alternative_id": "B", "summary": "y"}],
              "recommended_alternative_id": "A", "confidence": 0.8,
              "rationale": [{"factor": "c", "weight": 1}],
              "evidence_refs": ["e1"]},
             "art-5", lineage={"causation_id": "c1", "decision_id": "d1"}))


    # -- leitura canonica (SDK 0.2.0) ---------------------------------------
    armazenado: dict = {}

    def http_com_leitura(metodo, url, body, cfg):
        if not url.startswith(cfg.api_url):
            return {"status": 400}
        assert cfg.api_secret, "secret ausente"
        if "/core-dna/contracts/" in url:
            return {"status": 200}
        if metodo == "POST" and "/federation/events/publish" in url:
            # o servidor guarda SO os campos que aceita, e usa `producer`
            aceitos = {"event_type", "payload", "event_id", "trace_id",
                       "artifact_id", "scope", "producer", "contract_id",
                       "contract_version", "causation_id", "decision_id"}
            armazenado[body["event_id"]] = {k: v for k, v in body.items()
                                            if k in aceitos}
            enviados.append(body)
            return {"status": 201}
        if metodo == "GET" and "/federation/events/by-type/" in url:
            tipo = url.split("/by-type/")[1].split("?")[0]
            lim = int(url.split("limit=")[1].split("&")[0]) if "limit=" in url else 200
            # o servidor ordena por created_at DESC antes de filtrar
            achados = [e for e in reversed(list(armazenado.values()))
                       if e.get("event_type") == tipo]
            fatia = achados[:lim]
            return {"status": 200, "body": {"status": "ok", "event_type": tipo,
                                            "total": len(achados),
                                            "returned": len(fatia),
                                            "items": fatia}}
        if metodo == "GET" and "/federation/events/" in url:
            eid = url.rsplit("/", 1)[-1]
            if eid not in armazenado:
                return {"status": 404}
            return {"status": 200, "body": {"status": "ok",
                                            "item": armazenado[eid]}}
        return {"status": 400}

    cli_r = FederationClient(cfg, ContractResolver(cr, http_com_leitura), conf, cr,
                             http_com_leitura, jetstream)

    def publicar_e_verificar():
        res = cli_r.publish("liceu.john.recommendation",
            {"alternatives": [{"alternative_id": "A", "summary": "x"},
                              {"alternative_id": "B", "summary": "y"}],
             "recommended_alternative_id": "A", "confidence": 0.8,
             "rationale": [{"factor": "c", "weight": 1}],
             "evidence_refs": ["e1"]},
            "art-read", lineage={"causation_id": "c1", "decision_id": "d1"})
        v = cli_r.verify_persistence(res)
        if not v.persisted:
            raise ReadError(v.motivo)
        return v

    ver: dict = {}
    caso("publish + verify_persistence pelo boundary oficial", True,
         lambda: ver.update(v=publicar_e_verificar()))

    v = ver.get("v")
    if v:
        print(f"           campos conferidos: "
              f"{sum(v.campos_conferidos.values())}/{len(v.campos_conferidos)}"
              f"  | nao verificaveis server-side: "
              f"{len(v.campos_nao_verificaveis)}")

    # evento inexistente -> BLOCKED, nunca otimismo
    class _R:
        event_id = "nao-existe"; envelope_fingerprint = ""; envelope = {}
    v2 = cli_r.verify_persistence(_R())
    ok2 = (not v2.persisted) and v2.motivo.startswith("BLOCKED")
    resultados.append(("evento inexistente -> BLOCKED, nao otimismo", ok2))
    print(f"  [{'OK  ' if ok2 else 'FALHA'}] fail-closed  "
          f"leitura de evento inexistente resulta em BLOCKED")

    # sem transporte -> nao le banco, nao cai para caminho alternativo
    cli_nr = FederationClient(cfg, ContractResolver(cr, http), conf, cr, None, jetstream)
    try:
        cli_nr.get_event("qualquer"); ok3 = False
    except ReadError:
        ok3 = True
    resultados.append(("sem transporte -> get_event nao le banco", ok3))
    print(f"  [{'OK  ' if ok3 else 'FALHA'}] fail-closed  "
          f"get_event sem transporte nao degrada para banco local")

    # o servidor DESCARTA campos que nao aceita — provar que sabemos disso
    if v:
        desc = set(CAMPOS_NAO_ACEITOS_PELO_SERVIDOR)
        guardado = set(armazenado[v.event_id])
        ok4 = not (desc & guardado)
        resultados.append(("campos nao aceitos nao voltam do servidor", ok4))
        print(f"  [{'OK  ' if ok4 else 'FALHA'}] realidade    "
              f"payload_hash/fingerprint/emitted_at nao persistem no servidor")


    # -- consulta por tipo (SDK 0.3.0) --------------------------------------
    # Substitui a query direta do gate W89-A do BIM:
    #   SELECT ... WHERE event_type = %s ORDER BY created_at DESC LIMIT 1
    def _pub(tipo_evento, artifact):
        return cli_r.publish("liceu.john.recommendation",
            {"alternatives": [{"alternative_id": "A", "summary": "x"},
                              {"alternative_id": "B", "summary": "y"}],
             "recommended_alternative_id": "A", "confidence": 0.8,
             "rationale": [{"factor": "c", "weight": 1}],
             "evidence_refs": ["e1"]},
            artifact, lineage={"causation_id": "c1", "decision_id": "d1"})

    r1 = _pub(None, "art-t1")
    r2 = _pub(None, "art-t2")

    q = cli_r.get_events_by_type("john.recommendation.generated", limit=1)
    ordem_ok = bool(q.items) and q.items[0]["event_id"] == r2.event_id
    resultados.append(("get_events_by_type devolve o mais recente primeiro", ordem_ok))
    print(f"  [{'OK  ' if ordem_ok else 'FALHA'}] ordenacao   "
          f"items[0] == ultimo publicado (equivale a ORDER BY created_at DESC LIMIT 1)")
    print(f"           total={q.total} returned={q.returned} "
          f"truncamento_indetectavel={q.truncamento_indetectavel}")

    latest = cli_r.get_latest_by_type("john.recommendation.generated")
    ok_latest = latest["event_id"] == r2.event_id
    resultados.append(("get_latest_by_type equivale a LIMIT 1", ok_latest))
    print(f"  [{'OK  ' if ok_latest else 'FALHA'}] equivalencia "
          f"get_latest_by_type reproduz a semantica da query do gate do BIM")

    caso("tipo inexistente -> ReadError, nao lista vazia silenciosa", False,
         lambda: cli_r.get_latest_by_type("tipo.que.nao.existe"))

    caso("limit acima do aceito pelo servidor -> rejeita", False,
         lambda: cli_r.get_events_by_type("john.recommendation.generated", limit=5000))

    cli_sq = FederationClient(cfg, ContractResolver(cr, http), conf, cr, None, jetstream)
    caso("sem transporte -> consulta por tipo nao le banco", False,
         lambda: cli_sq.get_events_by_type("john.recommendation.generated"))


    # -- colisao 409 (SDK 0.4.0) --------------------------------------------
    colidir = {"ativo": False}

    def http_com_colisao(metodo, url, body, cfg):
        if metodo == "POST" and "/federation/events/publish" in url and colidir["ativo"]:
            return {"status": 409, "body": {
                "detail": "event_id_collision_divergent_semantics",
                "event_id": body["event_id"],
                "diverging_fields": ["producer", "contract_version"],
                "conflict_token": "a1b2c3d4e5f6a7b8",
                "hint": "event_id e unico por produtor."}}
        return http_com_leitura(metodo, url, body, cfg)

    cli_c = FederationClient(cfg, ContractResolver(cr, http_com_colisao), conf, cr,
                             http_com_colisao, jetstream)

    def _pub_c():
        return cli_c.publish("liceu.john.recommendation",
            {"alternatives": [{"alternative_id": "A", "summary": "x"},
                              {"alternative_id": "B", "summary": "y"}],
             "recommended_alternative_id": "A", "confidence": 0.8,
             "rationale": [{"factor": "c", "weight": 1}],
             "evidence_refs": ["e1"]},
            "art-col", lineage={"causation_id": "c1", "decision_id": "d1"})

    colidir["ativo"] = True
    caso("409 do CORE -> CollisionError, nao sucesso", False, _pub_c)

    # o erro carrega os campos estruturados, sem vazar valor alheio
    try:
        _pub_c(); col = None
    except CollisionError as e:
        col = e
    ok_campos = bool(col) and col.diverging_fields == ["producer", "contract_version"] \
        and col.conflict_token == "a1b2c3d4e5f6a7b8" and col.mode == "FOREIGN"
    resultados.append(("CollisionError carrega diverging_fields e conflict_token", ok_campos))
    print(f"  [{'OK  ' if ok_campos else 'FALHA'}] estrutura   "
          f"CollisionError expoe campos do 409 sem valores alheios")
    if col:
        print(f"           {col.relatorio()}")

    # o relatorio nao pode conter valor de campo algum
    rel = col.relatorio() if col else ""
    sem_valor = "liceu.opera" not in rel and "1.0.0" not in rel
    resultados.append(("relatorio nao vaza valor de fato alheio", sem_valor))
    print(f"  [{'OK  ' if sem_valor else 'FALHA'}] privacidade "
          f"relatorio traz so nomes de campo e token opaco")

    # PROIBIDO: o SDK nao reenvia com event_id novo nem altera producer_id
    antes = len(enviados)
    try:
        _pub_c()
    except CollisionError:
        pass
    ok_sem_retry = len(enviados) == antes
    resultados.append(("SDK nao reenvia apos 409", ok_sem_retry))
    print(f"  [{'OK  ' if ok_sem_retry else 'FALHA'}] fail-closed "
          f"nenhuma republicacao automatica apos colisao")

    colidir["ativo"] = False
    caso("apos a colisao cessar, publicacao volta a funcionar", True, _pub_c)

    acertos = sum(1 for _, ok in resultados if ok)
    print(f"\n{acertos}/{len(resultados)} casos corretos")
    return 0 if acertos == len(resultados) else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(_self_test())
    print(__doc__)
