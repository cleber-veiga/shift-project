# Record ID

**Categoria:** Transformação
**Tipo interno:** `record_id`

## Descrição

Adiciona uma coluna de ID sequencial ao dataset usando `ROW_NUMBER() OVER (...)` do DuckDB. Suporta:

- **`partition_by`** — reinicia a numeração dentro de cada grupo.
- **`order_by`** — controla a ordem dentro de cada partição.
- **`start_at`** — primeiro valor do ID (offset).

Sem `order_by`, a ordem do `ROW_NUMBER()` é não-determinística entre runs; o nó aceita mas registra o warning `non_deterministic_without_order_by`.

## Exemplo

**Entrada:**

| GRUPO | NOME  |
|-------|-------|
| A     | Alice |
| A     | Bob   |
| B     | Carol |
| B     | Dan   |

**Configuração:** `id_column=ID, partition_by=[GRUPO], order_by=[{column: NOME, direction: asc}]`

**Saída:**

| ID | GRUPO | NOME  |
|----|-------|-------|
| 1  | A     | Alice |
| 2  | A     | Bob   |
| 1  | B     | Carol |
| 2  | B     | Dan   |

## Configurações

| Campo | Tipo | Obrigatório | Padrão | Descrição |
|-------|------|-------------|--------|-----------|
| `id_column` | string | não | `id` | Nome da nova coluna de ID |
| `start_at` | int | não | `1` | Primeiro valor do ID |
| `partition_by` | lista | não | `[]` | Colunas que reiniciam a contagem |
| `order_by` | lista | não | `[]` | Cada item: `{column, direction}` |
| `output_field` | string | não | `data` | Campo de saída |

## Notas de performance

- **Shape:** `narrow`. `ROW_NUMBER()` em DuckDB é eficiente; partições e ordenações grandes podem precisar de spillover em datasets enormes.
- O ID é gerado na materialização — não é lazy.

## Limites e guardrails

- `start_at` não inteiro → erro.
- `order_by` ou `partition_by` com coluna vazia → erro.

## Observabilidade

A saída inclui `output_summary` com:

- `row_count_in` / `row_count_out` — devem coincidir.
- `warnings`:
  - `non_deterministic_without_order_by` — sem `order_by`, IDs entre execuções podem variar para o mesmo dado.

<!-- screenshot: TODO -->
