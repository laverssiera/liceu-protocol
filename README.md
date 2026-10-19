# liceu-protocol

Fonte única do protocolo LICEU 6.0: Constituição, Contract/Producer/Event
Registries, conformance kit (G1–G5), Federation SDK, registry checker e boundary
checker. Decisão: [ADR-001](docs/ADR-001-onde-o-kit-vive.md).

As versões dos componentes vivem em [`liceu_protocol/VERSION`](liceu_protocol/VERSION), que se declara fonte
única. Elas NÃO são repetidas aqui: número derivável de outro artefato não
se escreve, se deriva — e este bloco, enquanto era escrito, ficou velho em
cinco dos seis valores.

## Instalar

Fixe a versão. As três Mães validam sob a mesma lei só se as três fixarem a mesma.

O número abaixo é o único escrito neste arquivo, porque um comando precisa
de um alvo concreto. Ele não é derivado, e por isso é CONFERIDO: a CI deste
repositório roda o detector de pino do liceu-genome, que o compara com
`liceu_protocol/VERSION` e reprova se divergirem. Escrito-e-conferido é o
segundo melhor depois de derivado, e a diferença fica dita.

```bash
pip install "liceu-protocol @ git+https://github.com/laverssiera/liceu-protocol@v0.30.0"
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
