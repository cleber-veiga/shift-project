# Benchmarking de Nodes: Flowfile -> Shift

## 1. Objetivo

Este documento analisa os nodes disponiveis no Flowfile e avalia quais fariam sentido trazer para o Shift.

O criterio usado aqui nao e "copiar tudo". Em ETL, um node so vale a pena se vier com:

1. contrato claro de entrada e saida;
2. comportamento previsivel de schema;
3. estrategia de memoria;
4. observabilidade;
5. semantica de erro;
6. encaixe no runtime atual do Shift, que hoje e fortemente baseado em `DuckDbReference`.

O arquivo complementar `benchmarking_flowfile_shift.md` cobre arquitetura geral. Este aqui foca no catalogo de nodes e nas lacunas funcionais.

---

## 2. Inventario resumido

## 2.1 Nodes observados no Flowfile

Fonte principal: `D:\Labs\Flowfile\flowfile_core\flowfile_core\configs\node_store\nodes.py`.

| Node Flowfile | Item | Grupo | Tipo de transformacao | Laziness | Status no Shift |
|---|---|---|---|---|---|
| External source | `external_source` | input | other | eager | Parcial via `api_input`, `http_request`, conexoes |
| Manual input | `manual_input` | input | other | lazy | Existe como `inline_data`/`manual_trigger`, mas sem mesma semantica |
| Read data | `read` | input | other | conditional | Parcial via `csv_input`, `excel_input` |
| Join | `join` | combine | wide | lazy | Existe |
| Formula | `formula` | transform | narrow | lazy | Parcial via `mapper`, `math`, `code_node` |
| Write data | `output` | output | other | eager | Existe via `load`, `bulk_insert`, `composite_insert` |
| Select data | `select` | transform | narrow | lazy | Parcial via `mapper`/SQL |
| Rename columns | `dynamic_rename` | transform | narrow | lazy | Parcial via `mapper` |
| Filter data | `filter` | transform | narrow | lazy | Existe |
| Group by | `group_by` | aggregate | wide | lazy | Existe como `aggregator` |
| Fuzzy match | `fuzzy_match` | combine | wide | eager | Falta |
| Sort data | `sort` | transform | wide | lazy | Falta como node dedicado |
| Add record Id | `record_id` | transform | wide | lazy | Falta |
| Take Sample | `sample` | transform | narrow | lazy | Falta como node dedicado |
| Random Split | `random_split` | transform | narrow | lazy | Falta |
| Explore data | `explore_data` | output | other | eager | Parcial via previews/UI |
| Pivot data | `pivot` | aggregate | wide | eager | Falta |
| Unpivot data | `unpivot` | aggregate | wide | lazy | Falta |
| Union data | `union` | combine | narrow | lazy | Falta como node multi-input dedicado |
| Drop duplicates | `unique` | transform | wide | lazy | Existe como `deduplication` |
| Graph solver | `graph_solver` | combine | other | lazy | Falta |
| Count records | `record_count` | aggregate | wide | lazy | Parcial via `aggregator`/SQL |
| Cross join | `cross_join` | combine | wide | lazy | Falta como node dedicado |
| Text to rows | `text_to_rows` | transform | wide | lazy | Falta |
| Polars code | `polars_code` | transform | narrow | conditional | Parcial via `code_node`, mas engine diferente |
| SQL Query | `sql_query` | transform | narrow | lazy | Existe parcialmente via `sql_script` |
| Python Script | `python_script` | transform | narrow | eager | Existe parcialmente via `code_node` |
| Read from Database | `database_reader` | input | other | eager | Existe como `sql_database` |
| Write to Database | `database_writer` | output | other | eager | Existe via `load`, `bulk_insert`, `composite_insert` |
| Cloud storage reader | `cloud_storage_reader` | input | other | conditional | Falta como node dedicado |
| Catalog reader | `catalog_reader` | input | other | lazy | Falta ate existir Dataset Registry |
| Catalog writer | `catalog_writer` | output | other | eager | Falta ate existir Dataset Registry |
| Cloud storage writer | `cloud_storage_writer` | output | other | eager | Falta como node dedicado |
| Kafka Source | `kafka_source` | input | other | eager | Falta |
| Google Analytics | `google_analytics_reader` | input | other | eager | Falta |
| LazyFrame node | `polars_lazy_frame` | special | other | lazy | Nao recomendado para Shift agora |

