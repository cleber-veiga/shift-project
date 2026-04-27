# Adapted from Flowfile project, MIT License — see ./LICENSE and ./NOTICE.
#
# Imagem do sandbox de execucao de codigo do usuario no Shift. Diferente
# da imagem original do Flowfile (que roda um servidor FastAPI persistente
# com namespace de notebook), esta imagem e desenhada para containers
# *efemeros*: um container por execucao de code_node, sem servidor.

FROM python:3.12-slim

# Diretorio onde o runner mora — montado read-only via COPY no build, nao
# precisa de write-access em runtime.
WORKDIR /app

# Pacotes minimos para o runner. Nao instalamos build-essential, curl, ou
# qualquer outra dependencia que aumente a superficie de ataque dentro do
# container do usuario.
RUN pip install --no-cache-dir \
    duckdb>=1.1.0 \
    pyarrow>=14.0.0

# Copia o runner. Nada mais e copiado para a imagem final.
COPY kernel/runner.py /app/runner.py

# Usuario sem privilegios — defesa em profundidade caso o caller esqueca
# do --user no docker run.
RUN useradd --no-create-home --shell /usr/sbin/nologin --uid 65532 sandbox

USER sandbox

# Diretorios padrao usados pelo orquestrador:
# - /input  : montado read-only com o parquet de entrada
# - /output : tmpfs read-write onde o codigo escreve result.parquet
# Documentamos como hint mas nao criamos VOLUME para nao gerar volume
# anonimo em modos docker-in-docker.
ENV SHIFT_INPUT_DIR=/input \
    SHIFT_OUTPUT_DIR=/output \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Entrypoint le o codigo via stdin e roda. Sem servidor, sem porta exposta.
ENTRYPOINT ["python", "/app/runner.py"]
