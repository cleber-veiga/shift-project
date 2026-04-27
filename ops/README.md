# Shift — Observability ops bundle

Stack pre-configurada de observabilidade: dashboards Grafana, regras de alerta
Prometheus e exemplo de scrape config. Tudo aqui e versionado para que reviewers
de PR vejam mudancas em painel/alertas como qualquer outro codigo.

## Estrutura

```
ops/
├── grafana/
│   ├── dashboards/           # JSON de dashboards (importar via UI ou provisionar)
│   │   ├── shift-execution-health.json
│   │   ├── shift-resource-usage.json
│   │   └── shift-per-workspace.json
│   └── provisioning/         # YAML para datasource + dashboard provider
│       ├── datasources.yml
│       └── dashboards.yml
├── alerts/                   # Regras Prometheus (alerting + recording)
│   └── shift.rules.yml
├── prometheus/               # Exemplos de scrape config
│   └── prometheus.yml
└── README.md                 # este arquivo
```

## Subir o stack local em 1 comando

> Pre-requisito: Docker + docker compose. Os manifestos abaixo nao estao
> versionados — adapte para a infra existente, ou monte um docker-compose
> ad-hoc copiando os trechos do `prometheus.yml`/`provisioning/`.

Exemplo minimo de `docker-compose.yml`:

```yaml
services:
  prometheus:
    image: prom/prometheus:v2.54.1
    volumes:
      - ./ops/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - ./ops/alerts:/etc/prometheus/alerts:ro
    ports: ["9090:9090"]

  grafana:
    image: grafana/grafana:11.2.0
    environment:
      GF_AUTH_ANONYMOUS_ENABLED: "true"
      GF_AUTH_ANONYMOUS_ORG_ROLE: "Editor"
    volumes:
      - ./ops/grafana/dashboards:/etc/grafana/dashboards:ro
      - ./ops/grafana/provisioning:/etc/grafana/provisioning:ro
    ports: ["3001:3000"]
```

Depois disso:

- Prometheus em http://localhost:9090
- Grafana em http://localhost:3001 (dashboards ja provisionados)

## Dashboards disponiveis

### `shift-execution-health.json`

p50/p95/p99 de duracao por execucao, success rate, taxa de erro por minuto,
distribuicao por status. Painel principal de SRE para julgar saude do
servico.

### `shift-resource-usage.json`

Pools (DB, sandbox warm), queue depth de streaming, contadores de spillover
em disco, slots de spawner por tipo. Painel de "olha quem esta apertado".

### `shift-per-workspace.json`

Top 10 workspaces por volume e por latencia media, alem de erro por workspace.
Util para isolar tenants ruidosos.

## Alertas

`ops/alerts/shift.rules.yml` define cinco grupos:

- `shift_error_rate_high`         — > 5% de erros sustained 10m
- `shift_p95_duration_regressed`  — p95 atual > 3x baseline 1h
- `shift_sandbox_oom`             — OOM kills > 0 (any)
- `shift_db_pool_overflow`        — overflow > 0 sustained 5m
- `shift_queue_depth_high`        — queue depth > maxsize sustained 10m

Cada alerta tem `runbook_url` placeholder — preencha com o link interno
do time de plantao.

## Operational Limits

Algumas metricas sao **alta cardinalidade** por design (label
``workspace_id`` para dashboards por tenant). Em SaaS maduro essas series
podem chegar a 100k+ entradas. Antes de habilitar em producao com mais de
1k workspaces, leia o guia em [`prometheus/README.md`](prometheus/README.md).

Resumo das mitigacoes disponiveis:

| Nivel | Acao                           | Arquivo                                      |
| ----- | ------------------------------ | -------------------------------------------- |
| 1     | `metric_relabel_configs` drop  | [`prometheus/prometheus.yml`](prometheus/prometheus.yml) |
| 2     | Recording rules de agregacao   | [`alerts/recording-rules-aggregation.yml`](alerts/recording-rules-aggregation.yml) |
| 3     | Retention curto p/ alta-card   | flag `--storage.tsdb.retention.time`         |
| 4     | Mimir/Cortex/Thanos remote_write | infra externa                              |

Metricas afetadas estao listadas na tabela canonica em
[`prometheus/README.md#metricas-com-label-workspace_id`](prometheus/README.md).
