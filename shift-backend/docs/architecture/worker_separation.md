# Separação API ↔ Worker — Documento de Design (Sprint 4.3)

**Status:** Decisão pendente — não implementar antes de validar este documento.

---

## 1. Contexto

O Shift executa workflows via `asyncio` dentro do mesmo processo FastAPI, materializa
dados em DuckDB em `/tmp/shift/executions/{execution_id}/` e emite eventos SSE
diretamente da coroutine de execução para o cliente. Isso simplifica o deploy e
eliminou latências de rede entre componentes — mas cria um gargalo quando o volume de
execuções concorrentes cresce.

Este documento responde às cinco perguntas do épico antes de qualquer linha de código.

---

## 2. Qual fila usar?

### Opções avaliadas

| Fila | Prós | Contras |
|------|------|---------|
| **Redis Streams** | Leve, TTL nativo, pub/sub no mesmo broker | Requer Redis infra; ACK manual; sem DLQ nativo |
| **RabbitMQ** | DLQ nativo, confirmação robusta, AMQP padrão | Infra separada; complexidade de setup |
| **Celery** | Ecosistema Python maduro, retry/ETA, flower UI | Worker síncrono por padrão; asyncio via gevent/eventlet é frágil |
| **Dramatiq** | Primeira classe asyncio, simples, Django-friendly | Menor ecosistema; sem Redis Streams (usa listas) |
| **arq** (Async rq) | 100 % asyncio, Redis, simples | Pouco adotado; sem broadcast nativo |

### Recomendação: **arq + Redis**

O runner já é puro `asyncio`. `arq` executa jobs como coroutines nativas sem threads ou
gevent — sem mudança na semântica do código existente. Redis é necessário de qualquer
forma para rate limiting multi-réplica (`RATE_LIMIT_STORAGE_URI`). O overhead de
infraestrutura é mínimo.

**Alternativa aceitável:** Redis Streams com worker asyncio caseiro — mais controle,
mesma infra, mas exige implementar retry e DLQ.

**Descartar:** Celery — o modelo thread/process não combina com o runner asyncio e
causou bugs difíceis de reproduzir em projetos similares.

---

## 3. Como compartilhar DuckDB entre worker e API?

O DuckDB é materializado localmente (arquivo `.duckdb` em `/tmp/shift/`). Quando API
e worker rodam em processos ou hosts diferentes, isso quebra: o worker gera o arquivo,
mas a API não tem acesso para servir previews.

### Opções

| Estratégia | Latência adicional | Custo | Complexidade |
|---|---|---|---|
| **Volume compartilhado (NFS/EFS)** | ~1 ms (LAN) | Médio | Baixo — mount idêntico |
| **S3/MinIO: upload pós-execução** | ~100–500 ms por arquivo | Baixo | Médio — download sob demanda |
| **Redis: metadados + S3: dados** | Melhor dos dois mundos | Médio | Alto |
| **Colocation (worker no mesmo host)** | Zero | Mínimo | Mínimo — evita o problema |

### Recomendação: **Volume compartilhado (curto prazo) → S3 (longo prazo)**

Para o volume atual (N consultores × M execuções/dia, ver §5), colocation ou um único
volume compartilhado é suficiente. Quando escalar horizontalmente, mover para S3:
o `extraction_service` grava em DuckDB local, faz upload ao finalizar, apaga local.
O endpoint de preview baixa sob demanda e serve com cache local de 5 min.

---

## 4. Como o frontend recebe SSE se o worker é outro processo?

Hoje: `event_sink` é uma coroutine que escreve numa `asyncio.Queue` drenada pelo
`StreamingResponse` da rota `/test`. Isso só funciona dentro do mesmo processo.

### Opções

| Estratégia | Latência | Complexidade |
|---|---|---|
| **Redis pub/sub por execution_id** | ~1–5 ms | Baixo — cliente faz SUBSCRIBE, API faz proxy |
| **WebSocket Gateway separado** | ~1–5 ms | Alto — novo serviço, autenticação, reconexão |
| **Polling (GET /executions/{id}/status)** | Depende do intervalo | Mínimo — já existe |
| **Server-Sent Events via Redis** | ~1–5 ms | Médio — Redis como message bus |

### Recomendação: **Redis pub/sub**

O worker publica eventos no canal `shift:execution:{execution_id}`. A API subscreve
ao canal quando o cliente abre SSE (`/workflows/{id}/test`) e faz proxy dos eventos.
O `event_sink` do runner vira um publisher Redis em vez de enfileirar localmente.

Implementação:
```
Worker → redis.publish(f"shift:execution:{exec_id}", json_event)
API    → redis.subscribe(f"shift:execution:{exec_id}") → StreamingResponse
```

Reconexão: o cliente já implementa `EventSource` com `lastEventId` — basta o worker
incluir `id:` nos eventos SSE.

---

## 5. Custo de infra vs. benefício

### Volume previsto (estimativa)

- 20 consultores ativos simultaneamente
- 5 execuções/hora por consultor = **100 execuções/hora**
- Duração média de 3 min = pico de ~5 execuções concorrentes

### Custo atual (zero separação)

- 1 instância EC2 t3.xlarge (4 vCPU, 16 GB): ~$120/mês
- Cobre pico confortavelmente com o limite `SHIFT_MAX_CONCURRENT_EXECUTIONS=4`
- Sem Redis, sem fila, sem latência extra

### Custo com separação (estimativa mínima)

| Componente | Serviço | Custo/mês |
|---|---|---|
| API (2 réplicas) | t3.medium | $60 |
| Worker (2 réplicas) | t3.xlarge | $240 |
| Redis (ElastiCache r7g.large) | ElastiCache | $120 |
| EFS ou volume compartilhado | EFS (20 GB) | $6 |
| **Total** | | **~$426/mês** |

**Overhead:** +$306/mês (+255%) para o mesmo volume.

### Recomendação

**Não separar agora.** O gargalo atual é RAM/CPU, não arquitetura. O limite de
concorrência resolve o problema sem custo adicional. Reavaliar quando:

1. Pico de execuções concorrentes superar 10 regularmente, OU
2. Execuções longas (>10 min) bloquearem execuções curtas — implementar `max_instances=1`
   por projeto antes de separar.

---

## 6. Plano de migração incremental (quando necessário)

**Fase 0 (agora):** Status quo — asyncio in-process, sem mudança.

**Fase 1:** Adicionar Redis ao stack (necessário de qualquer forma para rate limiting
multi-réplica e cache de sessão). Zero breaking change.

**Fase 2:** Extrair o runner para um módulo `app/worker/`. O dispatcher passa a
publicar um `WorkflowJob` via `arq.enqueue`. A rota `/execute` retorna 202 imediatamente.
SSE usa Redis pub/sub. O DuckDB ainda usa `/tmp` local — worker e API no mesmo host.

**Fase 3:** Mover para volume compartilhado (EFS) ou S3. Workers tornam-se stateless.
Escalonamento horizontal independente de API e workers.

Cada fase é deployável independentemente sem downtime. A fase 2 pode ser feature-flagged
via `SHIFT_WORKER_MODE=inline|queue` para rollback seguro.

---

*Entregue para revisão. Implementação da Fase 2+ requer aprovação após monitoramento de
produção da Fase 0.*