## 2.2 Nodes atuais no Shift

Fonte principal: `D:\Labs\shift-project\shift-backend\app\services\workflow\nodes`.

O Shift ja possui:

- entradas: `csv_input`, `excel_input`, `api_input`, `inline_data`, `sql_database`;
- transformacoes: `filter`, `mapper`, `math`, `join`, `lookup`, `aggregator`, `deduplication`, `sql_script`, `code_node`;
- controle: `condition`, `if`, `switch`, `loop`, `sync`, `sub_workflow`;
- saidas: `load`, `bulk_insert`, `composite_insert`, `truncate_table`;
- operacao: `assert`, `dead_letter`, `notification`;
- triggers: `manual_trigger`, `cron_trigger`, `webhook_trigger`, `polling_trigger`;
- integracao HTTP: `http_request`.

Leitura tecnica: o Shift tem mais foco em workflow operacional e integracao, enquanto o Flowfile tem mais variedade em transformacoes de dataframe e catalogo de dados.

---

## 3. Priorizacao recomendada

## 3.1 P0: implementar primeiro

| Node | Por que entra em P0 |
|---|---|
| `union` | Alto uso em ETL real; combina varias fontes com baixo risco. |
| `sort` | Basico para preparacao de dados e downstream deterministico. |
| `record_id` | Muito util para auditoria, ordenacao, chaves tecnicas e debugging. |
| `sample` | Ajuda UX, testes e pipelines exploratorios sem custo alto. |
| `text_to_rows` | Normalizacao comum de campos multivalorados. |
| `pivot`/`unpivot` | Transformacoes analiticas recorrentes; alto valor de produto. |

## 3.2 P1: implementar apos base de estrategia/worker

| Node | Por que esperar um pouco |
|---|---|
| `fuzzy_match` | Muito valioso, mas pesado; deve nascer em worker isolado. |
| `cross_join` | Perigoso por explosao cardinal; precisa de guardrails. |
| `catalog_reader`/`catalog_writer` | Dependem do Dataset Registry proposto. |
| `cloud_storage_reader`/`cloud_storage_writer` | Valor alto, mas exige contrato de credenciais/storage. |

## 3.3 P2: implementar sob demanda de produto

| Node | Motivo |
|---|---|
| `kafka_source` | Exige semantica de offset/commit e execucao continua ou microbatch. |
| `google_analytics_reader` | Conector vertical; excelente se houver demanda clara. |
| `random_split` | Mais ligado a ML/amostragem experimental. |
| `graph_solver` | Poderoso, mas nichado. |

## 3.4 Nao copiar agora

| Node | Motivo |
|---|---|
| `polars_lazy_frame` | Quebra a coerencia DuckDB-first do Shift. |
| `polars_code` como Polars-first | Melhor evoluir `code_node` com contrato `DuckDbReference`. |
| `explore_data` como backend node | Melhor tratar como experiencia de UI/previews, nao como etapa de pipeline. |

---

## 4. Analise detalhada por node recomendado

## 4.1 Union data

### O que o Flowfile faz

O Flowfile tem `union` como node multi-input, classificado como `narrow` e lazy. A operacao concatena datasets, preservando a ideia de nao materializar antes da hora quando possivel.

No `FlowDataEngine`, isso aparece como `concat(...)`, usando dataframes/lazyframes como base.

### Como esta hoje no Shift

Nao ha um node dedicado de union multi-input. Hoje o usuario tenderia a resolver por SQL customizado ou por uma composicao menos ergonomica.

### O que mudaria no Shift

Criar `union_node.py` com suporte a:

- multiplas entradas;
- modo `by_name` vs `by_position`;
- estrategia para colunas faltantes (`null_fill`, `strict`);
- opcional `source_column` para rastrear origem.

