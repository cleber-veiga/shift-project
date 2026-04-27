# Sandbox pool — latência de execução de code_node — Fase 2.2

Critério de aceitação da Fase 2.2: **latência de execução de code_node
trivial** (`print('hello'); result = []`)

- **Cenário A** (pool desligado, cold start): ~2s por execução.
- **Cenário B** (pool com `target_idle=2`): **< 200ms** após pre-warm.

## Como reproduzir

```bash
# Build da imagem (uma vez)
cd kernel-runtime
docker build -t shift-kernel-runtime:latest .

# Bench
cd ../shift-backend
python scripts/benchmarks/bench_sandbox_pool.py --n 100
```

O script roda 100 execuções em cada cenário, medindo wall-clock end-to-end
(`time.perf_counter` antes do `await run_user_code` até o retorno do
`SandboxResult`). Reporta `p50`, `p95`, `p99`, `min`, `max`, `mean` em ms.

## Resultados

> **Status:** este ambiente de desenvolvimento (Windows) **não tem daemon
> Docker disponível**, portanto a bench é executada em CI ou em ambiente
> Linux com docker. Os números abaixo foram coletados em
> ([Linux x86_64, 4 vCPU, 8GB RAM, Docker Engine 24.x] — preencher na
> próxima execução em CI).

### Cenário A — pool desligado (cold start)

```
COLD:
  count : 100
  p50   : (preencher)
  p95   : (preencher)
  p99   : (preencher)
  min   : (preencher)
  max   : (preencher)
  mean  : (preencher)
```

Composição típica do cold start em ambiente Linux/Docker:

- `containers.create(...)` — ~50–200ms.
- `container.start()` — ~200–500ms.
- Boot do interpretador Python + `import duckdb` no runner — ~300–1500ms.
- `attach + write stdin + wait + extract output` — ~50–200ms.

**Total esperado:** 1.5s–2.5s na mediana.

### Cenário B — pool ligado (`target_idle=2`)

```
WARM:
  count : 100
  p50   : (preencher)
  p95   : (preencher)
  p99   : (preencher)
  min   : (preencher)
  max   : (preencher)
  mean  : (preencher)
```

Composição típica do warm hit:

- `pool.acquire()` — < 1ms (deque pop).
- `attach + write stdin + wait + extract output` — ~50–200ms.

Reposição do warm pool acontece em background pós-`release` — não conta na
latência da request.

**Total esperado:** 70ms–180ms na mediana → atende o critério `<200ms`.

### Speedup mediano

| Cenário                    | p50 (esperado)     |
|----------------------------|--------------------|
| Pool desligado (cold)      |   ~2000ms          |
| Pool ligado (warm hit)     |   ~150ms           |
| **Razão (cold/warm)**      |   **~13×**         |

O critério da Fase 2.2 é cobrir 1 ordem de grandeza (cold ~ 2s, warm <
200ms). Esperamos ~13× — folgado.

## Sinais de regressão

Configurações que invalidam a aceleração:

- `SANDBOX_POOL_TARGET_IDLE=0` no env — pool nunca pre-aquece, todos cold.
- `_limits_match_default()` retornando `False` — execuções com limits
  custom caem no cold path; default kwargs devem coincidir entre node e
  settings.
- Dockerfile do `kernel-runtime` adicionando dependências pesadas —
  `import duckdb` é o gargalo do cold start; novas libs grandes (pandas,
  scikit, etc.) inflariam ainda mais.

Se `bench_sandbox_pool.py` reportar warm p50 > 300ms, investigar nesta
ordem: (1) `_apply_driver_specific_cursor_tweaks` introduzindo trabalho
extra no path de execute; (2) `attach_socket` sem `_sock` (fallback lento);
(3) `_extract_output_parquet` com tarball muito grande.

## Métricas Prometheus relacionadas

- `sandbox_acquire_wait_ms_bucket{image, le}` — histogram com buckets até
  5s. Em CI, o p99 de `acquire` deve cair no bucket `≤100ms` quando o
  pool está saudável.
- `sandbox_acquire_total{image, outcome}` — relação `warm_hit /
  (warm_hit + cold_create)` deve ser próxima de 1.0 sob carga normal.
- `sandbox_pool_idle{image}` — gauge ≥ `target_idle - 1` na maioria do
  tempo; quedas frequentes para 0 indicam que `release → replenish` está
  lento ou que o tráfego é spiky e o pool é pequeno.
