"""
Microserviço HTTP que o n8n chama via HTTP Request node.
Roda na porta 8000 do host.
"""
from fastapi import FastAPI
from pydantic import BaseModel
from pathlib import Path
import db
from collect import collect_and_score
from apply import apply_sync
from dotenv import load_dotenv
import os

load_dotenv(Path(__file__).parent / ".env")
db.init_db()

app = FastAPI(title="Candidatura Agent API")


class ApplyRequest(BaseModel):
    url: str
    title: str
    company: str
    trello_card_id: str | None = None


class StatusUpdate(BaseModel):
    url: str
    status: str
    notes: str | None = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/collect")
def collect():
    """Coleta vagas, faz score e retorna lista. N8n cria cards no Trello."""
    jobs = collect_and_score()
    for j in jobs:
        db.upsert_job(j["url"], j["title"], j["company"], j["platform"], j["score"])
    return {"jobs": jobs, "total": len(jobs)}


@app.post("/apply")
def apply(req: ApplyRequest):
    """
    Executa candidatura. Retorna:
    - {"result": "SUCCESS"}
    - {"result": "CAPTCHA_DETECTED", "retry_count": N, "new_status": "queued"|"blocked"}
    - {"result": "ERROR", "detail": "..."}
    """
    job = db.get_job(req.url)
    if not job:
        db.upsert_job(req.url, req.title, req.company, "manual", 100, req.trello_card_id)

    db.update_status(req.url, "applying")
    result = apply_sync(req.url, req.title, req.company)

    if result == "SUCCESS":
        db.update_status(req.url, "waiting")
        return {"result": "SUCCESS"}
    elif result == "CAPTCHA_DETECTED":
        retry_count, new_status = db.increment_retry(req.url)
        return {
            "result": "CAPTCHA_DETECTED",
            "retry_count": retry_count,
            "new_status": new_status,
        }
    else:
        db.update_status(req.url, "queued", notes=result)
        return {"result": "ERROR", "detail": result}


@app.post("/status")
def update_status(req: StatusUpdate):
    """N8n atualiza status de uma vaga (ex: resposta recebida por email)."""
    db.update_status(req.url, req.status, req.notes)
    return {"ok": True}


@app.get("/pending-retry")
def pending_retry():
    """Retorna vagas que falharam com CAPTCHA e estão aguardando retry."""
    jobs = db.get_pending_retry()
    return {"jobs": [dict(j) for j in jobs]}
