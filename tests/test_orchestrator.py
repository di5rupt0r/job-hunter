"""Testes dos flows do orquestrador — mock httpx e integrações."""
import pytest
from unittest.mock import patch, MagicMock, call


@pytest.fixture
def orch_env(monkeypatch):
    monkeypatch.setenv("TRELLO_API_KEY", "fake-key")
    monkeypatch.setenv("TRELLO_TOKEN", "fake-token")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:fake")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100")
    monkeypatch.setenv("AGENT_API_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("TRELLO_LIST_COLETADA", "list-coletada")
    monkeypatch.setenv("TRELLO_LIST_TRIAGEM", "list-triagem")
    monkeypatch.setenv("TRELLO_LIST_CANDIDATANDO", "list-candidatando")
    monkeypatch.setenv("TRELLO_LIST_AGUARDANDO", "list-aguardando")
    monkeypatch.setenv("TRELLO_LIST_BLOQUEADA", "list-bloqueada")


class TestFlowCollectAndTriage:
    def test_sem_vagas_novas_nao_cria_cards(self, orch_env):
        with patch("httpx.post") as mock_post, \
             patch("integrations.trello.create_card") as mock_create, \
             patch("integrations.trello.move_card") as mock_move:
            mock_post.return_value = _api_resp({"jobs": [], "new_jobs": [], "new": 0, "total": 0})
            from orchestrator import flow_collect_and_triage
            flow_collect_and_triage()

        mock_create.assert_not_called()
        mock_move.assert_not_called()

    def test_com_vagas_novas_cria_cards_e_salva_card_id(self, orch_env):
        new_job = {"url": "https://j.com", "title": "SRE", "company": "Corp", "platform": "gupy"}
        collect_resp = {"jobs": [new_job], "new_jobs": [new_job], "new": 1, "total": 1}
        triage_resp = {"jobs": [], "total": 0}

        with patch("httpx.post") as mock_post, \
             patch("integrations.trello.create_card", return_value={"id": "card-abc"}) as mock_create, \
             patch("integrations.trello.move_card") as mock_move, \
             patch("time.sleep"):
            mock_post.side_effect = [
                _api_resp(collect_resp),   # /collect
                _api_resp({"ok": True}),   # /card-id
                _api_resp(triage_resp),    # /triage
            ]
            from orchestrator import flow_collect_and_triage
            flow_collect_and_triage()

        from unittest.mock import ANY
        mock_create.assert_called_once_with("list-coletada", "SRE — Corp", ANY)
        # card-id foi salvo
        card_id_call = mock_post.call_args_list[1]
        assert "card-id" in card_id_call[0][0]
        assert card_id_call[1]["json"]["trello_card_id"] == "card-abc"

    def test_vagas_triadas_movem_card_existente_para_triagem(self, orch_env):
        triaged_job = {
            "url": "https://j2.com", "title": "DevOps", "company": "Co A",
            "platform": "gupy", "score": 80, "trello_card_id": "card-xyz"
        }
        collect_resp = {"jobs": [], "new_jobs": [], "new": 0, "total": 0}
        triage_resp = {"jobs": [triaged_job], "total": 1}

        with patch("httpx.post") as mock_post, \
             patch("integrations.trello.create_card") as mock_create, \
             patch("integrations.trello.move_card") as mock_move, \
             patch("time.sleep"):
            mock_post.side_effect = [
                _api_resp(collect_resp),
                _api_resp(triage_resp),
            ]
            from orchestrator import flow_collect_and_triage
            flow_collect_and_triage()

        mock_move.assert_called_once_with(
            "card-xyz", "list-triagem", name="[80] DevOps — Co A"
        )
        mock_create.assert_not_called()

    def test_vaga_triada_sem_card_cria_novo_na_triagem(self, orch_env):
        triaged_job = {
            "url": "https://j3.com", "title": "Cloud", "company": "Co B",
            "platform": "gupy", "score": 75, "trello_card_id": None
        }
        collect_resp = {"jobs": [], "new_jobs": [], "new": 0, "total": 0}
        triage_resp = {"jobs": [triaged_job], "total": 1}

        with patch("httpx.post") as mock_post, \
             patch("integrations.trello.create_card") as mock_create, \
             patch("integrations.trello.move_card") as mock_move, \
             patch("time.sleep"):
            mock_post.side_effect = [
                _api_resp(collect_resp),
                _api_resp(triage_resp),
            ]
            from orchestrator import flow_collect_and_triage
            flow_collect_and_triage()

        mock_create.assert_called_once()
        call_args = mock_create.call_args
        assert call_args[0][0] == "list-triagem"
        assert "[75] Cloud — Co B" in call_args[0][1]


class TestFlowExecuteApplication:
    def test_sem_cards_na_triagem_retorna_sem_acao(self, orch_env):
        with patch("integrations.trello.list_cards", return_value=[]) as mock_list, \
             patch("httpx.post") as mock_post:
            from orchestrator import flow_execute_application
            flow_execute_application()

        mock_post.assert_not_called()

    def test_sucesso_move_para_aguardando(self, orch_env):
        card = {
            "id": "card1",
            "name": "SRE — Corp",
            "desc": "🔗 URL: https://j.com\n🏭 Plataforma: gupy",
        }
        apply_resp = {"result": "SUCCESS"}

        with patch("integrations.trello.list_cards", return_value=[card]), \
             patch("integrations.trello.move_card") as mock_move, \
             patch("httpx.post", return_value=_api_resp(apply_resp)):
            from orchestrator import flow_execute_application
            flow_execute_application()

        calls = mock_move.call_args_list
        assert any(c[0][1] == "list-candidatando" for c in calls)
        assert any(c[0][1] == "list-aguardando" for c in calls)

    def test_captcha_retry_move_para_coletada_e_envia_telegram(self, orch_env):
        card = {
            "id": "card1",
            "name": "Dev — Corp",
            "desc": "🔗 URL: https://j.com\n🏭 Plataforma: gupy",
        }
        apply_resp = {"result": "CAPTCHA_DETECTED", "retry_count": 1, "new_status": "queued"}

        with patch("integrations.trello.list_cards", return_value=[card]), \
             patch("integrations.trello.move_card") as mock_move, \
             patch("integrations.telegram.send_message") as mock_tg, \
             patch("httpx.post", return_value=_api_resp(apply_resp)):
            from orchestrator import flow_execute_application
            flow_execute_application()

        move_targets = [c[0][1] for c in mock_move.call_args_list]
        assert "list-coletada" in move_targets
        mock_tg.assert_called_once()
        assert "CAPTCHA" in mock_tg.call_args[0][0]

    def test_captcha_blocked_move_para_bloqueada_e_envia_telegram(self, orch_env):
        card = {
            "id": "card1",
            "name": "Dev — Corp",
            "desc": "🔗 URL: https://j.com\n🏭 Plataforma: gupy",
        }
        apply_resp = {"result": "CAPTCHA_DETECTED", "retry_count": 3, "new_status": "blocked"}

        with patch("integrations.trello.list_cards", return_value=[card]), \
             patch("integrations.trello.move_card") as mock_move, \
             patch("integrations.telegram.send_message") as mock_tg, \
             patch("httpx.post", return_value=_api_resp(apply_resp)):
            from orchestrator import flow_execute_application
            flow_execute_application()

        move_targets = [c[0][1] for c in mock_move.call_args_list]
        assert "list-bloqueada" in move_targets
        mock_tg.assert_called_once()
        assert "BLOQUEADA" in mock_tg.call_args[0][0]

    def test_erro_move_para_coletada_e_envia_telegram(self, orch_env):
        card = {
            "id": "card1",
            "name": "Dev — Corp",
            "desc": "🔗 URL: https://j.com\n🏭 Plataforma: gupy",
        }
        apply_resp = {"result": "ERROR", "detail": "timeout"}

        with patch("integrations.trello.list_cards", return_value=[card]), \
             patch("integrations.trello.move_card") as mock_move, \
             patch("integrations.telegram.send_message") as mock_tg, \
             patch("httpx.post", return_value=_api_resp(apply_resp)):
            from orchestrator import flow_execute_application
            flow_execute_application()

        move_targets = [c[0][1] for c in mock_move.call_args_list]
        assert "list-coletada" in move_targets
        mock_tg.assert_called_once()
        assert "Erro" in mock_tg.call_args[0][0] or "erro" in mock_tg.call_args[0][0].lower()


class TestFlowRetryCaptcha:
    def test_sem_pending_nao_move_nenhum_card(self, orch_env):
        with patch("httpx.get", return_value=_api_resp({"jobs": []})), \
             patch("integrations.trello.move_card") as mock_move:
            from orchestrator import flow_retry_captcha
            flow_retry_captcha()

        mock_move.assert_not_called()

    def test_move_cards_pendentes_para_triagem(self, orch_env):
        pending = [
            {"url": "https://j1.com", "trello_card_id": "card-a", "retry_count": 1},
            {"url": "https://j2.com", "trello_card_id": "card-b", "retry_count": 2},
        ]
        with patch("httpx.get", return_value=_api_resp({"jobs": pending})), \
             patch("integrations.trello.move_card") as mock_move:
            from orchestrator import flow_retry_captcha
            flow_retry_captcha()

        assert mock_move.call_count == 2
        for c in mock_move.call_args_list:
            assert c[0][1] == "list-triagem"

    def test_job_sem_card_id_e_ignorado(self, orch_env):
        pending = [{"url": "https://j1.com", "trello_card_id": None, "retry_count": 1}]
        with patch("httpx.get", return_value=_api_resp({"jobs": pending})), \
             patch("integrations.trello.move_card") as mock_move:
            from orchestrator import flow_retry_captcha
            flow_retry_captcha()

        mock_move.assert_not_called()


# --- helpers ---

def _api_resp(data: dict) -> MagicMock:
    import httpx
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    return resp
