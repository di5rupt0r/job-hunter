"""Testes da API FastAPI via TestClient."""
import pytest
from unittest.mock import patch


def test_health_retorna_200(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_collect_retorna_lista_e_total(client):
    fake_jobs = [
        {"url": "https://j1.com", "title": "DevOps", "company": "Co A",
         "platform": "gupy"}
    ]
    with patch("api.collect_jobs", return_value=fake_jobs):
        resp = client.post("/collect")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["jobs"][0]["url"] == "https://j1.com"


def test_apply_success_move_status_para_waiting(client):
    import db
    db.upsert_job("https://vaga-s.com", "SRE", "Corp", "gupy", 90)
    with patch("api.apply_sync", return_value="SUCCESS"):
        resp = client.post("/apply", json={
            "url": "https://vaga-s.com", "title": "SRE", "company": "Corp"
        })
    assert resp.json()["result"] == "SUCCESS"
    assert db.get_job("https://vaga-s.com")["status"] == "waiting"


def test_apply_captcha_incrementa_retry(client):
    import db
    db.upsert_job("https://vaga-c.com", "Dev", "Corp", "gupy", 75)
    with patch("api.apply_sync", return_value="CAPTCHA_DETECTED"):
        resp = client.post("/apply", json={
            "url": "https://vaga-c.com", "title": "Dev", "company": "Corp"
        })
    data = resp.json()
    assert data["result"] == "CAPTCHA_DETECTED"
    assert data["retry_count"] == 1
    assert data["new_status"] == "queued"


def test_apply_tres_captchas_retorna_blocked(client):
    import db
    db.upsert_job("https://vaga-b.com", "Cloud", "Corp", "gupy", 70)
    # Pré-configura 2 retries
    db.increment_retry("https://vaga-b.com")
    db.increment_retry("https://vaga-b.com")

    with patch("api.apply_sync", return_value="CAPTCHA_DETECTED"):
        resp = client.post("/apply", json={
            "url": "https://vaga-b.com", "title": "Cloud", "company": "Corp"
        })
    data = resp.json()
    assert data["result"] == "CAPTCHA_DETECTED"
    assert data["retry_count"] == 3
    assert data["new_status"] == "blocked"


def test_pending_retry_retorna_jobs_corretos(client):
    import db
    db.upsert_job("https://vaga-r.com", "Infra", "Corp", "gupy", 65)
    db.increment_retry("https://vaga-r.com")  # queued com retry=1

    db.upsert_job("https://vaga-noretry.com", "Dev", "Corp", "gupy", 65)
    # retry_count = 0, não deve aparecer

    resp = client.get("/pending-retry")
    assert resp.status_code == 200
    urls = [j["url"] for j in resp.json()["jobs"]]
    assert "https://vaga-r.com" in urls
    assert "https://vaga-noretry.com" not in urls


def test_status_atualiza_corretamente(client):
    import db
    db.upsert_job("https://vaga-u.com", "Cyber", "Corp", "gupy", 88)
    resp = client.post("/status", json={
        "url": "https://vaga-u.com", "status": "interview", "notes": "convite recebido"
    })
    assert resp.json() == {"ok": True}
    assert db.get_job("https://vaga-u.com")["status"] == "interview"


def test_triage_processa_vagas_coletadas(client):
    import db

    url = "https://vaga-t.com"
    db.upsert_job(url, "DevOps", "Co A", "gupy", 0)
    db.update_status(url, "collected")

    fake_jobs = [
        {
            "url": url,
            "title": "DevOps",
            "company": "Co A",
            "city": "Campinas",
            "modality": "remoto",
            "description": "Vaga de DevOps em Campinas.",
            "platform": "gupy",
        }
    ]

    with patch("api.collect_jobs", return_value=fake_jobs), patch(
        "api.load_profile_and_policy", return_value=("PROFILE", "POLICY")
    ), patch("api.filter_hard", return_value=True), patch(
        "api.score_job", return_value=85
    ):
        resp = client.post("/triage")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["jobs"][0]["score"] == 85
    job = db.get_job(url)
    assert job["status"] == "queued"
    assert job["score"] == 85
