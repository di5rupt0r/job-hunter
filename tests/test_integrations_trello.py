"""Testes para integrations/trello.py — mock httpx para não fazer chamadas reais."""
import pytest
import httpx
from unittest.mock import patch, MagicMock


@pytest.fixture
def trello_env(monkeypatch):
    monkeypatch.setenv("TRELLO_API_KEY", "fake-key")
    monkeypatch.setenv("TRELLO_TOKEN", "fake-token")


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


class TestListCards:
    def test_retorna_lista_de_cards(self, trello_env):
        cards = [{"id": "card1", "name": "Dev — Corp", "desc": "🔗 URL: https://j.com"}]
        with patch("httpx.get", return_value=_mock_response(cards)) as mock_get:
            from integrations.trello import list_cards
            result = list_cards("list123")

        assert result == cards
        call_params = mock_get.call_args
        assert "list123" in call_params[0][0]
        assert call_params[1]["params"]["key"] == "fake-key"
        assert call_params[1]["params"]["token"] == "fake-token"
        assert call_params[1]["params"]["fields"] == "id,name,desc"

    def test_lista_vazia(self, trello_env):
        with patch("httpx.get", return_value=_mock_response([])):
            from integrations.trello import list_cards
            result = list_cards("list-vazia")
        assert result == []

    def test_levanta_excecao_em_erro_http(self, trello_env):
        with patch("httpx.get", return_value=_mock_response({}, status_code=401)):
            from integrations.trello import list_cards
            with pytest.raises(Exception):
                list_cards("list123")


class TestCreateCard:
    def test_cria_card_e_retorna_dict_com_id(self, trello_env):
        card_resp = {"id": "card-novo", "name": "SRE — Corp", "desc": "🔗 URL: ..."}
        with patch("httpx.post", return_value=_mock_response(card_resp)) as mock_post:
            from integrations.trello import create_card
            result = create_card("list123", "SRE — Corp", "🔗 URL: https://j.com")

        assert result["id"] == "card-novo"
        call_params = mock_post.call_args
        assert "cards" in call_params[0][0]
        payload = call_params[1]["json"]
        assert payload["idList"] == "list123"
        assert payload["name"] == "SRE — Corp"
        assert "key" in call_params[1]["params"]

    def test_levanta_excecao_em_erro_http(self, trello_env):
        with patch("httpx.post", return_value=_mock_response({}, status_code=400)):
            from integrations.trello import create_card
            with pytest.raises(Exception):
                create_card("list123", "Vaga", "desc")


class TestMoveCard:
    def test_move_card_sem_renomear(self, trello_env):
        with patch("httpx.put", return_value=_mock_response({"id": "card1"})) as mock_put:
            from integrations.trello import move_card
            move_card("card1", "list-destino")

        call_params = mock_put.call_args
        assert "card1" in call_params[0][0]
        payload = call_params[1]["json"]
        assert payload["idList"] == "list-destino"
        assert "name" not in payload

    def test_move_card_com_novo_nome(self, trello_env):
        with patch("httpx.put", return_value=_mock_response({"id": "card1"})) as mock_put:
            from integrations.trello import move_card
            move_card("card1", "list-destino", name="[85] SRE — Corp")

        payload = mock_put.call_args[1]["json"]
        assert payload["name"] == "[85] SRE — Corp"
        assert payload["idList"] == "list-destino"

    def test_levanta_excecao_em_erro_http(self, trello_env):
        with patch("httpx.put", return_value=_mock_response({}, status_code=403)):
            from integrations.trello import move_card
            with pytest.raises(Exception):
                move_card("card1", "list-destino")
