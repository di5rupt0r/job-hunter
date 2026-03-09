"""Testes do wrapper de provider LLM (Groq/GitHub)."""
from unittest.mock import patch, MagicMock


def test_get_client_groq_usa_base_url_e_api_key_corretos(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")

    import llm_provider

    fake_client_cls = MagicMock()
    with patch("llm_provider.OpenAI", fake_client_cls):
        client = llm_provider.get_client()

    fake_client_cls.assert_called_once_with(
        base_url="https://api.groq.com/openai/v1",
        api_key="test-groq-key",
    )
    assert client is fake_client_cls()


def test_get_client_github_usa_base_url_e_token_github(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "github")
    monkeypatch.setenv("GITHUB_TOKEN", "test-gh-token")

    import llm_provider

    fake_client_cls = MagicMock()
    with patch("llm_provider.OpenAI", fake_client_cls):
        client = llm_provider.get_client()

    fake_client_cls.assert_called_once_with(
        base_url="https://models.inference.ai.azure.com",
        api_key="test-gh-token",
    )
    assert client is fake_client_cls()


def test_get_model_retorna_modelo_por_provider(monkeypatch):
    import llm_provider

    monkeypatch.setenv("LLM_PROVIDER", "groq")
    assert llm_provider.get_model() == "llama-3.1-70b-versatile"

    monkeypatch.setenv("LLM_PROVIDER", "github")
    assert llm_provider.get_model() == "gpt-4o-mini"

