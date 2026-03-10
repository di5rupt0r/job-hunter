"""Testes para integrations/telegram.py — mock httpx."""
import pytest
import httpx
from unittest.mock import patch, MagicMock


@pytest.fixture
def telegram_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:fake-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100999")


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


class TestSendMessage:
    def test_envia_mensagem_com_sucesso(self, telegram_env):
        with patch("httpx.post", return_value=_mock_response({"ok": True})) as mock_post:
            from integrations.telegram import send_message
            send_message("Olá mundo")

        call_params = mock_post.call_args
        assert "123:fake-token" in call_params[0][0]
        assert call_params[1]["json"]["chat_id"] == "-100999"
        assert call_params[1]["json"]["text"] == "Olá mundo"

    def test_falha_silenciosa_sem_levantar_excecao(self, telegram_env):
        """Falha no Telegram NÃO deve travar o fluxo principal."""
        with patch("httpx.post", return_value=_mock_response({}, status_code=500)):
            from integrations.telegram import send_message
            # Não deve levantar exceção
            send_message("mensagem que falha")

    def test_falha_silenciosa_em_network_error(self, telegram_env):
        with patch("httpx.post", side_effect=httpx.ConnectError("timeout")):
            from integrations.telegram import send_message
            send_message("mensagem com timeout")  # Não deve levantar
