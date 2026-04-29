# Texto → Linhas (Text to Rows)

**Categoria:** Transformação  
**Tipo interno:** `text_to_rows`

## Descrição

"Explode" uma coluna de texto que contém múltiplos valores separados por delimitador, gerando uma linha para cada valor. Todas as outras colunas da linha original são replicadas em cada nova linha.

## Exemplo

**Entrada:**

| ID | TAGS      |
|----|-----------|
| 1  | a,b,c     |
| 2  | x,y       |

**Configuração:** coluna=`TAGS`, delimitador=`,`

**Saída:**

| ID | TAGS |
|----|------|
| 1  | a    |
| 1  | b    |
| 1  | c    |
| 2  | x    |
| 2  | y    |

## Configurações

| Campo | Tipo | Obrigatório | Padrão | Descrição |
|-------|------|-------------|--------|-----------|
| `column_to_split` | string | sim | — | Coluna com os valores delimitados |
| `delimiter` | string | sim | `","` | Separador (suporta múltiplos caracteres, ex.: `\|\|`) |
| `output_column` | string | não | `null` | Renomear a coluna de saída (vazio = mesmo nome) |
| `trim_values` | bool | não | `true` | Remover espaços ao redor de cada valor |
| `keep_empty` | bool | não | `false` | Preservar partes vazias (ex.: `"a,,b"` → 3 linhas) |
| `max_output_rows` | int | não | `null` | Limitar total de linhas geradas |

## Summary

O nó registra no resultado:

| Campo | Descrição |
|-------|-----------|
| `row_count_in` | Linhas no dataset de entrada |
| `row_count_out` | Linhas geradas após explosão |
| `avg_fanout` | Fator médio de expansão (`out / in`) |

## Performance

Implementado com `UNNEST(string_split(coluna, delimitador))` do DuckDB — execução em memória, muito eficiente.

**Benchmark de referência:** 1.000 linhas com fanout médio de 5× gera 5.000 linhas em < 50 ms.

## Notas

- O delimitador é interpretado como string literal, não regex.
- Valores `NULL` na coluna de entrada são ignorados (nenhuma linha gerada para esse registro).
- Use `output_column` para separar a coluna original da expandida quando precisar de ambas downstream — combine com o nó **Mapper** antes para duplicar a coluna.