### Ganho esperado

- Consolidacao simples de varias fontes.
- Menos SQL manual.
- Melhor UX para pipelines de ingestao padronizados.

### Implementacao sugerida

Usar DuckDB:

```sql
CREATE OR REPLACE TABLE output AS
SELECT *, 'input_1' AS source FROM input_1
UNION ALL BY NAME
SELECT *, 'input_2' AS source FROM input_2;
```

Para compatibilidade ampla, implementar fallback montando `SELECT` com colunas alinhadas manualmente.

### Riscos

- Divergencia de tipos entre entradas.
- Colunas ausentes.
- Ordem de colunas.

### Guardrails

- modo `strict_schema=true` por default para primeira versao;
- modo `allow_missing_columns` so depois;
- evento com `input_count`, `output_columns`, `schema_conflicts`.

---

## 4.2 Sort data

### O que o Flowfile faz

`sort` e classificado como `wide`, lazy. Ordenacao pode exigir reorganizacao global do dataset, entao e corretamente marcada como operacao potencialmente cara.

No `FlowDataEngine`, `do_sort(...)` aplica ordenacoes sobre Polars.

### Como esta hoje no Shift

Nao ha node dedicado de sort. Pode ser feito via `sql_script`, mas isso joga responsabilidade para o usuario e perde UI tipada.

### O que mudaria no Shift

Criar `sort_node.py` com:

- lista de colunas;
- direcao por coluna;
- nulls first/last se suportado;
- limite opcional para top-N.

### Ganho esperado

- Preparacao deterministica para outputs.
- Melhor UX para ordenacao antes de export/carga.
- Base para operacoes como ranking e deduplicacao deterministica.

### Implementacao sugerida

DuckDB:

```sql
CREATE OR REPLACE TABLE output AS
SELECT *
FROM input
ORDER BY col1 ASC, col2 DESC;
```

### Riscos

- Sort global em tabela grande pode ser caro.
- Pode consumir disco temporario.

### Guardrails

- classificar como `wide`;
- strategy default `DATA_WORKER` quando input estimado for grande;
- alertar em preview se nao houver limite e row_count for alto.

---

## 4.3 Record ID

### O que o Flowfile faz

`record_id` adiciona uma coluna sequencial. O Flowfile suporta:

- ID simples;
- ID agrupado, reiniciando por grupo;
- offset.

No `FlowDataEngine`, isso aparece em `add_record_id(...)`, `_add_grouped_record_id(...)` e `_add_simple_record_id(...)`.

### Como esta hoje no Shift

Nao ha node dedicado. O usuario pode fazer com SQL customizado usando `row_number()`.

### O que mudaria no Shift

Criar `record_id_node.py` com:

- `output_column`;
- `start_at` ou `offset`;
- `order_by`;
- `partition_by` opcional.

### Ganho esperado

- Chave tecnica para auditoria.
- Debug mais facil.
- Preparacao para cargas que precisam de sequencia.

### Implementacao sugerida

DuckDB:

```sql
CREATE OR REPLACE TABLE output AS
SELECT
  row_number() OVER (PARTITION BY group_col ORDER BY order_col) + :offset AS record_id,
  *
FROM input;
```

### Riscos

- Sem `order_by`, resultado pode nao ser deterministico.

### Guardrails

- recomendar `order_by`;
- se ausente, registrar warning no evento do node.

---

## 4.4 Sample

### O que o Flowfile faz

`sample` e `narrow`, lazy. O Flowfile tambem usa sampling como parte da experiencia de preview e do modo local/remote.

### Como esta hoje no Shift

O Shift tem previews e pode limitar consultas em alguns pontos, mas nao ha node dedicado de amostragem para pipeline.

### O que mudaria no Shift

Criar `sample_node.py` com:

- `mode`: `first_n`, `random`, `percent`;
- `n`;
- `seed`;
- `output_field`.

### Ganho esperado

- Pipelines de teste mais baratos.
- Criacao de datasets menores para desenvolvimento.
- UX melhor para exploracao.

### Implementacao sugerida

