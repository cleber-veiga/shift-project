# Prometheus — guia operacional do Shift

Este diretorio carrega o ``prometheus.yml`` de exemplo. Esta nota cobre o
**outro lado** da stack: cardinalidade, retention e quando usar Mimir/Cortex.

## Metricas com label `workspace_id` (alta cardinalidade)

A decisao de incluir `workspace_id` em alguns histogramas/contadores foi
deliberada (ver [`metrics.py`](../../shift-backend/app/core/observability/metrics.py)).
A trade-off: dashboards "por tenant" funcionam direto no Prometheus,
mas em SaaS maduro (10k+ workspaces ativos) o numero de series explode.

Series afetadas:

| Metrica                          | Tipo      | Cardinalidade base                       |
| -------------------------------- | --------- | ---------------------------------------- |
| `execution_duration_seconds`     | Histogram | `workspaces × templates × statuses × bucket` |
| `shift_executions_total`         | Counter   | `workspaces × templates × statuses`      |
| `db_pool_size`                   | Gauge     | `workspaces × database_types`            |
| `db_pool_checked_out`            | Gauge     | `workspaces × database_types`            |
| `db_pool_overflow`               | Gauge     | `workspaces × database_types`            |
| `streaming_queue_depth`          | Gauge     | `execution_id` (rotativo, mas vaza ate cleanup) |
| `streaming_spilled_chunks_total` | Counter   | `execution_id` (idem)                    |

Em deploy com 1k workspaces × 10 templates × 4 statuses × 11 buckets do
histograma = ~440k series so de `execution_duration_seconds_bucket`.
Adicione os outros e o Prometheus single-binary chega ao limite usual
(2-5M series por instancia em hardware modesto).

## Mitigacoes — em ordem de esforco

### Nivel 1 — `metric_relabel_configs` (config-only)

Drop labels em metricas onde detalhe-por-workspace nao e prioridade. Ex:
`node_duration_seconds` raramente precisa breakdown por tenant — basta
top-N agregado.

```yaml
scrape_configs:
  - job_name: shift-backend
    metric_relabel_configs:
      # Mantem ``execution_duration_seconds`` com workspace_id (dashboards
      # por tenant), mas dropa em metricas de no — analise global e
      # suficiente.
      - source_labels: [__name__]
        regex: 'node_(duration|errors|rows_processed).*'
        action: labeldrop
        replacement: 'workspace_id'
```

> ATENCAO: `labeldrop` em SERIES diferentes nao colide; dentro de UMA
> serie, dropar um label faz N series virarem 1 (somatorio implicito).
> Dashboards que usavam o label PRECISAM ser revisados.

### Nivel 2 — Recording rules de agregacao (pre-computar)

Ver [`recording-rules-aggregation.yml`](../alerts/recording-rules-aggregation.yml).
Pre-agregamos visoes globais (`shift:execution_duration:p95:5m:global`)
para que dashboards principais nao precisem computar
`histogram_quantile` em milhoes de buckets em cada refresh.

Resultado: queries de dashboard caem de 200ms-2s para <50ms; carga no
Prometheus reduz 10-100x para os paineis de alta frequencia.

### Nivel 3 — Retention diferenciada

Series com label de tenant nao precisam de 90 dias. Sugestao:

| Categoria                    | Retention | Onde |
| ---------------------------- | --------- | ---- |
| High-cardinality bruto       | 7-15 dias | Prometheus local |
| Recording rules globais      | 90 dias   | Prometheus local |
| Acima de 90 dias / compliance | indefinido | Mimir / Cortex / Thanos remote_write |

Configure via `--storage.tsdb.retention.time=15d` no Prometheus, e use
Mimir/Cortex/Thanos como long-term storage para as recording rules
agregadas (que sao baixa cardinalidade).

### Nivel 4 — Mimir/Cortex/Thanos (escala > 10M series)

Quando o backend ultrapassa ~5M series ativas e voce precisa de HA / DR
/ multi-tenancy real do Prometheus, adote Mimir (Grafana) ou Cortex.
Ambos suportam `remote_write` direto do Prometheus existente — migracao
incremental. Ate chegar nesse volume, Nivel 1+2+3 deve ser suficiente.

## Quem pode adicionar metricas com `workspace_id`?

Antes de adicionar, responda:

1. Ha um **dashboard pratico ou alerta** que requer breakdown por tenant?
2. Se nao, a serie agregada (sem `workspace_id`) cobre o caso de uso?
3. Se sim, podemos pre-agregar via recording rule e expor APENAS a
   agregada nos dashboards (mantendo a bruta com retention curto)?

Se 1 e 3 forem "nao", **nao adicione o label**. Reaproveite series
existentes ou crie agregacoes.

## Checklist para adicionar nova metrica

- [ ] Cardinalidade estimada: `nrows_label_a × nrows_label_b × ... × buckets`
- [ ] Documentei no docstring da metrica (em `metrics.py`)
- [ ] Atualizei a tabela acima neste README
- [ ] Considerei recording rule de agregacao
- [ ] Considerei retention especifico

## Observabilidade do proprio Prometheus

Habilite `prometheus_tsdb_head_series` no scrape do Prometheus —
metrica de proprio Prometheus. Alertar quando excede 60% do limite
configurado.

## Operational Limits

Veja a secao "Operational Limits" no [README global de ops](../README.md#operational-limits)
para a lista canonica de metricas sensiveis e umbrais de alerta
relacionados.
