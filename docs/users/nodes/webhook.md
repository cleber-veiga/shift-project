# Webhook

**Categoria:** Gatilho
**Tipo interno:** `webhook`

## Descrição

Expõe uma URL HTTP pública que, ao receber uma chamada, inicia o workflow imediatamente com o payload recebido. Permite integrar o Shift a qualquer sistema externo que suporte envio de webhooks — ERPs, plataformas de e-commerce, ferramentas de automação, etc.

Cada nó Webhook gera duas URLs distintas:

| URL | Quando usar |
|-----|-------------|
| **Test URL** (`/api/v1/webhook-test/{path}`) | Testes durante desenvolvimento; o workflow roda em modo draft |
| **Production URL** (`/api/v1/webhook/{path}`) | Uso real; disponível somente com o workflow em **Produção** e **Publicado** |

## Saída produzida

```json
{
  "trigger_type": "webhook",
  "status": "triggered",
  "http_method": "POST",
  "headers": { "content-type": "application/json", ... },
  "query_params": { "source": "erp" },
  "data": { ...body da requisição... }
}
```

O body da requisição fica no campo definido por `output_field` (padrão `data`). Query strings ficam em `query_params` e os cabeçalhos em `headers`.

## Configurações

### Aba Parameters

| Campo | Tipo | Padrão | Descrição |
|-------|------|--------|-----------|
| `http_method` | enum | `POST` | Método HTTP aceito: `GET`, `POST`, `PUT`, `PATCH`, `DELETE`, `HEAD` |
| `path` | string | UUID gerado automaticamente | Sufixo da URL do webhook. Gerado na primeira abertura; pode ser personalizado |
| `authentication` | objeto | `none` | Mecanismo de autenticação (ver abaixo) |
| `respond_mode` | enum | `immediately` | Quando o Shift responde ao chamador (ver abaixo) |
| `output_field` | string | `data` | Campo da saída onde o body da requisição é gravado |

#### Autenticação

| Tipo | Campos adicionais | Descrição |
|------|-------------------|-----------|
| `none` | — | Sem autenticação (qualquer chamada é aceita) |
| `header` | `header_name`, `header_value` | Exige um header com valor secreto (ex.: `X-Webhook-Secret`) |
| `basic` | `username`, `password` | HTTP Basic Auth |
| `jwt` | `jwt_secret`, `jwt_algorithm` | Bearer token JWT; algoritmos suportados: HS256, HS384, HS512, RS256 |

#### Modo de resposta (Respond)

| Valor | Comportamento |
|-------|--------------|
| `immediately` | Responde `200 OK` assim que o payload é recebido, sem esperar o workflow terminar |
| `on_finish` | Mantém a conexão aberta e responde somente quando o workflow conclui |
| `using_respond_node` | A resposta é controlada por um nó "Respond to Webhook" no fluxo |

### Aba Options (avançado)

| Campo | Padrão | Descrição |
|-------|--------|-----------|
| `response_code` | `200` | Código HTTP retornado ao chamador |
| `response_data` | `first_entry_json` | O que incluir no corpo da resposta: primeiro registro JSON, todos os registros, ou sem corpo |
| `raw_body` | `false` | Recebe o body sem parse JSON (útil para payloads binários ou texto puro) — indisponível para GET/HEAD |
| `allowed_origins` | *(vazio)* | Origens permitidas para CORS (`*` ou domínio específico) |

## Como testar

1. Abra o nó no editor e clique em **Listen for test event**.
2. O Shift fica aguardando por até 120 segundos.
3. Dispare uma requisição para a **Test URL** exibida no painel.
4. O payload capturado é injetado automaticamente na execução de teste.

## Limites e guardrails

- A **Production URL** só fica acessível após o workflow ser colocado em Produção e publicado.
- `path` vazio → o ID do workflow é usado como path de fallback.
- Com `respond_mode: on_finish`, chamadores com timeout curto podem receber erro de conexão encerrada antes de o workflow concluir.
- `raw_body: true` com método GET ou HEAD é bloqueado pela UI (GET/HEAD não carregam body).

## Observabilidade

A saída inclui `http_method`, `headers` e `query_params`, visíveis no painel de execução para depurar problemas de integração.

<!-- screenshot: TODO -->