DuckDB:

```sql
SELECT * FROM input LIMIT n;
```

Para random:

```sql
SELECT * FROM input USING SAMPLE reservoir(n ROWS) REPEATABLE(seed);
```

### Riscos

- Sem seed, execucoes nao reprodutiveis.

### Guardrails

- seed obrigatoria para `random` em workflows publicados;
- registrar modo e seed no output_summary.

---

## 4.5 Text to rows

### O que o Flowfile faz

`text_to_rows` divide uma string por delimitador e explode o resultado em multiplas linhas.

No `FlowDataEngine.split(...)`, ele faz:

- `str.split(...)`;
- `explode(...)`;
- opcionalmente escreve em coluna de saida diferente.

### Como esta hoje no Shift

Nao ha node dedicado. O usuario precisaria escrever SQL customizado.

### O que mudaria no Shift

Criar `text_to_rows_node.py` com:

- `column_to_split`;
- `delimiter`;
- `output_column`;
- `keep_empty`;
- `trim_values`;
- `max_splits` opcional.

### Ganho esperado

- Normalizacao de campos CSV-like, tags, listas, codigos concatenados.
- Muito util para dados vindos de planilhas e APIs.

### Implementacao sugerida

DuckDB:

```sql
CREATE OR REPLACE TABLE output AS
SELECT
  input.* EXCLUDE (col),
  value AS output_col
FROM input,
UNNEST(string_split(col, delimiter)) AS t(value);
```

### Riscos

- Explosao de linhas.
- Delimitadores regex vs literal.

### Guardrails

- estimar multiplicacao media em preview quando possivel;
- registrar `row_count_in` e `row_count_out`;
- opcional `max_output_rows` para modo preview.

---

## 4.6 Pivot data

### O que o Flowfile faz

`pivot` transforma linhas em colunas. O Flowfile trata pivot como `wide` e `eager`, o que e correto: pivot pode expandir colunas e exige descobrir valores unicos da coluna pivot.

No `FlowDataEngine.do_pivot(...)`, ele:

- coleta valores unicos da coluna pivot com limite de seguranca;
- emite warning se houver muitos valores unicos;
- agrega antes de pivotar;
- preenche zero para agregacoes como sum/count.

### Como esta hoje no Shift

Nao ha node dedicado. O usuario pode tentar resolver em SQL, mas pivot dinamico e chato e arriscado.

### O que mudaria no Shift

Criar `pivot_node.py` com:

- `index_columns`;
- `pivot_column`;
- `value_column`;
- `aggregations`;
- limite de valores unicos;
- estrategia para nomes de colunas.

### Ganho esperado

- Muito valor para dados analiticos e planilhas.
- Reduz SQL manual complexo.
- Melhora a paridade com ferramentas ETL visuais.

### Implementacao sugerida

Primeira versao:

- descobrir valores unicos da coluna pivot com limite, em query separada;
- gerar SQL condicional:

```sql
SELECT
  index_col,
  SUM(CASE WHEN pivot_col = 'A' THEN value_col ELSE 0 END) AS A_sum,
  SUM(CASE WHEN pivot_col = 'B' THEN value_col ELSE 0 END) AS B_sum
FROM input
GROUP BY index_col;
```

### Riscos

- Cardinalidade alta vira explosao de colunas.
- Nomes de colunas invalidos/duplicados.
- Tipos mistos em `value_column`.

### Guardrails

- `max_pivot_values` default 200, como Flowfile;
- falhar com erro claro acima do limite;
- sanitizar nomes e persistir mapping original -> coluna gerada.

---

## 4.7 Unpivot data

### O que o Flowfile faz

`unpivot` transforma wide -> long. No `FlowDataEngine.unpivot(...)`, ele aceita:

- colunas de valor;
- colunas de indice;
- seletor por tipo.

### Como esta hoje no Shift

Nao ha node dedicado.

### O que mudaria no Shift

Criar `unpivot_node.py` com:

- `index_columns`;
- `value_columns`;
- `variable_column_name`;
- `value_column_name`.

### Ganho esperado

