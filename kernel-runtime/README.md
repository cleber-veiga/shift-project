# Shift kernel-runtime

Adapted from [Flowfile project](https://github.com/Edwardvaneechoud/Flowfile),
MIT License — see [LICENSE](./LICENSE) and [NOTICE](./NOTICE).

Imagem Docker que executa código Python de usuários do Shift em um
container efêmero, sem rede, com FS read-only e cgroup limits.

## Build

```bash
docker build -t shift-kernel-runtime:latest .
```

## Protocolo de execução

Um container **por execução** de `code_node`. Sem servidor HTTP, sem
porta exposta. A comunicação é:

- **stdin** → código Python do usuário.
- **/input/table.parquet** (read-only mount, opcional) → dados de entrada.
- **/output/result.parquet** (tmpfs read-write) → resultado do usuário.
- **stdout/stderr** → logs do node.
- **exit code** → 0 sucesso, 1 erro do usuário, 2 erro de protocolo.

## Variáveis disponíveis ao código

```python
# já injetado pelo runner — não precisa importar:
data            # DuckDBPyRelation com input_data se /input/table.parquet existir
connection      # duckdb.DuckDBPyConnection (in-memory)
duckdb          # módulo duckdb importado

# escreva o resultado em uma destas formas:
result = data.filter("x > 10")            # DuckDBPyRelation
# ou
result = "SELECT col FROM input_data"     # string SQL
# ou
result = [{"a": 1}, {"a": 2}]             # lista de dicts
```

## Como o `shift-backend` o usa

Ver `app/services/sandbox/docker_sandbox.py`. O orquestrador:

1. Materializa o input parquet em um tmpdir do host.
2. Lança o container com:
   - `network_mode="none"`
   - `read_only=True` (rootfs)
   - `tmpfs={"/tmp": "size=128m", "/output": "size=128m"}`
   - `mem_limit`, `cpu_quota` (do `SandboxLimits`)
   - `--user 65532:65532` (usuário sem privilégios)
   - `cap_drop=["ALL"]`, sem `--privileged`
   - bind do tmpdir do host em `/input` (read-only)
3. Envia o código do usuário em `stdin`.
4. Aguarda exit code com timeout duro (`docker wait` com timer).
5. Lê `result.parquet` do volume tmpfs (via `docker cp` ou `tar` stream).
6. Mata o container e remove.

## Não fazer (regras de segurança)

- Nunca usar `--privileged`, `--cap-add`, ou expor `docker.sock`.
- Nunca permitir mounts arbitrários — apenas o input parquet do
  workflow atual em `/input`, read-only.
- Nunca rodar o container como `root` (uid 0).
