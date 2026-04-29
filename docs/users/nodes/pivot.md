# Pivot

**Categoria:** Transformação  
**Tipo interno:** `pivot`

## Descrição

Transforma o dataset do formato **long** (linhas) para **wide** (colunas), aplicando uma função de agregação. Equivale a uma tabela dinâmica.

Cada valor único encontrado na **coluna pivot** vira uma nova coluna. Os valores são calculados pela função de agregação sobre a **coluna de valor**, agrupados pelas **colunas de índice**.

## Exemplo

**Entrada:**

| REGIAO | PRODUTO | VALOR |
|--------|---------|-------|
| NORTE  | A       | 100   |
| NORTE  | A       | 50    |
| NORTE  | B       | 200   |
| SUL    | A       | 150   |
| SUL    | B       | 300   |

**Configuração:** índice=`REGIAO`, pivot=`PRODUTO`, valor=`VALOR`, agregação=`sum`

**Saída:**

| REGIAO | A_sum | B_sum |
|--------|-------|-------|
| NORTE  | 150   | 200   |
| SUL    | 150   | 300   |

## Configurações

| Campo | Tipo | Obrigatório | Padrão | Descrição |
|-------|------|-------------|--------|-----------|
| `index_columns` | lista | sim | — | Colunas que identificam a linha (GROUP BY) |
| `pivot_column` | string | sim | — | Coluna cujos valores únicos viram colunas |
| `value_column` | string | sim | — | Coluna com os valores a agregar |
| `aggregations` | lista | não | `["sum"]` | Funções: `sum`, `count`, `avg`, `max`, `min` |
| `max_pivot_values` | int | não | `200` | Limite de valores únicos na coluna pivot (máx. 1000) |

## Múltiplas agregações

Quando `aggregations` contém mais de uma função, cada combinação `valor × função` gera uma coluna separada:

```
aggregations: ["sum", "count"]
→ colunas: A_sum, A_count, B_sum, B_count
```

## Nomes de colunas

Caracteres especiais nos valores pivot são substituídos por `_`. Nomes duplicados recebem sufixo numérico automático (`_1`, `_2`, …).

O resultado inclui `pivot_col_mapping` — mapa `{valor: {função: nome_coluna}}` — para rastreabilidade em nós downstream.

## Notas de performance

- Utiliza SQL `CASE WHEN … THEN … END` por coluna (sem usar o PIVOT nativo do DuckDB), compatível com todos os tipos.
- Acima de ~50 colunas pivot o tempo de geração do SQL cresce linearmente, mas permanece performático para uso comum (até 200 valores).
- Use `max_pivot_values` conservador em datasets com alta cardinalidade para evitar explosão de colunas.
