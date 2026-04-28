---
title: Sua primeira migração — CSV → Postgres
order: 2
---

# Sua primeira migração: CSV → Postgres

Cenário: o cliente te mandou um `clientes.csv` e precisa que o conteúdo entre numa tabela `cliente` no Postgres dele. Vamos do zero.

## 1. Cadastre a conexão de destino

Menu **Conexões** → **Nova conexão**. Preencha:

- **Tipo**: PostgreSQL
- **Host / porta / database / usuário / senha**: do banco do cliente
- **Nome**: algo como `postgres-cliente-acme`

Salve. A conexão é cifrada no servidor.

## 2. Cadastre o modelo de entrada (opcional, mas recomendado)

Menu **Modelos de Entrada** → **Novo Modelo**:

- **Tipo**: CSV
- **Nome**: `clientes`
- **Colunas**: descreva o que o CSV deve ter (id, nome, cnpj_cpf, email, etc)
- Marque **Obrigatórias** as colunas que sem elas a migração não roda

> **Por que vale**: na execução, o Shift compara o CSV recebido contra o modelo. Se o cliente mandar um arquivo com coluna renomeada, o erro vem **claro e cedo** ("coluna `cnpj_cpf` ausente, presentes: `cnpjcpf`...") em vez de quebrar 3 nós depois.

## 3. Crie o fluxo

Menu **Fluxos** → **Novo Fluxo**. Nome: `migracao-clientes-acme`.

## 4. Adicione os nós

No canvas:

1. **Gatilho Manual** (já vem por padrão)
2. **CSV** — arrasta da Biblioteca
3. **Mapper** — transforma os dados
4. **Bulk Insert** — escreve no Postgres

Conecta os 4 em sequência (manual → CSV → mapper → bulk insert).

## 5. Configure o nó CSV

Click no nó CSV. Painel direito:

- **Arquivo CSV**:
  - Aba **Enviar** se o arquivo já está no seu computador
  - Aba **Variável** se o arquivo vai ser diferente a cada execução (cliente manda novo todo mês)
- **Modelo de entrada**: selecione `clientes` (que você criou no passo 2)
- Outros campos: deixa default (delimitador `,`, com cabeçalho, encoding `utf-8`)

## 6. Configure o Mapper

Click no Mapper. Cada linha = uma coluna do destino:

| Destino | Origem | Transformação |
|---|---|---|
| `id` | `id` (do CSV) | — |
| `nome` | `nome` | Maiúsculo (opcional) |
| `cnpjcpf` | `cnpj_cpf` | Somente dígitos |
| `email` | `email` | Minúsculo |
| `data_cadastro` | `data_cadastro` | — (já é date no CSV) |

## 7. Configure o Bulk Insert

- **Conexão**: `postgres-cliente-acme`
- **Tabela**: `cliente`
- **Modo de conflito**: ajuste conforme a regra do cliente (insert / upsert / ignore)

## 8. Teste

Botão **Executar** no canvas (ou Executar em cada nó individual pra ver os dados). Aba **Tabela** no painel direito mostra as linhas após cada nó.

## 9. Programe (se for recorrente)

Se o cliente quer executar todo dia 1° do mês:

- Substitua o gatilho **Manual** por **Agendamento** (cron)
- Configure: `0 0 1 * *` (todo dia 1° à meia-noite)

Pronto. Próximas execuções vão acontecer sozinhas.

## E se o arquivo mudar a cada execução?

Use o modo **Variável** no nó CSV (passo 5). Veja [Variáveis e arquivos](variaveis-arquivos).
