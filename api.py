"""
Microserviço HTTP que o n8n chama via HTTP Request node.
Roda na porta 8000 do host.
"""
import logging
from pathlib import Path

import db
from apply import apply_sync
from collect import collect_jobs, load_profile_and_policy
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel
from triage import filter_hard, score_job

load_dotenv(Path(__file__).parent / ".env")
db.init_db()

logger = logging.getLogger(__name__)

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
    """Coleta vagas brutas e salva no banco com status 'collected'."""
    jobs = collect_jobs()
    for j in jobs:
        url = j["url"]
        db.upsert_job(url, j["title"], j["company"], j["platform"], 0)
        db.update_status(url, "collected")
    logger.info("Coleta concluida com %d vagas", len(jobs))
    return {"jobs": jobs, "total": len(jobs)}


@app.post("/triage")
def triage():
    """Triagem em duas camadas das vagas com status='collected'."""
    _, policy_md = load_profile_and_policy()
    raw_jobs = {j["url"]: j for j in collect_jobs()}

    triaged = []
    for url, job in raw_jobs.items():
        db_job = db.get_job(url)
        if not db_job or db_job["status"] != "collected":
            continue

        if not filter_hard(job):
            logger.info("Vaga %s descartada na camada hardcoded", url)
            continue

        score = score_job(
            title=job["title"],
            company=job["company"],
            city=job.get("city", ""),
            modality=job.get("modality", ""),
            description=job.get("description", ""),
            policy_md=policy_md,
        )
        if score < 0:
            logger.info("Vaga %s descartada pelo LLM (score=%s)", url, score)
            continue

        db.upsert_job(url, job["title"], job["company"], job["platform"], score)
        db.update_status(url, "queued")
        triaged.append({**job, "score": score})

    logger.info("Triagem concluiu com %d vagas aprovadas", len(triaged))
    return {"jobs": triaged, "total": len(triaged)}


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
