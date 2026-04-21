# Variáveis e Connection Mapping — Guia de Migração

## Contexto

Templates de workflow podem fazer referência a conexões de duas formas:

| Forma | Exemplo | Quando usar |
|---|---|---|
| **UUID literal** (legado) | `"connection_id": "3fa85f64-5717-..."` | Templates antigos criados antes das variáveis |
| **Referência de variável** | `"connection_id": "{{vars.conexao_destino}}"` | Forma recomendada — flexível e sem acoplamento |

---

## Fluxo recomendado (com variáveis)

### 1. Declare a variável no template

```json
{
  "variables": [
    {
      "name": "conexao_destino",
      "type": "connection",
      "required": true,
      "description": "Conexão com o banco de dados destino"
    }
  ]
}
```

### 2. Referencie nos nós

```json
{
  "config": {
    "connection_id": "{{vars.conexao_destino}}"
  }
}
```

### 3. Clone sem mapeamento

Ao clonar o template para um projeto, **nenhum mapeamento é necessário** — as variáveis
são copiadas integralmente e os valores concretos são fornecidos pelo consultor no momento
da execução via `variable_values`.

```http
POST /workflows/{template_id}/clone
{
  "target_project_id": "..."
}
```

---

## Fluxo legado (connection_mapping)

Templates que ainda usam UUIDs fixos precisam do `connection_mapping` no clone:

```http
POST /workflows/{template_id}/clone
{
  "target_project_id": "...",
  "connection_mapping": {
    "3fa85f64-5717-...": "uuid-da-conexao-do-projeto"
  }
}
```

O campo `connection_mapping` é **deprecated** — mantenha-o apenas para compatibilidade
com templates antigos. Novos templates devem sempre usar variáveis.

---

## Comportamento de _deep_replace_connections

A função `_deep_replace_connections` percorre o JSON da definição substituindo
`connection_id` cujo valor esteja no mapeamento. Referências `{{vars.X}}` **nunca**
aparecem no mapeamento e portanto são sempre preservadas sem modificação.

---

## Migração de templates existentes

Para migrar um template legado para usar variáveis:

1. Identifique os nós com `connection_id` fixo
2. Adicione uma variável `type: "connection"` em `definition.variables`
3. Substitua o UUID por `"{{vars.NOME_DA_VARIAVEL}}"`
4. Publique o template atualizado

Após a migração, clones novos não precisarão mais de `connection_mapping`.
