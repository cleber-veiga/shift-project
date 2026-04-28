---
title: Conceitos rápidos
order: 1
---

# Conceitos rápidos

Pra começar a usar o Shift, basta entender 5 coisas. Se você já mexe com SQL, vai pegar rápido.

## Workspace

Um agrupamento administrativo — geralmente sua **organização** ou **time**. Tem permissões, conexões compartilhadas e modelos de entrada. Pense como o **schema** de um banco.

## Projeto

Dentro de um workspace, um projeto representa um **cliente** ou uma **migração** específica. Os fluxos de dados ficam no projeto. Equivale a um **conjunto de scripts** organizados pra um trabalho.

## Conexão

Apontamento pra um banco externo (Oracle, SQL Server, Postgres, Firebird, MySQL). Você cadastra **uma vez** com credenciais e reusa em N fluxos. Pense como **DSN/connection string**, mas guardada e versionada.

## Fluxo (Workflow)

A peça central. Um diagrama de **passos conectados** que extrai dados, transforma e carrega. Equivale a um **script SQL com várias etapas** — só que cada etapa é um nó visual com sua configuração.

> **Analogia SQL**: imagine um `WITH` chained:
> `WITH origem AS (SELECT ...), filtrado AS (SELECT ... FROM origem WHERE ...), final AS (...) INSERT INTO destino SELECT * FROM final`
> Isso é um fluxo: cada CTE é um nó, conectados na ordem.

## Nó (Node)

Cada **caixinha** num fluxo. Tem 4 categorias:

- **Gatilhos** — quando o fluxo dispara (manual, cron, webhook)
- **Ações** — entrada de dados (SQL, CSV, Excel, API)
- **Transformação** — manipula linhas (mapper, filter, aggregator, dedup)
- **Armazenamento** — saída (insert em tabela, escreve arquivo, etc)

Conecta-se nó com nó arrastando da bolinha de saída pra de entrada. O dado flui.

## Próximo passo

Veja [Sua primeira migração: CSV → Postgres](primeira-migracao) pra colocar a mão na massa.
