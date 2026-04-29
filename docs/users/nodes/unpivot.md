# Unpivot

**Categoria:** Transformação  
**Tipo interno:** `unpivot`

## Descrição

Operação inversa do Pivot. Transforma o dataset do formato **wide** (colunas) para **long** (linhas): cada coluna selecionada vira uma linha, com o nome da coluna numa coluna de variável e o valor numa coluna de valor.

## Exemplo

**Entrada:**

| REGIAO | JAN | FEV | MAR |
|--------|-----|-----|-----|
| NORTE  | 100 | 200 | 150 |
| SUL    | 300 | 100 | 250 |

**Configuração:** índice=`REGIAO`, valores=`JAN, FEV, MAR`, variável=`MES`, valor=`VALOR`

**Saída:**

| REGIAO | MES | VALOR |
|--------|-----|-------|
| NORTE  | JAN | 100   |
| NORTE  | FEV | 200   |
| NORTE  | MAR | 150   |
| SUL    | JAN | 300   |
| SUL    | FEV | 100   |
| SUL    | MAR | 250   |

## Configurações

| Campo | Tipo | Obrigatório | Padrão | Descrição |
|-------|------|-------------|--------|-----------|
| `index_columns` | lista | sim | — | Colunas que permanecem fixas (identificadoras) |
| `value_columns` | lista | condicional | `[]` | Colunas explícitas a expandir |
| `by_type` | string | condicional | `null` | Seleção automática: `all_numeric` ou `all_string` |
| `variable_column_name` | string | não | `"variable"` | Nome da coluna com o nome das colunas originais |
| `value_column_name` | string | não | `"value"` | Nome da coluna com os valores |
| `cast_value_to` | string | não | `null` | Converter valores: `VARCHAR`, `DOUBLE`, `BIGINT` |

**Regra:** informe `value_columns` **ou** `by_type`, nunca os dois.

## Seleção automática por tipo (`by_type`)

| Valor | Colunas selecionadas |
|-------|----------------------|
| `all_numeric` | INTEGER, BIGINT, DOUBLE, FLOAT, DECIMAL, … |
| `all_string` | VARCHAR, TEXT, CHAR |

As `index_columns` são sempre excluídas da seleção automática.

## Notas de performance

- Tenta o `UNPIVOT` nativo do DuckDB primeiro (mais rápido).
- Se falhar (ex.: tipos mistos), usa UNION ALL: uma query por coluna. Funcional mas mais lento para muitas colunas.
- Para datasets com centenas de colunas, prefira selecionar explicitamente apenas as colunas necessárias.
