---
title: FAQ — Perguntas frequentes
order: 5
---

# FAQ — Perguntas frequentes

## Por que meu Mapper não acha a coluna que eu defini?

Os nomes batem **exatamente**: incluindo case e underscore. Se a coluna do CSV é `cnpj_cpf` mas o Mapper procura `CnpjCpf`, ele não acha.

**Como debugar**:
1. Execute só o nó **CSV** (botão Executar no painel)
2. Aba **Tabela** mostra as colunas reais
3. Compare com o que o Mapper espera

Pra evitar esse problema, vincule um [Modelo de Entrada](modelos-entrada) ao nó CSV — ele falha com mensagem clara antes do Mapper.

## O que é `shift-upload://...` que aparece no campo Arquivo?

É a referência interna pro arquivo que você enviou (ou que uma variável apontou). Não precisa entender, não precisa mexer. Quando aparece na UI como chip "📎 nome-do-arquivo.csv", está funcionando.

## Limites de upload

| Limite | Default | Configurável? |
|---|---|---|
| Tamanho por arquivo | 500 MB | Sim, via env |
| Quota total por projeto | 5 GB | Sim, via env |
| TTL (arquivos não usados) | 30 dias | Sim, via env |
| Extensões aceitas | .csv, .tsv, .xlsx, .xls, .json, .parquet, .txt | Não |

Arquivos não acessados há mais de 30 dias são removidos automaticamente. Se um fluxo agendado usar o arquivo, isso atualiza o "último acesso" e protege da limpeza.

## "Modo arrastar" vs "Modo seleção" — qual usar?

- **Arrastar** (ícone mãozinha): clicar e arrastar move o canvas. Selecionar nó precisa de **um clique** no nó.
- **Seleção** (ícone seta): clicar e arrastar **seleciona múltiplos nós**. Pra mover o canvas use **espaço + arrastar**.

Default sugerido pra quem está aprendendo: Arrastar.

## Posso editar o tipo de um Modelo de Entrada depois de salvar?

Não. Quando o modelo já foi salvo, o tipo (CSV/Excel/Dados) fica bloqueado. Isso preserva integridade dos fluxos que já apontam pra ele.

Se você precisa trocar o tipo: crie um modelo novo + ajuste os fluxos que apontavam pro antigo + delete o antigo.

## Por que minha sandbox de código (Python) não inicia?

A sandbox precisa de **acesso ao Docker socket** do host. Se você está rodando o backend localmente (sem Docker), a sandbox cai num "cold path" mais lento, mas funciona. Se estiver no Docker e a sandbox falhar, é provavelmente o `DOCKER_GID` do `.env` desalinhado com o GID real do socket no host.

Verificação:
```bash
docker compose exec shift-backend stat -c "%g" /var/run/docker.sock
```

Atualize `DOCKER_GID` no `.env` com o número que aparecer.

## Preciso fechar o navegador pra cancelar uma execução?

Não. Em fluxos rodando via "Executar" do canvas, o painel inferior tem botão de cancelar. Em fluxos agendados, vá em **Execuções** → encontre a execução em andamento → cancelar.

## Onde vejo o histórico de execuções?

Aba **Execuções** no editor do fluxo. Lista cada run com status, duração, snapshot do que rodou. Snapshots são imutáveis: mesmo se você editar o fluxo depois, o histórico mostra como **estava** quando rodou.

## Algum erro novo que não está aqui?

Manda print pro time de desenvolvimento. Se a mensagem de erro for clara, copia ela. Se estiver críptica, copia o **stack trace** completo do log.
