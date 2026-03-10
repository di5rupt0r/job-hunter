"""Testes do módulo apply.py com mocks do browser-use."""
import sys
import types
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.fixture(autouse=True)
def mock_browser_use_module():
    """Injeta módulo fake de browser_use para que a lazy import dentro de run_agent funcione."""
    fake_module = types.ModuleType("browser_use")
    fake_module.Agent = MagicMock
    fake_module.Browser = MagicMock
    fake_module.BrowserConfig = MagicMock
    sys.modules.setdefault("browser_use", fake_module)
    yield
    sys.modules.pop("browser_use", None)


@pytest.fixture(autouse=True)
def mock_profile():
    with patch("collect.load_profile_and_policy", return_value=("Perfil Gabriel", "Política triagem")):
        yield


def make_mock_history(final_result_value):
    history = MagicMock()
    history.final_result.return_value = final_result_value
    return history


def test_apply_sync_retorna_success():
    from apply import apply_sync
    mock_browser = MagicMock()
    mock_browser.close = AsyncMock()
    mock_history = make_mock_history("SUCCESS")

    with patch("browser_use.Browser", return_value=mock_browser), \
         patch("browser_use.Agent") as MockAgent:
        instance = MockAgent.return_value
        instance.run = AsyncMock(return_value=mock_history)
        result = apply_sync("https://vaga.com", "DevOps", "TechCorp")

    assert result == "SUCCESS"


def test_apply_sync_retorna_captcha_detected():
    from apply import apply_sync
    mock_browser = MagicMock()
    mock_browser.close = AsyncMock()
    mock_history = make_mock_history("CAPTCHA_DETECTED")

    with patch("browser_use.Browser", return_value=mock_browser), \
         patch("browser_use.Agent") as MockAgent:
        instance = MockAgent.return_value
        instance.run = AsyncMock(return_value=mock_history)
        result = apply_sync("https://vaga.com", "DevOps", "TechCorp")

    assert result == "CAPTCHA_DETECTED"


def test_apply_sync_retorna_error_em_excecao():
    from apply import apply_sync
    mock_browser = MagicMock()
    mock_browser.close = AsyncMock()

    with patch("browser_use.Browser", return_value=mock_browser), \
         patch("browser_use.Agent") as MockAgent:
        instance = MockAgent.return_value
        instance.run = AsyncMock(side_effect=RuntimeError("timeout no browser"))
        result = apply_sync("https://vaga.com", "DevOps", "TechCorp")

    assert result.startswith("ERROR:")
    assert "timeout" in result
