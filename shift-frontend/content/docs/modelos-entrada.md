---
title: Modelos de Entrada
order: 3
---

# Modelos de Entrada

Um Modelo de Entrada é o **contrato** do que o cliente deve mandar. Ele descreve as colunas, tipos e quais são obrigatórias. Quando você vincula um modelo a um nó CSV/Excel, o Shift valida o arquivo recebido **antes** de processar.

## Por que usar

Sem modelo:
- Cliente manda CSV com `cnpjcpf` em vez de `cnpj_cpf`
- Nó CSV passa de boa (são só dados)
- Nó **Mapper** quebra com erro críptico: `Binder Error: Referenced column "cnpj_cpf" not found`
- Você gasta meia hora descobrindo que o cliente errou no nome da coluna

Com modelo vinculado:
- Cliente manda CSV com `cnpjcpf` em vez de `cnpj_cpf`
- Nó CSV **falha imediatamente**: `Coluna obrigatória ausente: cnpj_cpf. Presentes: id, nome, cnpjcpf, email…`
- Você manda print pro cliente, ele corrige, próxima execução roda

Em **uma execução real de migração** essa diferença vale ouro.

## Como criar

Menu **Modelos de Entrada** → **Novo Modelo**:

1. **Nome**: descritivo (`clientes-acme`, `produtos-padrao`)
2. **Tipo**: CSV ou Excel (o tipo é fixado após salvar — escolha bem)
3. **Identificador**: usado em logs e mensagens
4. **Colunas**:
   - **Nome**: bate exatamente com o cabeçalho esperado
   - **Tipo**: text, number, integer, date, datetime, boolean
   - **Obrigatório**: marca se sem ela a migração não roda

## Excel multi-sheet

Modelos Excel podem ter **várias abas** (`sheets`). Cada aba é validada separadamente pelo nó Excel correspondente. Cenário: arquivo do cliente tem uma aba `Clientes` e uma `Produtos` — você cria 2 nós Excel apontando pro mesmo arquivo, cada um com aba diferente, ambos validando contra o mesmo modelo.

## Como vincular

No nó CSV/Excel, campo **Modelo de entrada (opcional)**: dropdown lista todos os modelos do tipo correspondente. Ao selecionar:

- Mostra **mensagem de validação na execução** abaixo do dropdown
- No Excel: o **Nome da Aba** passa a vir do modelo (1 sheet = auto-set, N sheets = dropdown limitado)

## O que é validado hoje (v1)

| Regra | Comportamento |
|---|---|
| Coluna `obrigatória` ausente no arquivo | **Falha** com mensagem específica |
| Coluna `obrigatória` presente | OK |
| Coluna `opcional` ausente | OK |
| Coluna **extra** no arquivo | OK (registra log info) |
| Tipo divergente | **Não validado** ainda — fica pra próxima fase |
| Comparação de nomes | **Case-insensitive** (`Email` casa com `email`) |

## Limites e quotas

Veja [FAQ](faq) seção "Limites de upload".