- Normalizacao de planilhas largas.
- Preparacao para agregacoes e analises.

### Implementacao sugerida

DuckDB tem suporte a `UNPIVOT` em versoes recentes. Se a versao usada suportar:

```sql
SELECT *
FROM input
UNPIVOT (value FOR variable IN (col1, col2, col3));
```

Fallback:

```sql
SELECT index_col, 'col1' AS variable, col1 AS value FROM input
UNION ALL
SELECT index_col, 'col2' AS variable, col2 AS value FROM input;
```

### Riscos

- Tipos diferentes nas colunas unpivotadas.
- Numero grande de colunas gera SQL grande.

### Guardrails

- validar tipos ou cast explicito;
- limite de colunas;
- opcao `cast_value_to`.

---

## 4.8 Fuzzy match

### O que o Flowfile faz

`fuzzy_match` e uma operacao de join aproximado. O Flowfile usa `pl_fuzzy_frame_match`, prepara os dataframes e pode executar externamente via worker (`ExternalFuzzyMatchFetcher`).

Ponto importante: o Flowfile nao trata fuzzy match como transformacao trivial. Ele e `wide`, `eager` e com caminho externo, porque pode ser muito caro.

### Como esta hoje no Shift

Nao ha node equivalente. `lookup` e `join` exigem match exato.

### O que mudaria no Shift

Criar `fuzzy_match_node.py`, mas somente junto de worker isolado.

Configuracao minima:

- left/right handles;
- colunas de comparacao;
- algoritmo (`levenshtein`, `jaro_winkler`, `token_set`, dependendo da biblioteca);
- threshold;
- estrategia de bloqueio (`blocking_keys`) para reduzir combinatoria;
- max matches por linha;
- output score column.

### Ganho esperado

- Enriquecimento e conciliacao de cadastros.
- Casos reais de CRM, fornecedores, clientes, produtos, enderecos.
- Alto diferencial de produto.

### Implementacao sugerida

Nao fazer cross product completo. Exigir ao menos uma destas estrategias:

- blocking key;
- pre-normalizacao;
- limite de candidatos;
- indice auxiliar.

Possiveis bases:

- DuckDB para blocking e prefiltragem;
- Python worker para scoring fuzzy;
- resultado materializado em DuckDB.

### Riscos

- Explosao O(N*M).
- Consumo de memoria.
- Resultados dificeis de explicar.

### Guardrails

- node sempre `DATA_WORKER`;
- bloquear execucao sem `blocking_keys` quando ambos inputs forem grandes;
- estimativa de candidatos antes de rodar;
- output com score e metodo.

---

## 4.9 Cross join

### O que o Flowfile faz

`cross_join` gera produto cartesiano. O Flowfile trata como `wide`, lazy, e no codigo ha verificacoes de integridade/selecoes para evitar resultado absurdo.

### Como esta hoje no Shift

Nao ha node dedicado. Pode ser escrito via SQL.

### O que mudaria no Shift

Criar `cross_join_node.py` apenas com guardrails fortes:

- selecao de colunas esquerda/direita;
- estimativa `left_count * right_count`;
- limite maximo configuravel;
- confirmacao explicita no config para workflows publicados.

### Ganho esperado

- Casos de calendario x entidade;
- combinacoes de cenarios;
- enriquecimentos controlados.

### Riscos

- E um dos nodes mais perigosos em volume.

### Guardrails

- falhar acima de `MAX_CROSS_JOIN_ROWS`;
- exigir selecao de colunas;
- classificar como `DATA_WORKER` quando passar de limite pequeno.

---

## 4.10 Catalog reader/writer

### O que o Flowfile faz

O Flowfile tem `catalog_reader` e `catalog_writer` integrados ao catalogo:

- grava tabelas fisicas/virtuais;
- preserva metadados;
- atualiza `updated_at`;
- dispara schedules table-trigger;
- permite preview e SQL sobre catalogo.

### Como esta hoje no Shift

Nao ha Dataset Registry equivalente. Existem outputs (`load`, `bulk_insert`, etc.), mas nao um contrato claro de dataset publicado cross-workflow.

