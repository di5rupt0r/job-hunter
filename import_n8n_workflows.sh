#!/bin/bash
# Importa os 5 workflows no n8n via API
# Execute após configurar credentials no n8n UI (Trello e Telegram)
set -e

N8N_URL="http://localhost:5678"
N8N_USER="admin"
N8N_PASS="${N8N_ADMIN_PASSWORD:-troca_isso_agora}"

WORKFLOWS_DIR="$HOME/agent/n8n-workflows"

echo "=== Importando workflows no n8n ==="

for f in "$WORKFLOWS_DIR"/*.json; do
  WFLOW_NAME=$(python3 -c "import json; print(json.load(open('$f'))['name'])")
  echo -n "  Importando: $WFLOW_NAME ... "

  RESULT=$(curl -s -X POST "${N8N_URL}/api/v1/workflows" \
    -u "${N8N_USER}:${N8N_PASS}" \
    -H "Content-Type: application/json" \
    -d @"$f")

  WF_ID=$(echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('id','ERROR'))" 2>/dev/null)

  if [ "$WF_ID" = "ERROR" ] || [ -z "$WF_ID" ]; then
    echo "FALHOU. Resposta: $RESULT"
  else
    echo "OK (id=$WF_ID)"
    # Ativa o workflow
    curl -s -X PATCH "${N8N_URL}/api/v1/workflows/${WF_ID}" \
      -u "${N8N_USER}:${N8N_PASS}" \
      -H "Content-Type: application/json" \
      -d '{"active": true}' > /dev/null
  fi
done

echo ""
echo "=== Workflows importados! Acesse: http://$(tailscale ip -4):5678 ==="
