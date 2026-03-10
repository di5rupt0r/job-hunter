#!/bin/bash
# Script de configuração final das credenciais
# Execute UMA VEZ após obter Telegram e Trello credentials
set -e

ENV_FILE="$HOME/job-hunter/.env"
COMPOSE_FILE="$HOME/docker/n8n/docker-compose.yml"

echo "=== Setup de Credenciais — Automação de Candidaturas ==="
echo ""

# ── Lê credenciais existentes ─────────────────────────────────────────────────
GITHUB_TOKEN=$(grep '^GITHUB_TOKEN=' "$ENV_FILE" | cut -d= -f2)

# ── Input do usuário ─────────────────────────────────────────────────────────
read -p "Telegram Bot Token (de @BotFather): " TELEGRAM_BOT_TOKEN
read -p "Telegram Chat ID: " TELEGRAM_CHAT_ID
read -p "Trello API Key (trello.com/app-key): " TRELLO_API_KEY
read -p "Trello Token (trello.com/app-key → Token): " TRELLO_TOKEN
echo ""
echo "Buscando boards disponíveis..."
curl -s "https://api.trello.com/1/members/me/boards?key=${TRELLO_API_KEY}&token=${TRELLO_TOKEN}&fields=name,id" \
  | python3 -c "import sys,json; [print(f'  {b[\"name\"]}: {b[\"id\"]}') for b in json.load(sys.stdin)]"
echo ""
read -p "ID do board 'Job Hunter' (copiado acima): " BOARD_ID
read -s -p "Senha para o painel n8n (pressione Enter para usar 'candidatura2026'): " N8N_PASS
N8N_PASS="${N8N_PASS:-candidatura2026}"
echo ""

# ── Atualiza ~/agent/.env ─────────────────────────────────────────────────────
sed -i "s|TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}|" "$ENV_FILE"
sed -i "s|TELEGRAM_CHAT_ID=.*|TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}|" "$ENV_FILE"
sed -i "s|TRELLO_API_KEY=.*|TRELLO_API_KEY=${TRELLO_API_KEY}|" "$ENV_FILE"
sed -i "s|TRELLO_TOKEN=.*|TRELLO_TOKEN=${TRELLO_TOKEN}|" "$ENV_FILE"
sed -i "s|TRELLO_BOARD_ID=.*|TRELLO_BOARD_ID=${BOARD_ID}|" "$ENV_FILE"

# ── Busca as listas existentes do board ──────────────────────────────────────
echo ""
echo "=== Lendo listas do board 'Job Hunter' (${BOARD_ID})... ==="

LISTS_JSON=$(curl -s "https://api.trello.com/1/boards/${BOARD_ID}/lists?key=${TRELLO_API_KEY}&token=${TRELLO_TOKEN}&fields=name,id")

if [ -z "$LISTS_JSON" ] || echo "$LISTS_JSON" | grep -q '"message"'; then
  echo "ERRO ao buscar listas. Resposta: $LISTS_JSON"
  exit 1
fi

declare -A NAME_TO_VAR=(
  ["Coletada"]="COLETADA"
  ["Triagem OK"]="TRIAGEM"
  ["Candidatando"]="CANDIDATANDO"
  ["Aguardando"]="AGUARDANDO"
  ["Teste"]="TESTE"
  ["Entrevista"]="ENTREVISTA"
  ["Aprovada"]="APROVADA"
  ["Recusada"]="RECUSADA"
  ["Bloqueada"]="BLOQUEADA"
)

declare -A LIST_IDS

while IFS='|' read -r LIST_NAME LIST_ID; do
  VAR="${NAME_TO_VAR[$LIST_NAME]}"
  if [ -n "$VAR" ]; then
    LIST_IDS[$VAR]="$LIST_ID"
    echo "  $LIST_NAME → $LIST_ID"
    sed -i "s|TRELLO_LIST_${VAR}=.*|TRELLO_LIST_${VAR}=${LIST_ID}|" "$ENV_FILE"
  fi
