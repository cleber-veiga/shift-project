#!/usr/bin/env bash
# =============================================================================
# Demo: Build Session — IA criando 3 nós ghost e usuário confirmando
#
# Pré-requisitos:
#   - Backend rodando em http://localhost:8000
#   - Variáveis de ambiente abaixo preenchidas
#   - jq instalado (brew install jq / apt install jq)
#   - curl instalado
#
# Uso:
#   export AUTH_TOKEN="<seu JWT do login>"
#   export WORKFLOW_ID="<uuid do workflow no banco>"
#   bash demo/build-session-demo.sh
# =============================================================================

set -euo pipefail

BASE="${API_BASE_URL:-http://localhost:8000/api/v1}"
TOKEN="${AUTH_TOKEN:-SUBSTITUA_COM_SEU_JWT}"
WF="${WORKFLOW_ID:-SUBSTITUA_COM_UUID_DO_WORKFLOW}"

AUTH="Authorization: Bearer $TOKEN"
CT="Content-Type: application/json"

step() { echo; echo "━━━ $1 ━━━"; }

# -----------------------------------------------------------------------------
# 0. Verificação de saúde
# -----------------------------------------------------------------------------
step "0 — Health check"
curl -sf "$BASE/../health" | jq .

# -----------------------------------------------------------------------------
# 1. Abre uma janela SSE para observar eventos em tempo real (background)
#    Nota: substitua por seu cliente SSE favorito; aqui usamos curl simples.
# -----------------------------------------------------------------------------
step "1 — Abrindo SSE listener em background (ctrl+c no final para fechar)"
SSE_LOG=$(mktemp /tmp/sse_events.XXXXXX)
curl -sN \
  -H "$AUTH" \
  -H "Accept: text/event-stream" \
  "$BASE/workflows/$WF/definition/events" > "$SSE_LOG" &
SSE_PID=$!
echo "SSE PID: $SSE_PID  →  tail -f $SSE_LOG"
sleep 1

# -----------------------------------------------------------------------------
# 2. Cria a build session
# -----------------------------------------------------------------------------
step "2 — Criando build session"
SESSION_RESP=$(curl -sf -X POST "$BASE/workflows/$WF/build-sessions" \
  -H "$AUTH" -H "$CT" \
  -d '{"reason": "Demo de construcao automatizada"}')

echo "$SESSION_RESP" | jq .
SESSION_ID=$(echo "$SESSION_RESP" | jq -r .session_id)
echo "session_id = $SESSION_ID"

sleep 0.5

# -----------------------------------------------------------------------------
# 3. Adiciona 3 nós ghost (pending)
# -----------------------------------------------------------------------------
step "3 — Adicionando nó 1: filter"
N1=$(curl -sf -X POST "$BASE/workflows/$WF/build-sessions/$SESSION_ID/pending-nodes" \
  -H "$AUTH" -H "$CT" \
  -d '{
    "node_type": "filter",
    "position": {"x": 100, "y": 100},
    "data": {"label": "Filtro IA", "conditions": []}
  }')
echo "$N1" | jq .
NODE1_ID=$(echo "$N1" | jq -r .node_id)
echo "node1_id = $NODE1_ID"
sleep 0.3

step "3 — Adicionando nó 2: mapper"
N2=$(curl -sf -X POST "$BASE/workflows/$WF/build-sessions/$SESSION_ID/pending-nodes" \
  -H "$AUTH" -H "$CT" \
  -d '{
    "node_type": "mapper",
    "position": {"x": 350, "y": 100},
    "data": {"label": "Mapeamento IA", "mappings": []}
  }')
echo "$N2" | jq .
NODE2_ID=$(echo "$N2" | jq -r .node_id)
echo "node2_id = $NODE2_ID"
sleep 0.3

step "3 — Adicionando nó 3: sql_script"
N3=$(curl -sf -X POST "$BASE/workflows/$WF/build-sessions/$SESSION_ID/pending-nodes" \
  -H "$AUTH" -H "$CT" \
  -d '{
    "node_type": "sql_script",
    "position": {"x": 600, "y": 100},
    "data": {"label": "Script SQL IA", "query": "SELECT * FROM orders"}
  }')
echo "$N3" | jq .
NODE3_ID=$(echo "$N3" | jq -r .node_id)
echo "node3_id = $NODE3_ID"
sleep 0.3

# -----------------------------------------------------------------------------
# 4. Adiciona 2 arestas conectando os nós
# -----------------------------------------------------------------------------
step "4 — Adicionando aresta 1→2"
E1=$(curl -sf -X POST "$BASE/workflows/$WF/build-sessions/$SESSION_ID/pending-edges" \
  -H "$AUTH" -H "$CT" \
  -d "{
    \"source\": \"$NODE1_ID\",
    \"target\": \"$NODE2_ID\",
    \"source_handle\": \"success\"
  }")
echo "$E1" | jq .
sleep 0.2

step "4 — Adicionando aresta 2→3"
E2=$(curl -sf -X POST "$BASE/workflows/$WF/build-sessions/$SESSION_ID/pending-edges" \
  -H "$AUTH" -H "$CT" \
  -d "{
    \"source\": \"$NODE2_ID\",
    \"target\": \"$NODE3_ID\",
    \"source_handle\": \"success\"
  }")
echo "$E2" | jq .
sleep 0.2

# -----------------------------------------------------------------------------
# 5. Atualiza a config do nó 1 (simula refinamento da IA)
# -----------------------------------------------------------------------------
step "5 — Atualizando config do nó 1 (filter)"
curl -sf -X PUT "$BASE/workflows/$WF/build-sessions/$SESSION_ID/pending-nodes/$NODE1_ID" \
  -H "$AUTH" -H "$CT" \
  -d '{"data_patch": {"conditions": [{"field": "status", "op": "eq", "value": "active"}]}}' | jq .
sleep 0.3

# -----------------------------------------------------------------------------
# 6. IA sinaliza que terminou (build_ready — frontend mostra botões Confirmar/Cancelar)
# -----------------------------------------------------------------------------
step "6 — IA sinaliza build_ready"
curl -sf -X POST "$BASE/workflows/$WF/build-sessions/$SESSION_ID/ready" \
  -H "$AUTH" -H "$CT" | jq .

sleep 1

# -----------------------------------------------------------------------------
# 7. Usuário clica "Confirmar" (persiste no banco, emite node_added/edge_added)
# -----------------------------------------------------------------------------
step "7 — Usuário confirma o build"
CONFIRM=$(curl -sf -X POST "$BASE/workflows/$WF/build-sessions/$SESSION_ID/confirm" \
  -H "$AUTH" -H "$CT")
echo "$CONFIRM" | jq .

sleep 1

# -----------------------------------------------------------------------------
# 8. Mostra eventos SSE recebidos
# -----------------------------------------------------------------------------
step "8 — Eventos SSE capturados:"
cat "$SSE_LOG"

# Cleanup
kill "$SSE_PID" 2>/dev/null || true
rm -f "$SSE_LOG"

echo
echo "✓ Demo concluído. Workflow $WF agora contém 3 novos nós e 2 novas arestas."