### O que mudaria no Shift

Criar:

- `dataset_writer` equivalente ao `catalog_writer`;
- `dataset_reader` equivalente ao `catalog_reader`.

Isso depende do Dataset Registry proposto no outro relatorio.

### Ganho esperado

- Reuso de dados entre workflows.
- Lineage.
- Base para dataset triggers.
- Governanca e descoberta.

### Implementacao sugerida

V1:

- writer grava materializacao fisica;
- reader le versao atual;
- sem virtual dataset.

V2:

- versionamento;
- schema diff;
- triggers.

### Riscos

- Se o registry nascer sem versao, triggers e cache ficam frageis.

---

## 4.11 Cloud storage reader/writer

### O que o Flowfile faz

O Flowfile tem nodes dedicados para ler/escrever em cloud storage. No `FlowDataEngine`, ha suporte a GCS, parquet, CSV, JSON, Delta/Iceberg em caminhos cloud.

### Como esta hoje no Shift

Nao ha node dedicado de cloud storage no inventario de processors. Pode haver integrações indiretas via HTTP/API, mas nao com semantica ETL de arquivo/dataset.

### O que mudaria no Shift

Criar:

- `cloud_storage_reader`;
- `cloud_storage_writer`.

Config:

- provider (`s3`, `gcs`, `azure`);
- credential/connection id;
- path/prefix;
- format (`csv`, `parquet`, `json`, opcional delta no futuro);
- schema/options;
- partitioning no writer.

### Ganho esperado

- Ingestao e exportacao de data lake.
- Integração com clientes que usam buckets como staging.
- Ponte natural para Dataset Registry.

### Implementacao sugerida

Comecar com:

- S3 e/ou GCS, conforme demanda real;
- CSV/Parquet;
- materializar em DuckDB como `DuckDbReference`.

### Riscos

- Credenciais;
- arquivos grandes;
- wildcard/prefix;
- schema drift.

### Guardrails

- limite de arquivos por leitura;
- preview de schema;
- log de arquivos lidos;
- checksum/fingerprint por objeto.

---

## 4.12 Kafka source

### O que o Flowfile faz

O Flowfile tem `kafka_source`, roda no worker e tem callback pos-execucao para commit de offsets somente quando o fluxo conclui com sucesso.

Isso e um detalhe importante: commit antes da conclusao do pipeline pode perder mensagens.

### Como esta hoje no Shift

Nao ha node Kafka dedicado.

### O que mudaria no Shift

Criar `kafka_source_node.py`, mas com semantica clara:

- microbatch, nao streaming infinito na primeira versao;
- `max_messages`;
- `max_wait_seconds`;
- `topic`;
- `consumer_group`;
- commit only on workflow success.

### Ganho esperado

- Ingestao event-driven/microbatch.
- Ponte para pipelines near-real-time.

### Riscos

- Offset management incorreto causa perda ou duplicacao.
- Workflow longo segura commit.
- Reprocessamento precisa ser intencional.

### Guardrails

- commit em callback de sucesso do workflow;
- dead-letter para mensagens invalidas;
- idempotencia recomendada no downstream.

---

## 4.13 Google Analytics reader

### O que o Flowfile faz

O Flowfile inclui `google_analytics_reader` para GA4, executado via worker.

### Como esta hoje no Shift

Nao ha node GA4 dedicado.

### O que mudaria no Shift

Criar `ga4_reader_node.py` se houver demanda comercial:

- property id;
- date range;
- dimensions;
- metrics;
- filters;
- quota handling;
- pagination.

### Ganho esperado

- Valor direto para times de marketing/produto.
- Menos dependencia de exportacoes manuais.

### Riscos

- Quotas e rate limits;
- autenticacao OAuth/service account;
- schema dinamico.

### Recomendacao

Nao priorizar antes de cloud/dataset registry, a menos que seja pedido por cliente.

---

## 4.14 Graph solver

### O que o Flowfile faz

`graph_solver` usa colunas `from` e `to` para resolver agrupamentos/conectividade, provavelmente componentes conectados.

