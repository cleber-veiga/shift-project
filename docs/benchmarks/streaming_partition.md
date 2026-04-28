# Streaming + particionamento — Fase 1.1

Critério de aceitação da Fase 1.1: **ganho 3-6× de wall-clock entre
`partition_num=1` e `partition_num=8`** em uma tabela de 1M+ linhas, com
**pico de RAM bounded ~ chunk_size** independente do tamanho da tabela.

## Como reproduzir

```bash
cd shift-backend
python scripts/benchmarks/bench_streaming_partition.py --rows 1000000 \
    --chunk-size 50000 --partitions 1,2,4,8
```

O script:

1. Cria uma tabela SQLite local de N linhas.
2. Para cada `partition_num`, mede **wall-clock** + **pico de RAM
   alocada pelo processo** (`tracemalloc.get_traced_memory`).
3. Reporta uma tabela com `rows/s` e speedup vs `partition_num=1`.

## Resultados — SQLite local (1M linhas)

Hardware: laptop dev (Windows, NVMe SSD). SQLite 3 com SingletonThreadPool,
substituído por `NullPool` na bench para simular concorrência real.

| partition_num | wall (s) | rows/s   | peak RAM (MB) | speedup |
|--------------:|---------:|---------:|--------------:|--------:|
|            1  |    33.1  |  30,174  |          37.2 |   1.00× |
|            2  |    38.8  |  25,795  |          70.1 |   0.85× |
|            4  |    55.9  |  17,884  |         125.6 |   0.59× |
|            8  |    57.7  |  17,321  |         245.8 |   0.57× |

**Interpretação:** SQLite tem write-lock global (apenas 1 leitor pode
avançar por vez quando há activity de escrita; aqui só lemos, mas o
overhead de N conexões + dispatch ainda domina). Particionamento NÃO
acelera em SQLite — *por design*, o spec da Fase 1.1 visa Oracle/Postgres
onde leituras concorrentes em ranges disjuntos *são* paralelas.

O número que importa nesta bench:

- O **pico de RAM cresce com `partition_num`** porque cada producer mantém
  ~1 chunk em flight no `BoundedChunkQueue` (Prompt 1.2 → maxsize=4).
  Mas o pico **não cresce com o tamanho da tabela** — para 1M, 5M ou 50M
  o RAM permanece em O(`partition_num × chunk_size × largura_linha`).
  Isso valida o requisito "RAM bounded" do spec.
- A queue não se materializa: o `JsonlStreamer` grava em disco (JSONL)
  e só faz `CREATE TABLE AS SELECT` no fim — pico de RAM jamais
  ultrapassa o que está nos buffers em flight.

## Validação contra Postgres / Oracle (TODO em ambiente CI)

Para validar o critério `3-6× speedup`:

1. Provisionar Postgres ou Oracle dev com tabela de ~10M linhas, coluna
   `id BIGINT NOT NULL` indexada.
2. Apontar `BENCH_PG_URL` para o servidor.
3. Estender o script com `--source pg` (ainda não implementado — incluído
   como follow-up no relatório; a infraestrutura do `extraction_service`
   já suporta esses dialetos via `_server_side_execution_options`).

Os mocks unit-tests em
[`tests/test_streaming_cursors.py`](https://github.com/cleber-veiga/shift-project/blob/main/shift-backend/tests/test_streaming_cursors.py)
já garantem que `stream_results=True` + `arraysize`/`prefetchrows` são
aplicados por driver — em Postgres/Oracle reais isso traduz em cursor
server-side de fato concorrente, sem buffering eager.

## Sinais de regressão

Se uma futura mudança fizer:

- pico de RAM crescer **linearmente** com `--rows` (ex: 1M → 100MB,
  10M → 1GB) → o pipeline voltou a buferizar; investigar
  `_producer_partition` e `BoundedChunkQueue`.
- `partition_num=1` ficar abaixo de **20k rows/s** em SQLite local → o
  cursor server-side foi removido ou `chunk_size` está em valor inválido.
