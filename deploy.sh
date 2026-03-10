#!/bin/bash
# Reinicia toda a automação após git pull.
# Uso: bash deploy.sh
set -euo pipefail

# Resolve project dir from the script itself so sudo doesn't break $HOME
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_USER="$(stat -c '%U' "$SCRIPT_DIR")"
PROJECT_HOME="$(getent passwd "$PROJECT_USER" | cut -d: -f6)"

COMPOSE_FILE="$PROJECT_HOME/docker/n8n/docker-compose.yml"
N8N_URL="http://localhost:5678"
N8N_API_KEY="n8n_api_7314bfbba89b407e530f0d8232524ee61856cd58ab4a4b05"
WORKFLOWS_DIR="$SCRIPT_DIR/n8n-workflows"
VENV_DIR="$SCRIPT_DIR/venv"  # alinhado com o ExecStart da unit systemd

log()  { echo "[deploy] $*"; }
ok()   { echo "[deploy] ✓ $*"; }
fail() { echo "[deploy] ✗ $*" >&2; exit 1; }

# ── Pré-requisito: .env deve existir ──────────────────────────────────────────
if [ ! -f "$SCRIPT_DIR/.env" ]; then
  fail ".env não encontrado em $SCRIPT_DIR/.env — copie .env.example e preencha as credenciais:
    cp $SCRIPT_DIR/.env.example $SCRIPT_DIR/.env"
fi

# ── 1. Dependências Python ────────────────────────────────────────────────────
log "Atualizando dependências Python..."
if [ ! -f "$VENV_DIR/bin/pip" ]; then
  log "venv não encontrado — criando em $VENV_DIR..."
  sudo -u "$PROJECT_USER" python3 -m venv "$VENV_DIR"
fi
# Atualiza pip+setuptools antes de instalar — necessário no Python 3.12
# (distutils foi removido; setuptools novo inclui o shim)
sudo -u "$PROJECT_USER" "$VENV_DIR/bin/pip" install -q --upgrade pip setuptools wheel

# python-jobspy pina NUMPY==1.26.3 que não tem wheel para Python 3.12.
# Instalamos tudo exceto jobspy primeiro (com numpy>=1.26.4 compatível),
# depois jobspy com --no-deps para ignorar o pin de numpy.
python3 -c "
lines = open('$SCRIPT_DIR/requirements.txt').read().splitlines()
without = [l for l in lines if 'python-jobspy' not in l]
open('/tmp/_reqs_no_jobspy.txt', 'w').write('\n'.join(without))
"
sudo -u "$PROJECT_USER" "$VENV_DIR/bin/pip" install -q -r /tmp/_reqs_no_jobspy.txt
rm -f /tmp/_reqs_no_jobspy.txt
sudo -u "$PROJECT_USER" "$VENV_DIR/bin/pip" install -q --no-deps python-jobspy==1.1.82
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
  curl -s -X DELETE "${N8N_URL}/api/v1/workflows/${WF_ID}" \
    -H "X-N8N-API-KEY: ${N8N_API_KEY}" >/dev/null || true
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

  RESULT=$(curl -s -X POST "${N8N_URL}/api/v1/workflows" \
    -H "X-N8N-API-KEY: ${N8N_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "$BODY")

  WF_ID=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)

  if [ -z "$WF_ID" ]; then
    echo "FALHOU."
    echo "  Resposta: $(echo "$RESULT" | head -c 200)"
  else
    # n8n 2.x: ativação via POST /activate (não PATCH)
    curl -s -X POST "${N8N_URL}/api/v1/workflows/${WF_ID}/activate" \
      -H "X-N8N-API-KEY: ${N8N_API_KEY}" >/dev/null || true
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