No `FlowDataEngine.solve_graph(...)`, ele aplica `graph_solver(col_from, col_to)`.

### Como esta hoje no Shift

Nao ha equivalente.

### O que mudaria no Shift

Criar `graph_solver_node.py` apenas se houver caso de uso:

- resolucao de entidades;
- agrupamento por relacionamento;
- redes de dependencias;
- consolidacao de cadastros.

### Ganho esperado

- Muito poderoso para entity resolution e relacoes indiretas.

### Riscos

- Nichado;
- pode ser caro;
- dificil explicar na UI.

### Recomendacao

P2/P3. Fazer depois de fuzzy match, porque os dois podem se complementar.

---

## 4.15 Random split

### O que o Flowfile faz

`random_split` divide um dataset em multiplas saidas nomeadas por percentual. Ele materializa o shuffle uma vez para evitar recomputar por saida.

### Como esta hoje no Shift

Nao ha node equivalente. O Shift tem controle de fluxo, mas nao multi-output de split aleatorio de dados.

### O que mudaria no Shift

Criar `random_split_node.py` se houver foco em ML/teste:

- saidas nomeadas;
- percentuais;
- seed;
- coluna de split opcional.

### Ganho esperado

- Treino/teste;
- amostras experimentais;
- QA de pipelines.

### Riscos

- Multi-output de dados exige contrato claro com handles.
- Sem seed, nao e reprodutivel.

### Recomendacao

Nao e prioridade para ETL operacional geral.

---

## 5. Nodes que o Shift ja tem, mas pode melhorar copiando ideias do Flowfile

## 5.1 Join

O Shift ja implementa join de forma adequada em DuckDB, incluindo `ATTACH` quando left/right estao em arquivos diferentes. O que copiar do Flowfile:

- classificar como `wide`;
- strategy default para worker em grandes volumes;
- preview separado;
- suporte a semi/anti join, se ainda nao existir;
- selecao/renomeacao de colunas mais rica;
- verificacao de integridade antes de rodar joins perigosos.

## 5.2 Aggregator

O Shift ja tem `aggregator`. O que copiar:

- ampliar funcoes (`median`, `stddev`, `var`, `first`, `last`, `count_distinct`);
- schema preview antes da execucao;
- modo record count dedicado ou atalho de UX.

## 5.3 Deduplication

Equivalente ao `unique`. O que copiar:

- estrategias de manter primeiro/ultimo;
- `order_by` para determinismo;
- modo distinct all columns;
- contagem de duplicatas removidas.

## 5.4 Mapper/Formula

O Flowfile tem `formula` fortemente integrado com expressoes Polars. O Shift tem `mapper`/`math`/`code_node`.

Recomendacao:

- nao copiar Polars expression engine diretamente;
- fortalecer DSL/SQL expressions do Shift;
- validar expressoes antes da execucao;
- mostrar schema de saida previsto.

## 5.5 SQL Query / SQL Script

O Shift tem `sql_script`, com cuidado bom contra interpolacao insegura e suporte a bindings.

O que copiar do Flowfile:

- SQL sobre multiplas entradas de workflow de forma ergonomica;
- UI para registrar aliases de inputs;
- output schema prediction.

---

## 6. Ordem de implementacao recomendada

## Sprint 1: baixo risco, alto valor

1. `sample`
2. `sort`
3. `record_id`
4. `union`

Motivo: todos encaixam bem em DuckDB, nao exigem Dataset Registry nem worker remoto.

## Sprint 2: transformacoes analiticas

1. `text_to_rows`
2. `unpivot`
3. `pivot`
4. melhorias em `aggregator`

Motivo: alto valor para planilhas, BI e normalizacao de dados.

## Sprint 3: operacoes perigosas com guardrails

1. `cross_join`
2. `fuzzy_match`

Motivo: valor alto, mas precisam de estimativa de cardinalidade, limites e worker.

## Sprint 4: dados como produto

1. `dataset_writer`
2. `dataset_reader`
3. triggers por dataset

