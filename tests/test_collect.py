"""Testes do módulo collect.py com mocks de LLM e HTTP."""
import json
import pytest
import respx
import httpx
from unittest.mock import patch, MagicMock


MOCK_PROFILE = "Candidato: Gabriel. Skills: Python, Docker, Linux."
MOCK_POLICY = """
## Prompt de Triagem (LLM)
```
Você é um recrutador. Avalie a vaga abaixo.
VAGA: {titulo} em {empresa} ({cidade}, {modalidade})
Descrição: {descricao}
RETORNE APENAS JSON: {"score": N, "descarte": bool, "motivo": "...", "alerta": null}
```
score_minimo_candidatura: 60
"""


@pytest.fixture(autouse=True)
def reset_collect_cache():
    """Limpa o cache do Basic Memory antes de cada teste."""
    import collect
    collect._CACHE = {"profile": None, "policy": None, "loaded_at": 0}


@pytest.fixture
def mock_mcp(monkeypatch):
    """Mock do Basic Memory MCP — retorna perfil e política falsos."""
    with patch("collect._call_mcp") as mock:
        def side_effect(tool, params):
            if "perfil" in params.get("identifier", ""):
                return MOCK_PROFILE
            return MOCK_POLICY
        mock.side_effect = side_effect
        yield mock


def make_llm_response(score, descarte=False, motivo="ok"):
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = json.dumps({
        "score": score, "descarte": descarte, "motivo": motivo, "alerta": None
    })
    return mock_resp


def test_score_job_blacklist_retorna_descarte():
    import collect
    with patch.object(collect.llm_client.chat.completions, "create") as mock_llm:
        mock_llm.return_value = make_llm_response(20, descarte=True, motivo="vendas blacklist")
        result = collect.score_job(
            "Vendedor Externo", "Empresa X", "SP", "presencial",
            "vender produtos", policy_md=MOCK_POLICY
        )
    assert result["descarte"] is True


def test_score_job_devops_campinas_acima_threshold():
    import collect
    with patch.object(collect.llm_client.chat.completions, "create") as mock_llm:
        mock_llm.return_value = make_llm_response(82)
        result = collect.score_job(
            "Estágio DevOps", "TechCorp", "Campinas", "hibrido",
            "Docker, Linux, CI/CD", policy_md=MOCK_POLICY
        )
    assert result["score"] >= 60
    assert result["descarte"] is False


def test_score_job_venda_baixo_score():
    import collect
    with patch.object(collect.llm_client.chat.completions, "create") as mock_llm:
        mock_llm.return_value = make_llm_response(15, descarte=False, motivo="irrelevante")
        result = collect.score_job(
            "Auxiliar Comercial", "Loja Y", "SP", "presencial",
            "atender clientes", policy_md=MOCK_POLICY
        )
    assert result["score"] < 60


def test_collect_and_score_deduplica_por_url(mock_mcp):
    import collect
    job = {
        "url": "https://vaga-dup.com", "title": "Dev", "company": "Co",
        "city": "SP", "modality": "remoto", "description": "Python", "platform": "gupy"
    }
    with patch("collect.collect_gupy", return_value=[job, job]):
        with patch("collect.collect_jobspy", return_value=[]):
            with patch("collect.score_job", return_value={"score": 75, "descarte": False, "motivo": "ok", "alerta": None}):
                results = collect.collect_and_score()
    urls = [r["url"] for r in results]
    assert urls.count("https://vaga-dup.com") == 1


def test_collect_and_score_filtra_abaixo_threshold(mock_mcp):
    import collect
    jobs = [
        {"url": f"https://vaga{i}.com", "title": "Job", "company": "Co",
         "city": "SP", "modality": "remoto", "description": "x", "platform": "gupy"}
        for i in range(3)
    ]
    scores = [30, 55, 80]
    with patch("collect.collect_gupy", return_value=jobs):
        with patch("collect.collect_jobspy", return_value=[]):
            with patch("collect.score_job") as mock_score:
                mock_score.side_effect = [
                    {"score": s, "descarte": False, "motivo": "ok", "alerta": None} for s in scores
                ]
                results = collect.collect_and_score()
    # Apenas score 80 está acima do threshold 60
    assert len(results) == 1
    assert results[0]["score"] == 80


def test_load_profile_and_policy_usa_fallback_se_mcp_falha(monkeypatch):
    import collect
    with patch("collect._call_mcp", side_effect=Exception("MCP indisponível")):
        profile, policy = collect.load_profile_and_policy()
    assert "Gabriel" in profile
    assert "60" in policy


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
    required_keys = {"title", "company", "city", "modality", "description", "url", "source"}
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


def test_collect_and_score_deduplicates_across_sources(mock_mcp):
    import collect
    shared_url = "https://shared-job.com"
    gupy_job = {"url": shared_url, "title": "Dev", "company": "Co",
                "city": "SP", "modality": "remoto", "description": "Python",
                "platform": "gupy"}
    jobspy_job = {"url": shared_url, "title": "Dev", "company": "Co",
                  "city": "SP", "modality": "remoto", "description": "Python",
                  "source": "linkedin"}
    with patch("collect.collect_gupy", return_value=[gupy_job]):
        with patch("collect.collect_jobspy", return_value=[jobspy_job], create=True):
            with patch("collect.score_job", return_value={
                "score": 75, "descarte": False, "motivo": "ok", "alerta": None
            }):
                results = collect.collect_and_score()
    assert [r["url"] for r in results].count(shared_url) == 1
