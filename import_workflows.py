#!/usr/bin/env python3
"""Import n8n workflows via API, stripping read-only fields."""
import json, glob, sys
import urllib.request, urllib.error

N8N_URL = "http://localhost:5678"
API_KEY = "n8n_api_7314bfbba89b407e530f0d8232524ee61856cd58ab4a4b05"
WORKFLOWS_DIR = "/home/copilot/job-hunter/n8n-workflows"
READ_ONLY = {"active", "id", "tags", "createdAt", "updatedAt", "versionId"}

def api(method, path, body=None):
    url = N8N_URL + path
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method,
        headers={"X-N8N-API-KEY": API_KEY, "Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

print("=== Importando workflows no n8n ===")
files = sorted(glob.glob(f"{WORKFLOWS_DIR}/*.json"))
for f in files:
    wf = json.load(open(f))
    name = wf.get("name", f)
    print(f"  Importando: {name} ... ", end="", flush=True)
    payload = {k: v for k, v in wf.items() if k not in READ_ONLY}
    try:
        result = api("POST", "/api/v1/workflows", payload)
        wf_id = result["id"]
        print(f"OK (id={wf_id})")
        try:
            api("PATCH", f"/api/v1/workflows/{wf_id}", {"active": True})
        except Exception as e:
            print(f"    (aviso ao ativar: {e})")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"FALHOU: {e.code} {body}")
    except Exception as e:
        print(f"ERRO: {e}")

print("\n=== Concluído! ===")
