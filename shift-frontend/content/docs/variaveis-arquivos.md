---
title: Variáveis e arquivos no runtime
order: 4
---

# Variáveis e arquivos no runtime

Quando o arquivo do cliente **muda a cada execução** (relatório mensal, lista nova de produtos, etc), você não pode hardcodar o caminho no nó. Use **variáveis tipo arquivo** — o Shift pede o upload na hora de executar.

## Cenário típico

> "Todo dia 5 do mês, o financeiro me manda o `pagamentos-2026-XX.csv`. Eu quero rodar o mesmo fluxo, só trocando o arquivo."

## Como configurar

### 1. Crie a variável no fluxo

No editor, abra **Variáveis do workflow** (no painel lateral). Adicione:

- **Nome**: `arquivo_pagamentos` (sem espaços, sem acento)
- **Tipo**: **Arquivo** (file_upload)
- **Obrigatória**: sim

Salve.

### 2. Aponte o nó CSV pra essa variável

No nó CSV, campo **Arquivo CSV**:

- Aba **Variável**
- Selecione `arquivo_pagamentos` no dropdown
- O campo fica com o chip violeta `arquivo_pagamentos`

### 3. Execute

Botão **Executar**. Modal abre solicitando upload pra cada variável tipo arquivo. Faz upload do CSV do mês, fluxo roda.

Próxima execução: novo upload, mesmo fluxo. **O nó não precisa ser editado**.

## Como funciona internamente

Quando você seleciona "Variável", o nó armazena:

```
url: "{{vars.arquivo_pagamentos}}"
```

Em runtime:

1. Modal de execução pede o arquivo
2. Frontend faz upload → backend retorna `shift-upload://abc-123-...`
3. Variável vira `arquivo_pagamentos = "shift-upload://abc-123"`
4. Backend resolve `{{vars.arquivo_pagamentos}}` → caminho real do arquivo no servidor
5. Nó CSV lê normalmente

## Workflows agendados (cron)

Se o fluxo dispara via cron (sem usuário no controle), variáveis tipo arquivo **não funcionam** (não tem ninguém pra fazer upload). Pra esses casos:

- Use **URL/Path** no campo Arquivo CSV — aponta direto pra um bucket S3 ou pasta de rede onde o arquivo é depositado
- Ou agenda só o **template do fluxo** e dispara via API com `variable_values` pré-resolvidos

## Quando usar cada modo do Arquivo CSV

| Modo | Quando |
|---|---|
| **URL / Path** | Arquivo num bucket S3, servidor de arquivos, FTP. Ideal pra automações sem humano. |
| **Do projeto** | Arquivo já enviado antes (ex: catálogo padrão que vale o ano todo). |
| **Enviar** | Arquivo único no momento do design — vai ser sempre o mesmo. |
| **Variável** | Arquivo muda a cada execução, com humano disparando. |
