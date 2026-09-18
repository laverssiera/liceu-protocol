"""LICEU 6.0 — pacote de protocolo (Constituicao, registries, conformance kit, SDK).

Os arquivos deste diretorio sao o kit, byte a byte: a identidade do kit e o
``MANIFEST`` (sha256 de cada arquivo). Este ``__init__`` so expõe onde ele esta.

Uso no consumidor (mesmo loader que os monolitos ja usam):

    from liceu_protocol import KIT_DIR
    kit = load_protocol_kit(KIT_DIR)   # ex.: runtime/planning_state_publisher.py no ARCHIMEDES

Os modulos do kit importam-se entre si por nome plano (``import liceu_conformance``);
o loader do consumidor registra-os em ``sys.modules`` antes de executar o SDK.
Nao importe ``liceu_protocol.liceu_federation_sdk`` diretamente.
"""

from __future__ import annotations

from pathlib import Path

KIT_DIR = Path(__file__).resolve().parent


def version() -> dict[str, str]:
    """Le ``VERSION`` (chave=valor por linha)."""
    out: dict[str, str] = {}
    for line in (KIT_DIR / "VERSION").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            out[key.strip()] = value.strip()
    return out


__all__ = ["KIT_DIR", "version"]
