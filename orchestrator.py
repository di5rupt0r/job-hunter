"""
Orquestrador Python — substitui os workflows n8n.

Flows agendados:
  - flow_collect_and_triage: cron 0 8,20 * * * America/Sao_Paulo
  - flow_execute_application: cron 0 */3 * * *  America/Sao_Paulo
  - flow_retry_captcha:       cron 0 */4 * * *  America/Sao_Paulo

A API FastAPI (api.py) continua rodando como processo separado via uvicorn.
Este orquestrador a consome via HTTP local.
"""
import logging
import os
import re
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import db
import integrations.telegram as telegram
import integrations.trello as trello

logger = logging.getLogger(__name__)

_API = os.environ.get("AGENT_API_BASE_URL", "http://localhost:8000")


# ---------------------------------------------------------------------------
# Flow 01 — Coleta + Cards + Triagem
# ---------------------------------------------------------------------------

def flow_collect_and_triage() -> None:
    try:
        _flow_collect_and_triage()
    except Exception:
        logger.exception("Erro no flow_collect_and_triage")


def _flow_collect_and_triage() -> None:
    resp = httpx.post(f"{_API}/collect", timeout=120)
    resp.raise_for_status()
    data = resp.json()

    if data["new"] >= 1:
        for job in data["new_jobs"]:
            desc = (
                f"🔗 URL: {job['url']}\n"
                f"🏭 Plataforma: {job['platform']}\n"
                f"📅 Coletada em: {_now()}"
            )
            card = trello.create_card(
                os.environ["TRELLO_LIST_COLETADA"],
                f"{job['title']} — {job['company']}",
                desc,
            )
            httpx.post(
                f"{_API}/card-id",
                json={"url": job["url"], "trello_card_id": card["id"]},
                timeout=30,
            )
            time.sleep(1)

    time.sleep(30)

    resp = httpx.post(f"{_API}/triage", timeout=300)
    resp.raise_for_status()
    triage_data = resp.json()

    if triage_data["total"] >= 1:
        for job in triage_data["jobs"]:
            score = job["score"]
            name = f"[{score}] {job['title']} — {job['company']}"
            card_id = job.get("trello_card_id")
            if card_id:
                trello.move_card(card_id, os.environ["TRELLO_LIST_TRIAGEM"], name=name)
            else:
                desc = (
                    f"🔗 URL: {job['url']}\n"
                    f"🏭 Plataforma: {job['platform']}\n"
                    f"📊 Score: {score}/100"
                )
                trello.create_card(os.environ["TRELLO_LIST_TRIAGEM"], name, desc)
            time.sleep(1)


# ---------------------------------------------------------------------------
# Flow 02 — Executor de Candidaturas (MVP: 1 card por execução)
# ---------------------------------------------------------------------------

def flow_execute_application() -> None:
    try:
        _flow_execute_application()
    except Exception:
        logger.exception("Erro no flow_execute_application")


def _flow_execute_application() -> None:
    cards = trello.list_cards(os.environ["TRELLO_LIST_TRIAGEM"])
    if not cards:
        return

    card = cards[0]
    url, title, company = _parse_card(card)

    trello.move_card(card["id"], os.environ["TRELLO_LIST_CANDIDATANDO"])

    resp = httpx.post(
        f"{_API}/apply",
        json={"url": url, "title": title, "company": company, "trello_card_id": card["id"]},
        timeout=300,
    )
    resp.raise_for_status()
    result = resp.json()

    match result["result"]:
        case "SUCCESS":
            trello.move_card(card["id"], os.environ["TRELLO_LIST_AGUARDANDO"])

        case "CAPTCHA_DETECTED":
            if result.get("new_status") == "blocked":
                trello.move_card(card["id"], os.environ["TRELLO_LIST_BLOQUEADA"])
                telegram.send_message(
                    f"⛔ VAGA BLOQUEADA (3 tentativas)\n{title} — {company}\n{url}"
                )
            else:
                trello.move_card(card["id"], os.environ["TRELLO_LIST_COLETADA"])
                telegram.send_message(
                    f"⚠️ CAPTCHA em {company}\n"
                    f"Retry {result.get('retry_count', '?')}/3 agendado para +4h\n{url}"
                )

        case _:
            trello.move_card(card["id"], os.environ["TRELLO_LIST_COLETADA"])
            telegram.send_message(
                f"❌ Erro ao candidatar: {company}\n{result.get('detail', '')}\n{url}"
            )


# ---------------------------------------------------------------------------
# Flow 03 — Retry de CAPTCHA
# ---------------------------------------------------------------------------

def flow_retry_captcha() -> None:
    try:
        _flow_retry_captcha()
    except Exception:
        logger.exception("Erro no flow_retry_captcha")


def _flow_retry_captcha() -> None:
    resp = httpx.get(f"{_API}/pending-retry", timeout=30)
    resp.raise_for_status()
    jobs = resp.json()["jobs"]

    for job in jobs:
        if job.get("trello_card_id"):
            trello.move_card(job["trello_card_id"], os.environ["TRELLO_LIST_TRIAGEM"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_card(card: dict) -> tuple[str, str, str]:
    """Extrai (url, title, company) de um card Trello."""
    url_match = re.search(r"🔗 URL: (.+)", card["desc"])
    url = url_match.group(1).strip() if url_match else ""
    name_clean = re.sub(r"^\[\d+\] ", "", card["name"])
    title, _, company = name_clean.partition(" — ")
    return url, title.strip(), company.strip()


def _now() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db.init_db()

    from apscheduler.schedulers.blocking import BlockingScheduler

    scheduler = BlockingScheduler(timezone="America/Sao_Paulo")
    scheduler.add_job(flow_collect_and_triage, "cron", hour="8,20")
    scheduler.add_job(flow_execute_application, "cron", hour="*/3")
    scheduler.add_job(flow_retry_captcha, "cron", hour="*/4")

    logger.info("Orquestrador iniciado. Aguardando schedules...")
    scheduler.start()
