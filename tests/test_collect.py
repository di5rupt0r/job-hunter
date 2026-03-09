"""Testes do módulo collect.py (coletores + helpers, sem LLM)."""
import pytest
from unittest.mock import patch, MagicMock


def test_load_profile_and_policy_usa_fallback_se_mcp_falha(monkeypatch):
    import collect
    with patch("collect._call_mcp", side_effect=Exception("MCP indisponível")):
        profile, policy = collect.load_profile_and_policy()
    assert "Gabriel" in profile
    assert "60" in policy


def test_collect_jobs_deduplica_por_url():
    import collect

    job = {
        "url": "https://vaga-dup.com",
        "title": "Dev",
        "company": "Co",
        "city": "SP",
        "modality": "remoto",
        "description": "Python",
        "platform": "gupy",
    }
    with patch("collect.collect_gupy", return_value=[job, job]), patch(
        "collect.collect_jobspy", return_value=[]
    ):
        results = collect.collect_jobs()
    urls = [r["url"] for r in results]
    assert urls.count("https://vaga-dup.com") == 1


def test_extract_company_dict():
    import collect
    job_data = {"company": {"name": "TechCorp"}}
    assert collect._extract_company(job_data) == "TechCorp"


def test_extract_company_string():
    import collect
    job_data = {"company": "TechCorp"}
    assert collect._extract_company(job_data) == "TechCorp"


def test_extract_company_missing():
    import collect
    assert collect._extract_company({}) == ""


# JobSpy tests (RED: devem falhar ate STEP 2)

def make_mock_jobspy_df(rows):
    mock_df = MagicMock()
    mock_df.iterrows.return_value = iter(list(enumerate(rows)))
    return mock_df


def test_collect_jobspy_returns_normalized_list():
    import collect
    rows = [
        {"title": "Estagio Dev", "company": "Corp SA", "location": "Campinas, SP",
         "description": "Python APIs", "job_url": "https://job1.com",
         "site": "linkedin", "is_remote": False},
        {"title": "Estagio DevOps", "company": "Tech Ltda", "location": "Brasil",
         "description": "Docker CI/CD", "job_url": "https://job2.com",
         "site": "indeed", "is_remote": True},
    ]
    with patch("collect.scrape_jobs", return_value=make_mock_jobspy_df(rows), create=True):
        result = collect.collect_jobspy(["estagio python"])
    assert len(result) == 2
    required_keys = {"title", "company", "city", "modality", "description", "url", "platform"}
    assert required_keys.issubset(result[0].keys())
    assert required_keys.issubset(result[1].keys())


def test_collect_jobspy_truncates_description():
    import collect
    long_desc = "x" * (collect.MAX_DESCRIPTION_CHARS + 100)
    rows = [{"title": "Job", "company": "Co", "location": "SP",
             "description": long_desc, "job_url": "https://job3.com",
             "site": "indeed", "is_remote": False}]
    with patch("collect.scrape_jobs", return_value=make_mock_jobspy_df(rows), create=True):
        result = collect.collect_jobspy(["query"])
    assert len(result[0]["description"]) == collect.MAX_DESCRIPTION_CHARS


def test_collect_jobspy_empty_results():
    import collect
    with patch("collect.scrape_jobs", return_value=make_mock_jobspy_df([]), create=True):
        result = collect.collect_jobspy(["query"])
    assert result == []


def test_collect_jobs_deduplicates_across_sources():
    import collect
    shared_url = "https://shared-job.com"
    gupy_job = {"url": shared_url, "title": "Dev", "company": "Co",
                "city": "SP", "modality": "remoto", "description": "Python",
                "platform": "gupy"}
    jobspy_job = {"url": shared_url, "title": "Dev", "company": "Co",
                  "city": "SP", "modality": "remoto", "description": "Python",
                  "platform": "linkedin"}
    with patch("collect.collect_gupy", return_value=[gupy_job]):
        with patch("collect.collect_jobspy", return_value=[jobspy_job], create=True):
            results = collect.collect_jobs()
    assert [r["url"] for r in results].count(shared_url) == 1
