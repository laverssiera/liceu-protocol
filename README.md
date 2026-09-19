# liceu-protocol

Fonte única do protocolo LICEU 6.0: Constituição, Contract/Producer/Event
Registries, conformance kit (G1–G5), Federation SDK, registry checker e boundary
checker. Decisão: [ADR-001](docs/ADR-001-onde-o-kit-vive.md).

```
constitution=1.15.0   conformance_kit=0.11.0   federation_sdk=0.4.0
registry_checker=1.4.0   boundary_checker=1.1.0   package_date=2026-09-18
```

## Instalar

Fixe a versão. As três Mães validam sob a mesma lei só se as três fixarem a mesma.

```bash
pip install "liceu-protocol @ git+https://github.com/laverssiera/liceu-protocol@v0.11.0"
```

## Usar

O kit é carregado por diretório, como os monólitos já fazem:

```python
from liceu_protocol import KIT_DIR
kit = load_protocol_kit(KIT_DIR)   # o loader do consumidor (ex.: ARCHIMEDES runtime/planning_state_publisher.py)
```

Os módulos do kit importam-se entre si por nome plano (`import liceu_conformance`);
o loader registra-os em `sys.modules` antes de executar o SDK. Não importe
`liceu_protocol.liceu_federation_sdk` diretamente.

## Verificar

```bash
cd liceu_protocol
sha256sum -c MANIFEST                                   # 9/9 OK
python liceu_registry_check.py                          # 0 erros
LICEU_CONFORMANCE_STRICT=1 python liceu_conformance.py --self-test   # 90/90
python liceu_federation_sdk.py --self-test              # 25/25
```

A CI faz exatamente isso em todo push e PR.

## Mudar o kit

O `MANIFEST` é a identidade. Alterou um dos nove arquivos → regenere o `MANIFEST`
(`sha256sum <arquivos> > MANIFEST`, com o cabeçalho), faça bump em
`pyproject.toml`, e a tag nova é o que os consumidores fixam. Nunca edite uma cópia
vendorizada: substitua pelo pacote.

## Migração dos consumidores

1. ARCHIMEDES e FORNECEDORES: trocar `tools/liceu_protocol` pelo pacote (o loader
   recebe `KIT_DIR`; o passo de CI `sha256sum -c MANIFEST` passa a rodar aqui).
2. CORE: consumir o kit no boundary (modo ALERTA primeiro — CORE #34).
3. Demais: conforme migram do cliente HTTP próprio ao SDK.
