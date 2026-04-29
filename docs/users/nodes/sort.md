# Sort

**Categoria:** Transformação
**Tipo interno:** `sort`

## Descrição

Ordena o dataset por uma ou mais colunas, com direção (ASC/DESC) e posição de nulos configurável por coluna. Um limite opcional restringe a saída aos N primeiros registros após a ordenação — útil para construir listas "top-N" sem rodar uma query separada.

## Exemplo

**Entrada:**

| ID | GRUPO | VALOR |
|----|-------|-------|
| 1  | B     | 10    |
| 2  | A     | 30    |
| 3  | A     | 20    |
| 4  | B     | 50    |

**Configuração:** `sort_columns=[{column: "GRUPO", direction: "asc"}, {column: "VALOR", direction: "desc"}]`

**Saída:**

| ID | GRUPO | VALOR |
|----|-------|-------|
| 2  | A     | 30    |
| 3  | A     | 20    |
| 4  | B     | 50    |
| 1  | B     | 10    |

## Configurações

| Campo | Tipo | Obrigatório | Padrão | Descrição |
|-------|------|-------------|--------|-----------|
| `sort_columns` | lista | sim | — | Cada item: `{column, direction, nulls_position}` |
| `sort_columns[].column` | string | sim | — | Nome da coluna |
| `sort_columns[].direction` | string | não | `asc` | `asc` ou `desc` |
| `sort_columns[].nulls_position` | string | não | `last` (asc) / `first` (desc) | `first` ou `last` |
| `limit` | int | não | — | Mantém apenas os N primeiros registros após ordenação |
| `output_field` | string | não | `data` | Campo do dicionário de saída onde a referência é gravada |

## Notas de performance

- **Shape:** `wide` — ORDER BY em DuckDB usa ordenação em memória, com fallback para spillover em disco quando o dataset não cabe.
- Datasets > 50M linhas tendem a saturar a memória; nesse caso prefira `LIMIT` ou particione antes de ordenar.
- Sem `limit`, o nó materializa o dataset inteiro reordenado — custo proporcional a `N * log(N)`.

## Limites e guardrails

- `sort_columns` vazio → erro `NodeProcessingError`.
- `column` vazio em qualquer item → erro.
- `limit` não inteiro ou negativo → erro.

## Observabilidade

A saída inclui `output_summary` com:

- `row_count_in` / `row_count_out` — número de linhas antes/depois.
- `warnings` — lista vazia neste nó (sort não tem heurísticas com warning automático).

<!-- screenshot: TODO -->
