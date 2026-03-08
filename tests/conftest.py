import pytest
from pathlib import Path


@pytest.fixture(autouse=True)
def test_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_jobs.db"
    monkeypatch.setattr("db.DB_PATH", db_path)
    import db
    db.init_db()


@pytest.fixture(autouse=True)
def env_vars(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("BASIC_MEMORY_MCP_URL", "http://mock-mcp")
    monkeypatch.setenv("BASIC_MEMORY_PROJECT", "main")
    monkeypatch.setenv("TRELLO_API_KEY", "test-key")
    monkeypatch.setenv("TRELLO_TOKEN", "test-token")


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from api import app
    return TestClient(app)
