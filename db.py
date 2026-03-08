"""SQLite wrapper — fonte de verdade do estado das candidaturas."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "jobs.db"


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                url TEXT PRIMARY KEY,
                title TEXT,
                company TEXT,
                platform TEXT,
                score INTEGER DEFAULT 0,
                status TEXT DEFAULT 'queued',
                retry_count INTEGER DEFAULT 0,
                trello_card_id TEXT,
                notes TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)


def upsert_job(url, title, company, platform, score, trello_card_id=None):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO jobs (url, title, company, platform, score, trello_card_id)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                title=excluded.title,
                company=excluded.company,
                score=excluded.score,
                updated_at=CURRENT_TIMESTAMP
        """, (url, title, company, platform, score, trello_card_id))


def get_job(url):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM jobs WHERE url=?", (url,)).fetchone()


def update_status(url, status, notes=None):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            UPDATE jobs SET status=?, notes=COALESCE(?,notes), updated_at=CURRENT_TIMESTAMP
            WHERE url=?
        """, (status, notes, url))


def increment_retry(url):
    """Incrementa retry_count e retorna (retry_count, new_status)."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            UPDATE jobs SET retry_count=retry_count+1, updated_at=CURRENT_TIMESTAMP
            WHERE url=?
        """, (url,))
        row = conn.execute("SELECT retry_count FROM jobs WHERE url=?", (url,)).fetchone()
        retry_count = row[0]
        new_status = "blocked" if retry_count >= 3 else "queued"
        conn.execute("UPDATE jobs SET status=? WHERE url=?", (new_status, url))
        return retry_count, new_status


def get_pending_retry():
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("""
            SELECT * FROM jobs
            WHERE status='queued' AND retry_count > 0 AND retry_count < 3
        """).fetchall()
