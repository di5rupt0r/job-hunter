"""Testes do módulo db.py — RED first, então GREEN com db.py existente."""
import pytest
import db


def test_upsert_job_cria_novo():
    db.upsert_job("https://vaga1.com", "Dev Backend", "Empresa A", "gupy", 85)
    job = db.get_job("https://vaga1.com")
    assert job is not None
    assert job["title"] == "Dev Backend"
    assert job["score"] == 85


def test_upsert_job_nao_duplica_url():
    db.upsert_job("https://vaga2.com", "DevOps", "Empresa B", "gupy", 70)
    db.upsert_job("https://vaga2.com", "DevOps Senior", "Empresa B", "gupy", 75)
    # Conta direto no banco
    import sqlite3
    with sqlite3.connect(db.DB_PATH) as conn:
        count = conn.execute("SELECT COUNT(*) FROM jobs WHERE url=?", ("https://vaga2.com",)).fetchone()[0]
    assert count == 1


def test_update_status_altera_corretamente():
    db.upsert_job("https://vaga3.com", "SRE", "Empresa C", "linkedin", 60)
    db.update_status("https://vaga3.com", "waiting", notes="ok")
    job = db.get_job("https://vaga3.com")
    assert job["status"] == "waiting"
    assert job["notes"] == "ok"


def test_increment_retry_primeira_chamada():
    db.upsert_job("https://vaga4.com", "Cloud", "Empresa D", "gupy", 65)
    retry_count, new_status = db.increment_retry("https://vaga4.com")
    assert retry_count == 1
    assert new_status == "queued"


def test_increment_retry_terceira_chamada_bloqueia():
    db.upsert_job("https://vaga5.com", "Infra", "Empresa E", "gupy", 72)
    db.increment_retry("https://vaga5.com")
    db.increment_retry("https://vaga5.com")
    retry_count, new_status = db.increment_retry("https://vaga5.com")
    assert retry_count == 3
    assert new_status == "blocked"


def test_get_pending_retry_so_retorna_queued_com_retry():
    # queued com retry_count > 0: deve aparecer
    db.upsert_job("https://vaga6.com", "Sec", "Empresa F", "gupy", 80)
    db.increment_retry("https://vaga6.com")  # retry_count=1, status=queued

    # queued sem retry: NÃO deve aparecer
    db.upsert_job("https://vaga7.com", "DevOps", "Empresa G", "gupy", 75)
    # status padrão = 'queued', retry_count = 0

    # blocked: NÃO deve aparecer
    db.upsert_job("https://vaga8.com", "Dev", "Empresa H", "gupy", 70)
    db.increment_retry("https://vaga8.com")
    db.increment_retry("https://vaga8.com")
    db.increment_retry("https://vaga8.com")  # blocked

    results = db.get_pending_retry()
    urls = [r["url"] for r in results]
    assert "https://vaga6.com" in urls
    assert "https://vaga7.com" not in urls
    assert "https://vaga8.com" not in urls
