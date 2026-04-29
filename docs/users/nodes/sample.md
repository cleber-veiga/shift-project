# Sample

**Categoria:** Transformação
**Tipo interno:** `sample`

## Descrição

Seleciona um subconjunto do dataset por três modos:

- **`first_n`**: as primeiras N linhas (`LIMIT n`).
- **`random`**: amostragem por reservoir com seed configurável — `USING SAMPLE reservoir(n ROWS) REPEATABLE(seed)`.
- **`percent`**: amostragem por Bernoulli — `USING SAMPLE p PERCENT (BERNOULLI)`.

O modo `random` com `seed` fixo é determinístico e reprodutível entre runs. Sem `seed` explícito, o nó emite o warning `non_reproducible_sample`.

## Exemplo

**Entrada:** 1.000 linhas com `ID 1..1000`

**Configuração:** `mode=random, n=10, seed=42`

**Saída:** 10 linhas selecionadas pelo reservoir; com o mesmo seed, as mesmas 10 linhas em runs subsequentes.

## Configurações

| Campo | Tipo | Obrigatório | Padrão | Descrição |
|-------|------|-------------|--------|-----------|
| `mode` | string | não | `first_n` | `first_n`, `random` ou `percent` |
| `n` | int | sim em `first_n`/`random` | — | Quantas linhas amostrar |
| `seed` | int | não | aleatório | Seed do reservoir; sem seed, emite warning |
| `percent` | float | sim em `percent` | — | Percentual ∈ (0, 100] |
| `output_field` | string | não | `data` | Campo de saída |

## Notas de performance

- **Shape:** `narrow`. `first_n` é O(n) — DuckDB para ao atingir o limite.
- `random` (reservoir) é O(linhas), pois precisa ler todas para decidir; recomendado para datasets pequenos a médios.
- `percent` (Bernoulli) decide por linha — variância no tamanho final.

## Limites e guardrails

- `n` negativo → erro.
- `percent` fora de (0, 100] → erro.
- Modo desconhecido → erro com lista de modos válidos.

## Observabilidade

A saída inclui `output_summary` com:

- `row_count_in` — linhas no upstream.
- `row_count_out` — linhas amostradas.
- `warnings`:
  - `non_reproducible_sample` — modo `random` sem `seed` explícito. Em workflows publicados, defina o seed para garantir reprodutibilidade entre execuções.

<!-- screenshot: TODO -->
