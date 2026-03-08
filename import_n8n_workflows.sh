#!/bin/bash
# Importa os 5 workflows no n8n via API
set -e

N8N_URL="http://localhost:5678"
N8N_API_KEY="n8n_api_7314bfbba89b407e530f0d8232524ee61856cd58ab4a4b05"
WORKFLOWS_DIR="$HOME/job-hunter/n8n-workflows"

echo "=== Importando workflows no n8n ==="

for f in "$WORKFLOWS_DIR"/*.json; do
  WFLOW_NAME=$(python3 -c "import json; print(json.load(open('$f'))'name')")
  echo -n "  Importando: $WFLOW_NAME ... "

  # Strip read-only fields before POST
  BODY=$(python3 -c "
import json, sys
d = json.load(open(sys.argv[1]))
for k in [active, id, tags, createdAt, updatedAt, versionId]:
    d.pop(k, None)
print(json.dumps(d))
" "$f")

  RESULT=$(curl -s -X POST "${N8N_URL}/api/v1/workflows" \
    -H "X-N8N-API-KEY: ${N8N_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "$BODY")

  WF_ID=$(echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get(id,ERROR))" 2>/dev/null)

  if [ "$WF_ID" = "ERROR" ] || [ -z "$WF_ID" ]; then
    echo "FALHOU. Resposta: $RESULT"
  else
    echo "OK (id=$WF_ID)"
    curl -s -X PATCH "${N8N_URL}/api/v1/workflows/${WF_ID}" \
      -H "X-N8N-API-KEY: ${N8N_API_KEY}" \
      -H "Content-Type: application/json" \
      -d '{"active": true}' > /dev/null
  fi
done

echo ""
echo "=== Workflows importados! Acesse: http://$(tailscale ip -4):5678 ==="
