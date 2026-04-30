# Agendamento

**Categoria:** Gatilho
**Tipo interno:** `cron`

## Descrição

Dispara o workflow automaticamente em horários definidos, sem intervenção manual. A programação é configurada por uma interface visual que gera a expressão cron equivalente — não é necessário saber escrever cron manualmente.

> **Importante:** o agendamento só fica ativo quando o workflow está em modo **Produção** e **Publicado**. Em modo de teste (draft), o nó pode ser executado manualmente mas não dispara sozinho.

## Saída produzida

O nó não carrega dados externos — apenas sinaliza que o fluxo foi iniciado pelo agendador:

```json
{
  "trigger_type": "cron",
  "status": "triggered",
  "cron_expression": "0 9 * * 1-5",
  "triggered_at": "2025-06-10T09:00:00+00:00",
  "data": {}
}
```

O timestamp `triggered_at` está sempre em UTC (ISO 8601). Converta-o em um nó posterior se precisar de outro fuso.

## Configurações

### Frequência

| Opção | Expressão gerada | Descrição |
|-------|-----------------|-----------|
| A cada 5 minutos | `*/5 * * * *` | Dispara 5, 10, 15... |
| A cada 10 minutos | `*/10 * * * *` | |
| A cada 15 minutos | `*/15 * * * *` | |
| A cada 30 minutos | `*/30 * * * *` | |
| A cada hora | `0 * * * *` | No minuto :00 de cada hora |
| A cada 2 horas | `0 */2 * * *` | |
| A cada 3 horas | `0 */3 * * *` | |
| A cada 6 horas | `0 */6 * * *` | |
| Horário específico | `<min> <hora> * * *` | Define hora e minuto exatos |

### Demais campos

| Campo | Tipo | Padrão | Descrição |
|-------|------|--------|-----------|
| Horário | `HH:MM` | `09:00` | Visível apenas com "Horário específico" |
| Fuso horário | string | `America/Sao_Paulo` | Referência para calcular a hora do disparo |
| Dias da semana | seleção múltipla | todos | Desmarque "Toda a semana" para escolher dias específicos |
| Meses | seleção múltipla | todos | Desmarque "Todos os meses" para restringir |
| Dias do mês | seleção múltipla (1–31) | todos | Desmarque "Todos os dias" para escolher datas específicas |

### Prévia das próximas execuções

A aba **Próximas execuções** exibe as 5 próximas disparadas previstas com base na expressão atual, convertidas para o horário local do navegador. Use para conferir se o agendamento está correto antes de publicar.

## Expressão cron gerada

A interface exibe a expressão cron resultante em tempo real (ex.: `0 9 * * 1-5`). Ela é gravada no campo `cron_expression` da configuração do nó e é o valor que o agendador (APScheduler) usa internamente.

## Limites e guardrails

- Selecionar dias da semana sem marcar "Toda a semana" e não escolher nenhum dia → erro de validação (o agendamento não é salvo).
- O mesmo vale para Meses e Dias do mês.
- Hora fora de 0–23 ou minuto fora de 0–59 → erro de validação.
- Dois workflows distintos podem ter o mesmo horário; não há conflito entre si.

## Observabilidade

A saída inclui `cron_expression` e `triggered_at`, disponíveis no painel de execução para auditoria.

<!-- screenshot: TODO -->