done < <(echo "$LISTS_JSON" | python3 -c "
import sys, json
for l in json.load(sys.stdin):
    print(l['name'] + '|' + l['id'])
")

# Verifica se todas as listas foram encontradas
REQUIRED_VARS=(TRIAGEM CANDIDATANDO AGUARDANDO COLETADA BLOQUEADA)
for VAR in "${REQUIRED_VARS[@]}"; do
  if [ -z "${LIST_IDS[$VAR]}" ]; then
    echo "AVISO: lista '${VAR}' não encontrada no board. Verifique os nomes das listas no Trello."
  fi
done

# ── Atualiza docker-compose.yml com todas as env vars ────────────────────────
echo ""
echo "=== Atualizando docker-compose.yml do n8n... ==="

cat > "$COMPOSE_FILE" << COMPOSE
services:
  n8n:
    image: n8nio/n8n:latest
    container_name: n8n
    restart: unless-stopped
    ports:
      - "5678:5678"
    environment:
      - N8N_BASIC_AUTH_ACTIVE=true
      - N8N_BASIC_AUTH_USER=admin
      - N8N_BASIC_AUTH_PASSWORD=${N8N_PASS}
      - GENERIC_TIMEZONE=America/Sao_Paulo
      - TZ=America/Sao_Paulo
      - N8N_LOG_LEVEL=warn
      - NODE_FUNCTION_ALLOW_EXTERNAL=*
      - N8N_RUNNERS_ENABLED=true
      # Trello
      - TRELLO_API_KEY=${TRELLO_API_KEY}
      - TRELLO_TOKEN=${TRELLO_TOKEN}
      - TRELLO_LIST_COLETADA=${LIST_IDS[COLETADA]}
      - TRELLO_LIST_TRIAGEM=${LIST_IDS[TRIAGEM]}
      - TRELLO_LIST_CANDIDATANDO=${LIST_IDS[CANDIDATANDO]}
      - TRELLO_LIST_AGUARDANDO=${LIST_IDS[AGUARDANDO]}
      - TRELLO_LIST_TESTE=${LIST_IDS[TESTE]}
      - TRELLO_LIST_ENTREVISTA=${LIST_IDS[ENTREVISTA]}
      - TRELLO_LIST_RECUSADA=${LIST_IDS[RECUSADA]}
      - TRELLO_LIST_APROVADA=${LIST_IDS[APROVADA]}
      - TRELLO_LIST_BLOQUEADA=${LIST_IDS[BLOQUEADA]}
      # Telegram
      - TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
    volumes:
      - /home/copilot/.n8n:/home/node/.n8n
    extra_hosts:
      - "host.docker.internal:host-gateway"
COMPOSE

# ── Restart n8n com nova config ───────────────────────────────────────────────
echo "=== Reiniciando n8n... ==="
cd "$HOME/docker/n8n" && docker compose down && docker compose up -d
sleep 8

# ── Reinicia serviço Python ───────────────────────────────────────────────────
sudo systemctl restart candidatura-agent
sleep 3
echo -n "Agent API: " && curl -s http://localhost:8000/health

# ── Importa workflows no n8n ─────────────────────────────────────────────────
echo ""
echo "=== Importando workflows n8n... ==="
N8N_ADMIN_PASSWORD="${N8N_PASS}" bash "$HOME/job-hunter/import_n8n_workflows.sh"

echo ""
echo "======================================="
echo "✅ Setup completo!"
echo "  Painel n8n : http://$(tailscale ip -4):5678"
echo "  Usuário    : admin"
echo "  Senha      : ${N8N_PASS}"
echo "  Trello     : https://trello.com/b/${BOARD_ID}"
echo ""
echo "  Para testar coleta manual:"
echo "    curl -s http://localhost:8000/collect | python3 -m json.tool | head -30"
echo "======================================="
