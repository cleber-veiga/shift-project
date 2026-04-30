# Entrada do Fluxo

**Categoria:** Gatilho
**Tipo interno:** `workflow_input`

## Descrição

Define o ponto de entrada de um **sub-fluxo** — um workflow reutilizável que pode ser invocado por outros workflows usando o nó [Chamar Fluxo](./chamar_fluxo.md). Quando o sub-fluxo é chamado, os parâmetros fornecidos pelo chamador chegam aqui e ficam disponíveis para os nós seguintes.

Use este nó sempre que quiser criar um workflow que funcione como uma **sub-rotina**: uma lógica encapsulada com entradas e saídas bem definidas, reutilizável em múltiplos outros workflows.

> Este nó **não pode ser disparado manualmente** pelo botão Play como os outros gatilhos. Ele só é acionado quando outro workflow invoca este fluxo via nó Chamar Fluxo.

## Relacionamento com outros nós

Os três nós que compõem o padrão de sub-fluxo trabalham juntos:

| Nó | Papel |
|----|-------|
| **Entrada do Fluxo** (este nó) | Recebe os parâmetros de entrada do chamador |
| **Saída do Fluxo** (`workflow_output`) | Empacota os resultados que serão devolvidos ao chamador |
| **Chamar Fluxo** (`call_workflow`) | No workflow pai: invoca este sub-fluxo e recebe a saída |

## Saída produzida

```json
{
  "status": "completed",
  "output_field": "data",
  "data": { ...parâmetros enviados pelo chamador... }
}
```

Os parâmetros chegam no campo definido por `output_field` (padrão `data`). Nós seguintes referenciam via `upstream_results.<nodeId>.data`.

## Configurações

| Campo | Tipo | Padrão | Descrição |
|-------|------|--------|-----------|
| `output_field` | string | `data` | Nome do campo na saída onde os parâmetros de entrada são expostos |

## Exemplo de uso

**Cenário:** Um sub-fluxo que recebe um `pedido_id` e retorna o status do pedido.

**Configuração do nó Entrada do Fluxo:**
- `output_field`: `entrada`

**No nó seguinte (ex.: SQL)**, referencie o parâmetro com:
```
{{ upstream_results.<nodeId>.entrada.pedido_id }}
```

**No nó Chamar Fluxo** (workflow pai), o mapeamento seria:
```json
{
  "input_mapping": {
    "pedido_id": "{{ upstream_results.<sourceId>.data.pedido_id }}"
  }
}
```

## Isolamento de contexto

O sub-fluxo roda em um contexto completamente isolado do workflow pai:

- Não herda variáveis, conexões ou resultados de nós do pai.
- Exceção: variáveis com o **mesmo nome** declaradas tanto no pai quanto no sub-fluxo são propagadas automaticamente (auto-forward). Isso evita remapeamento manual de conexões de banco de dados compartilhadas.
- O chamador pode sobrescrever os valores propagados via `variable_values` no nó Chamar Fluxo.

## Limites e guardrails

- Um workflow com Entrada do Fluxo pode ter apenas **um** nó deste tipo.
- Parâmetros obrigatórios não fornecidos pelo chamador → erro em tempo de execução no nó Chamar Fluxo.
- Ciclos de chamada (A invoca B que invoca A) são detectados e bloqueados pelo runtime (`call_stack` + `max_depth`).
- Rehydratação de datasets upstream: se o chamador mapear linhas de um nó materializado em DuckDB (ex.: resultado de um `filter`), o runtime carrega até **1.000 linhas** antes de resolver o mapeamento. Para volumes maiores, use o nó Loop (For Each) em vez de sub-fluxo.

## Observabilidade

A execução do sub-fluxo gera um `execution_id` próprio (prefixo `sub-`), visível nos logs. Cada invocação é rastreável independentemente do workflow pai.

<!-- screenshot: TODO -->
