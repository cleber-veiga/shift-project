# Manual

**Categoria:** Gatilho
**Tipo interno:** `manual`

## Descrição

Ponto de partida para execuções disparadas manualmente pelo botão **Play** no editor ou via API com payload explícito. Tudo que for enviado no corpo da requisição de disparo fica disponível para os nós seguintes através do campo `data`.

É o gatilho indicado para testes, execuções sob demanda e workflows que precisam receber parâmetros na hora do disparo (ex.: um ID de pedido, um intervalo de datas).

## Saída produzida

O nó não transforma dados — apenas empacota o que chegou no disparo:

```json
{
  "trigger_type": "manual",
  "status": "triggered",
  "data": { ...payload enviado no disparo... }
}
```

Os nós seguintes referenciam o payload via `upstream_results.<nodeId>.data`.

## Configurações

Este nó não possui campos de configuração. Basta arrastá-lo para o canvas e conectar ao próximo nó.

## Como passar dados no disparo

Ao clicar em **Play** no editor, um painel permite informar um JSON de entrada. Esse objeto se torna o `data` na saída do nó.

Via API:

```http
POST /api/v1/workflows/{workflowId}/execute
Content-Type: application/json

{
  "input_data": {
    "pedido_id": 4201,
    "data_inicio": "2025-01-01"
  }
}
```

## Limites e guardrails

- Sem payload → `data` é um objeto vazio `{}`. Nós downstream que dependem de campos específicos devem tratar esse caso.
- O nó não valida o schema do payload; use um nó de transformação logo após para garantir os campos obrigatórios.

## Observabilidade

A saída inclui `trigger_type: "manual"` e `status: "triggered"`, visíveis no painel de execução.

<!-- screenshot: TODO -->
