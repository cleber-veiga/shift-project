# Union

**Categoria:** Transformação
**Tipo interno:** `union`

## Descrição

Combina N datasets upstream em um único resultado, identificados por handles `input_1`, `input_2`, … `input_N`. Suporta dois modos de alinhamento:

- **`by_name`** (padrão): `UNION ALL BY NAME` — alinha colunas por nome, preenchendo NULL onde a coluna não existe na fonte.
- **`by_position`**: `UNION ALL` — alinha colunas pela posição. Schemas devem ser idênticos ou compatíveis. Quando os schemas divergem, o nó emite o warning `schema_drift`.

Quando os datasets vêm de bancos DuckDB distintos, o nó faz `ATTACH ... READ_ONLY` automaticamente.

## Exemplo

**Entrada `input_1`:**

| ID | NOME  |
|----|-------|
| 1  | Alice |
| 2  | Bob   |

**Entrada `input_2`:**

| ID | NOME  | DEPTO |
|----|-------|-------|
| 3  | Carol | RH    |

**Configuração:** `mode=by_name`

**Saída:**

| ID | NOME  | DEPTO |
|----|-------|-------|
| 1  | Alice | NULL  |
| 2  | Bob   | NULL  |
| 3  | Carol | RH    |

## Configurações

| Campo | Tipo | Obrigatório | Padrão | Descrição |
|-------|------|-------------|--------|-----------|
| `mode` | string | não | `by_name` | `by_name` ou `by_position` |
| `add_source_col` | bool | não | `false` | Adiciona coluna identificando o handle de origem |
| `source_col_name` | string | não | `_source` | Nome da coluna de origem |
| `output_field` | string | não | `data` | Campo de saída |

## Notas de performance

- **Shape:** `wide` — UNION é eficiente em DuckDB, mas o resultado materializado tem `sum(N_i)` linhas.
- `by_name` é levemente mais caro pois precisa resolver alias de colunas, em troca de robustez a reordenação.
- `by_position` evita o overhead de mapping mas falha silenciosamente quando schemas divergem — preferir só quando a forma é controlada upstream.

## Limites e guardrails

- Menos de 2 entradas → erro.
- Modo desconhecido → erro com lista de modos válidos.

## Observabilidade

A saída inclui `output_summary` com:

- `row_count_in` — **dict por handle**: `{"input_1": N, "input_2": M, ...}`.
- `row_count_out` — soma das entradas.
- `warnings`:
  - `schema_drift` — em modo `by_position` quando os schemas das entradas têm nomes ou ordem diferentes. Validar manualmente que o alinhamento por posição está correto.

<!-- screenshot: TODO -->
