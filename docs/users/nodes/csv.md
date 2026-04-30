# CSV

**Categoria:** Entradas
**Tipo interno:** `csv_input`

## Descrição

Lê um arquivo CSV e disponibiliza seu conteúdo como dataset para os nós seguintes. O arquivo pode vir de quatro fontes diferentes: uma URL/caminho direto, um arquivo já salvo no projeto, um upload feito na hora, ou uma variável de workflow (útil quando o arquivo muda a cada execução).

A leitura é feita via DuckDB de forma streaming — o arquivo não é carregado inteiro na memória do servidor, o que permite processar arquivos grandes com segurança.

## Fontes de arquivo suportadas

| Fonte | Exemplo | Quando usar |
|-------|---------|-------------|
| URL HTTP/HTTPS | `https://exemplo.com/dados.csv` | Arquivo público ou com auth na URL |
| Caminho local | `/data/exports/pedidos.csv` | Arquivo no servidor Shift |
| Cloud storage | `s3://bucket/pasta/arquivo.csv` | AWS S3, Google Storage, Azure |
| Upload do projeto | Selecionado via picker | Arquivo enviado pela interface do Shift |
| Variável | `{{vars.ArquivoCSV}}` | Arquivo que muda a cada execução |

## Saída produzida

O dataset fica materializado em DuckDB. Os nós seguintes o referenciam via `upstream_results.<nodeId>.<output_field>`.

```json
{
  "status": "completed",
  "row_count": 1500,
  "output_field": "data",
  "data": { "storage_type": "duckdb", "..." }
}
```

## Configurações

| Campo | Tipo | Padrão | Descrição |
|-------|------|--------|-----------|
| `url` | string | — | **Obrigatório.** Caminho ou URL do arquivo CSV |
| `delimiter` | string (1 char) | `,` | Separador de colunas. Use `\t` para TSV |
| `has_header` | boolean | `true` | Se a primeira linha é o cabeçalho |
| `encoding` | string | `utf-8` | Codificação do arquivo (ver opções abaixo) |
| `null_padding` | boolean | `true` | Preenche com `NULL` colunas faltantes em linhas curtas |
| `output_field` | string | `data` | Nome do campo na saída onde o dataset é exposto |
| `max_rows` | inteiro | — | Limita a leitura a N linhas (útil para preview) |
| `input_model_id` | UUID | — | Modelo de entrada para validar o cabeçalho do CSV |
| `retry_policy` | objeto | — | Política de retenativa em caso de falha (ver abaixo) |

### Encodings aceitos

`utf-8` · `utf-16` · `latin-1` · `iso-8859-1` · `cp1252` · `ascii`

### Modelo de entrada (opcional)

Quando vinculado, o nó valida na execução se todas as colunas obrigatórias do modelo estão presentes no arquivo. Colunas extras são aceitas sem erro. Se uma coluna obrigatória estiver faltando, a execução falha com mensagem detalhada listando o que estava ausente e o que foi encontrado.

### Política de retentativa

| Campo | Tipo | Padrão | Descrição |
|-------|------|--------|-----------|
| `max_attempts` | int (1–10) | — | Número máximo de tentativas |
| `backoff_strategy` | enum | `none` | `none`, `fixed` ou `exponential` |
| `backoff_seconds` | float (0.1–300) | — | Espera entre tentativas |
| `retry_on` | lista de strings | — | Filtra retentativas por mensagem de erro |

## Comportamentos importantes

- **Arquivo vazio** → a execução falha com erro claro (0 linhas lidas).
- **Sem cabeçalho** (`has_header: false`) → colunas recebem nomes automáticos `column0`, `column1`, etc.
- **Delimitador inválido** (mais de 1 caractere) → erro de validação antes da execução.
- **URLs remotas** → DuckDB carrega a extensão `httpfs` automaticamente. Não é necessária configuração extra para S3/GCS/Azure desde que as credenciais estejam no ambiente.
- **Upload do projeto** (`shift-upload://`) → o arquivo é "tocado" antes da leitura para evitar que seja removido pela limpeza automática durante a execução.

## Limites e guardrails

- `delimiter` deve ter exatamente 1 caractere.
- `encoding` fora da lista aceita → erro de validação.
- `max_rows` ≤ 0 → comportamento indefinido; omita o campo para sem limite.

## Observabilidade

A saída inclui `row_count` com o total de linhas lidas, visível no painel de execução.

<!-- screenshot: TODO assets/nodes/csv/config-panel.png -->
