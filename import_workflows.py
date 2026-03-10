#!/usr/bin/env python3
# Importa e ativa todos os workflows do diretório n8n-workflows/ via API do n8n.
# Uso: python3 import_workflows.py <n8n_url> <api_key> <workflows_dir>
import json, glob, sys
import urllib.request, urllib.error

N8N_URL    = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5678"
API_KEY    = sys.argv[2] if len(sys.argv) > 2 else ""
WORKFLOWS_DIR = sys.argv[3] if len(sys.argv) > 3 else "./n8n-workflows"
READ_ONLY  = {"active", "id", "tags", "createdAt", "updatedAt", "versionId"}
HEADERS    = {"X-N8N-API-KEY": API_KEY, "Content-Type": "application/json"}


def api(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        N8N_URL + path, data=data, method=method, headers=HEADERS
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()[:300]}")


# ── Deleta workflows existentes ───────────────────────────────────────────────
print("=== Removendo workflows existentes ===")
try:
    existing = api("GET", "/api/v1/workflows").get("data", [])
    for wf in existing:
        wf_id = wf["id"]
        try:
            api("DELETE", f"/api/v1/workflows/{wf_id}")
            print(f"  Removido id={wf_id}")
        except Exception as e:
            print(f"  Aviso ao remover {wf_id}: {e}")
except Exception as e:
    print(f"  Aviso ao listar workflows: {e}")

# ── Importa e ativa ───────────────────────────────────────────────────────────
print("\n=== Importando workflows ===")
errors = 0
for f in sorted(glob.glob(f"{WORKFLOWS_DIR}/*.json")):
    wf = json.load(open(f))
    name = wf.get("name", f)
    print(f"  {name} ... ", end="", flush=True)
    payload = {k: v for k, v in wf.items() if k not in READ_ONLY}
    try:
        result = api("POST", "/api/v1/workflows", payload)
        wf_id = result["id"]
        try:
            # n8n 2.x usa POST /activate (não PATCH)
            api("POST", f"/api/v1/workflows/{wf_id}/activate")
        except Exception as e:
            print(f"OK (id={wf_id}, aviso ao ativar: {e})")
            continue
        print(f"OK (id={wf_id})")
    except Exception as e:
        print(f"FALHOU: {e}")
        errors += 1

print(f"\n=== Concluído! ({errors} erros) ===")
sys.exit(1 if errors else 0)
