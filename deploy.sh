#!/bin/bash
# Reinicia toda a automação após git pull.
# Uso: bash deploy.sh
set -euo pipefail

COMPOSE_FILE="$HOME/docker/n8n/docker-compose.yml"
N8N_URL="http://localhost:5678"
N8N_API_KEY="n8n_api_7314bfbba89b407e530f0d8232524ee61856cd58ab4a4b05"
WORKFLOWS_DIR="$HOME/job-hunter/n8n-workflows"
VENV_DIR="$HOME/job-hunter/.venv"

log()  { echo "[deploy] $*"; }
ok()   { echo "[deploy] ✓ $*"; }
fail() { echo "[deploy] ✗ $*" >&2; exit 1; }

# ── 1. Dependências Python ────────────────────────────────────────────────────
log "Atualizando dependências Python..."
if [ -f "$VENV_DIR/bin/pip" ]; then
  "$VENV_DIR/bin/pip" install -q -r "$HOME/job-hunter/requirements.txt"
elif command -v uv &>/dev/null; then
  uv pip install -q -r "$HOME/job-hunter/requirements.txt"
else
  pip install -q -r "$HOME/job-hunter/requirements.txt"
fi
ok "Dependências atualizadas."

# ── 2. Reinicia serviço Python ────────────────────────────────────────────────
log "Reiniciando candidatura-agent..."
if sudo systemctl restart candidatura-agent; then
  sleep 3
  if curl -sf http://localhost:8000/health >/dev/null; then
    ok "Agent API respondendo em :8000"
  else
    fail "Agent API não respondeu em :8000 — cheque: journalctl -u candidatura-agent -n 50"
  fi
else
  fail "Falha ao reiniciar candidatura-agent."
fi

# ── 3. Reinicia n8n ───────────────────────────────────────────────────────────
log "Reiniciando n8n..."
if [ ! -f "$COMPOSE_FILE" ]; then
  fail "docker-compose.yml não encontrado em $COMPOSE_FILE — execute setup_credentials.sh primeiro."
fi

cd "$(dirname "$COMPOSE_FILE")"
docker compose down --timeout 10
docker compose up -d
log "Aguardando n8n ficar pronto..."

N8N_READY=false
for i in $(seq 1 30); do
  if curl -sf "${N8N_URL}/healthz" >/dev/null 2>&1; then
    N8N_READY=true
    break
  fi
  sleep 2
done
$N8N_READY || fail "n8n não ficou pronto em 60s — cheque: docker logs n8n"
ok "n8n pronto em ${N8N_URL}"

# ── 4. Remove workflows antigos para evitar duplicatas ────────────────────────
log "Removendo workflows existentes..."
EXISTING=$(curl -sf "${N8N_URL}/api/v1/workflows" \
  -H "X-N8N-API-KEY: ${N8N_API_KEY}" | \
  python3 -c "import sys,json; [print(w['id']) for w in json.load(sys.stdin).get('data',[])]" 2>/dev/null || true)

for WF_ID in $EXISTING; do
  curl -sf -X DELETE "${N8N_URL}/api/v1/workflows/${WF_ID}" \
    -H "X-N8N-API-KEY: ${N8N_API_KEY}" >/dev/null
  log "  Removido workflow id=${WF_ID}"
done

# ── 5. Importa workflows ──────────────────────────────────────────────────────
log "Importando workflows..."
for f in "$WORKFLOWS_DIR"/*.json; do
  WFLOW_NAME=$(python3 -c "import json; print(json.load(open('$f'))['name'])")
  echo -n "[deploy]   $WFLOW_NAME ... "

  BODY=$(python3 - "$f" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
for k in ['active', 'id', 'tags', 'createdAt', 'updatedAt', 'versionId']:
    d.pop(k, None)
print(json.dumps(d))
PY
)

  RESULT=$(curl -sf -X POST "${N8N_URL}/api/v1/workflows" \
    -H "X-N8N-API-KEY: ${N8N_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "$BODY")

  WF_ID=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)

  if [ -z "$WF_ID" ]; then
    echo "FALHOU."
    echo "  Resposta: $RESULT"
  else
    curl -sf -X PATCH "${N8N_URL}/api/v1/workflows/${WF_ID}" \
      -H "X-N8N-API-KEY: ${N8N_API_KEY}" \
      -H "Content-Type: application/json" \
      -d '{"active": true}' >/dev/null
    echo "OK (id=${WF_ID})"
  fi
done

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "==========================================="
ok "Deploy concluído!"
echo "  Painel n8n : http://$(tailscale ip -4 2>/dev/null || echo 'localhost'):5678"
echo "  Agent API  : http://localhost:8000"
echo "==========================================="
