"""Testes para o módulo triage.py (duas camadas: hardcoded + LLM)."""
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def sample_job():
    return {
        "title": "Estágio DevOps",
        "company": "TechCorp",
        "city": "Campinas",
        "modality": "presencial",
        "description": "Vaga de estágio em DevOps com Docker e Linux.",
        "is_remote": False,
    }


def test_filter_hard_descarta_por_blacklist():
    import triage

    job = {
        "title": "Estágio em Vendas Internas",
        "company": "Loja X",
        "city": "Campinas",
        "modality": "presencial",
        "description": "Atendimento e vendas para clientes.",
        "is_remote": False,
    }
    assert triage.filter_hard(job) is False


def test_filter_hard_aprova_remoto_fora_rmc():
    import triage

    job = {
        "title": "Estágio Backend Python",
        "company": "Startup Y",
        "city": "São Paulo",
        "modality": "remoto",
        "description": "APIs em Python.",
        "is_remote": True,
    }
    assert triage.filter_hard(job) is True


def test_filter_hard_aprova_presencial_em_rmc(sample_job):
    import triage

    assert triage.filter_hard(sample_job) is True


def test_filter_hard_descarta_presencial_fora_rmc(sample_job):
    import triage

    job = dict(sample_job, city="São Paulo", is_remote=False)
    assert triage.filter_hard(job) is False


def test_is_rmc_reconhece_cidade_valida():
    import triage

    assert triage._is_rmc("Campinas - SP") is True
    assert triage._is_rmc("Cidade Qualquer") is False


def test_score_job_retorna_inteiro_entre_0_e_100(monkeypatch, sample_job):
    import triage

    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.choices[0].message.content = "85"
    fake_client.chat.completions.create.return_value = fake_response

    with patch("triage.get_client", return_value=fake_client), patch(
        "triage.get_model", return_value="llama-3.1-70b-versatile"
    ):
        score = triage.score_job(
            title=sample_job["title"],
            company=sample_job["company"],
            city=sample_job["city"],
            modality=sample_job["modality"],
            description=sample_job["description"],
            policy_md="score_minimo_candidatura: 60",
        )

    assert isinstance(score, int)
    assert 0 <= score <= 100


def test_score_job_retorna_menos_um_em_erro_de_llm(sample_job):
    import triage

    with patch("triage.get_client") as mock_client, patch(
        "triage.get_model", return_value="llama-3.1-70b-versatile"
    ):
        mock_client.return_value.chat.completions.create.side_effect = Exception(
            "LLM indisponível"
        )
        score = triage.score_job(
            title=sample_job["title"],
            company=sample_job["company"],
            city=sample_job["city"],
            modality=sample_job["modality"],
            description=sample_job["description"],
            policy_md="score_minimo_candidatura: 60",
        )

    assert score == -1