Motivo: isso muda o Shift de workflow runner para plataforma de dados operacional.

## Sprint 5: conectores externos

1. `cloud_storage_reader`
2. `cloud_storage_writer`
3. `kafka_source`
4. `google_analytics_reader`

Motivo: dependem de credenciais, storage contracts, quotas e semantica operacional.

---

## 7. Contrato padrao recomendado para novos nodes

Todo node novo deveria declarar:

```python
NODE_PROFILE = {
    "node_type": "pivot",
    "shape": "wide",
    "default_strategy": "local_thread",
    "worker_strategy_when_large": True,
    "input_handles": ["input"],
    "output_handles": ["success"],
    "requires_row_count_estimate": True,
}
```

E retornar sempre:

```json
{
  "node_id": "...",
  "status": "completed",
  "output_field": "data",
  "data": {
    "storage_type": "duckdb",
    "database_path": "...",
    "dataset_name": "main",
    "table_name": "..."
  },
  "summary": {
    "row_count_in": 100,
    "row_count_out": 250,
    "columns_added": [],
    "warnings": []
  }
}
```

Esse contrato e mais importante do que a feature em si.

---

## 8. Ranking final

## Copiar agora

1. `union`
2. `sort`
3. `record_id`
4. `sample`
5. `text_to_rows`
6. `unpivot`
7. `pivot`

## Copiar com worker/guardrails

1. `fuzzy_match`
2. `cross_join`
3. `graph_solver`

## Copiar depois do Dataset Registry

1. `catalog_writer` como `dataset_writer`
2. `catalog_reader` como `dataset_reader`
3. table/dataset triggers

## Copiar sob demanda comercial

1. `cloud_storage_reader`
2. `cloud_storage_writer`
3. `kafka_source`
4. `google_analytics_reader`

## Nao copiar literalmente

1. `polars_lazy_frame`
2. `polars_code`
3. `explore_data` como backend node

---

## 9. Conclusao

O Shift ja tem um conjunto bom de nodes operacionais. A lacuna mais clara em relacao ao Flowfile esta em nodes de transformacao de dataframe e em nodes de catalogo/dataset.

Minha recomendacao pratica e implementar primeiro os nodes que encaixam naturalmente no runtime DuckDB atual:

- `union`;
- `sort`;
- `record_id`;
- `sample`;
- `text_to_rows`;
- `pivot`;
- `unpivot`.

Depois disso, implementar os nodes de alto valor que exigem arquitetura melhor:

- `fuzzy_match`;
- `cross_join`;
- `dataset_reader`;
- `dataset_writer`;
- `cloud_storage_reader/writer`.

Essa ordem evita o erro comum de copiar conectores e features vistosas antes de amadurecer o contrato operacional. O Shift ganharia funcionalidade visivel rapidamente, mas sem abrir mao da arquitetura DuckDB-first que ja e uma vantagem tecnica do projeto.

---

## 10. Referencias usadas

### Flowfile

- `D:\Labs\Flowfile\flowfile_core\flowfile_core\configs\node_store\nodes.py`
- `D:\Labs\Flowfile\flowfile_core\flowfile_core\flowfile\flow_data_engine\flow_data_engine.py`
- `D:\Labs\Flowfile\flowfile_core\flowfile_core\catalog\service.py`
- `D:\Labs\Flowfile\flowfile_worker\flowfile_worker\routes.py`
- `D:\Labs\Flowfile\flowfile_worker\flowfile_worker\streaming.py`

### Shift

- `D:\Labs\shift-project\shift-backend\app\services\workflow\nodes`
- `D:\Labs\shift-project\shift-backend\app\services\workflow\nodes\join_node.py`
- `D:\Labs\shift-project\shift-backend\app\services\workflow\nodes\lookup_node.py`
- `D:\Labs\shift-project\shift-backend\app\services\workflow\nodes\aggregator_node.py`
- `D:\Labs\shift-project\shift-backend\app\services\workflow\nodes\sql_script.py`
- `D:\Labs\shift-project\shift-backend\app\data_pipelines\duckdb_storage.py`
