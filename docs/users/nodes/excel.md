# Excel

**Categoria:** Entradas
**Tipo interno:** `excel_input`

## Descrição

Lê uma planilha Excel (`.xlsx` ou `.xls`) e disponibiliza seu conteúdo como dataset. Suporta seleção de aba por nome ou índice, controle de onde começa o cabeçalho e supressão de linhas em branco.

A leitura é feita linha a linha via `openpyxl` em modo somente-leitura, sem carregar a planilha inteira na memória. Arquivos remotos são baixados automaticamente antes da leitura.

## Fontes de arquivo suportadas

| Fonte | Exemplo | Quando usar |
|-------|---------|-------------|
| URL HTTP/HTTPS | `https://exemplo.com/relatorio.xlsx` | Arquivo público ou com auth na URL |
| Caminho local | `/data/relatorios/vendas.xlsx` | Arquivo no servidor Shift |
| Upload do projeto | Selecionado via picker | Arquivo enviado pela interface do Shift |
| Variável | `{{vars.ArquivoExcel}}` | Planilha que muda a cada execução |

> S3/GCS/Azure não são suportados diretamente neste nó — use URL pública ou caminho local após montar o storage.

## Saída produzida

O dataset fica materializado em DuckDB. Os nós seguintes o referenciam via `upstream_results.<nodeId>.<output_field>`.

```json
{
  "status": "completed",
  "row_count": 820,
  "output_field": "data",
  "data": { "storage_type": "duckdb", "..." }
}
```

## Configurações

| Campo | Tipo | Padrão | Descrição |
|-------|------|--------|-----------|
| `url` | string | — | **Obrigatório.** Caminho ou URL do arquivo Excel |
| `sheet_name` | string ou inteiro | `null` | Nome da aba ou índice (base 0). `null` = aba ativa (primeira) |
| `header_row` | inteiro (≥ 0) | `0` | Índice (base 0) da linha que contém os cabeçalhos |
| `skip_empty` | boolean | `true` | Ignora linhas onde todas as células estão vazias |
| `output_field` | string | `data` | Nome do campo na saída onde o dataset é exposto |
| `max_rows` | inteiro | — | Limita a leitura a N linhas de dados (não conta cabeçalho) |
| `input_model_id` | UUID | — | Modelo de entrada para validar o cabeçalho da planilha |
| `retry_policy` | objeto | — | Política de retentativa em caso de falha |

### Seleção de aba

- **Sem modelo vinculado:** o picker lista as abas detectadas automaticamente no arquivo. Também é possível digitar diretamente um nome ou número.
- **Com modelo vinculado:** o picker passa a listar apenas as abas definidas no modelo, e seleciona a primeira automaticamente se `sheet_name` ainda não estiver preenchido.
- Se a aba solicitada não existir no arquivo, o nó usa a primeira aba disponível e registra um aviso no log (sem erro).

### Linha de cabeçalho (`header_row`)

Define qual linha do Excel contém os nomes das colunas. Linhas anteriores a esse índice são descartadas. Se a linha de cabeçalho estiver vazia, as colunas recebem nomes automáticos `col_0`, `col_1`, etc.

### Modelo de entrada (opcional)

Mesmo comportamento do nó CSV: valida colunas obrigatórias, ignora extras. Quando o modelo define múltiplas abas, o picker de aba passa a exibir apenas as abas do modelo, facilitando o mapeamento correto.

### Política de retentativa

Mesmos campos do nó CSV (`max_attempts`, `backoff_strategy`, `backoff_seconds`, `retry_on`).

## Conversão de tipos

O nó converte os tipos nativos do Excel automaticamente:

| Tipo Excel | Tipo no dataset |
|------------|----------------|
| Número inteiro | inteiro |
| Número decimal | float |
| Booleano | booleano |
| Data/hora | string ISO 8601 |
| Texto | string |
| Vazio | `NULL` |

## Comportamentos importantes

- **Arquivo vazio** (nenhuma linha de dados após o cabeçalho) → a execução falha com erro claro.
- **Download remoto** → feito via httpx com timeout de 30 s (conexão) e 300 s (leitura). O arquivo temporário é removido ao final, mesmo em caso de erro.
- **Upload do projeto** (`shift-upload://`) → mesmo mecanismo do CSV.
- **Múltiplas abas** → crie um nó Excel separado para cada aba que precisar ler.

## Limites e guardrails

- `header_row` negativo → erro de validação.
- `sheet_name` como índice fora do intervalo → comportamento equivalente a aba não encontrada (usa a primeira).
- Limite implícito de tempo para download remoto: 300 s.

## Observabilidade

A saída inclui `row_count` com o total de linhas lidas, visível no painel de execução.

<!-- screenshot: TODO assets/nodes/excel/config-panel.png -->
