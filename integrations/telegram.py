"""Wrapper para o Telegram Bot API — falha silenciosa para não travar flows."""
import logging
import os

import httpx

logger = logging.getLogger(__name__)


def send_message(text: str) -> None:
    """Envia mensagem de texto via Telegram. Falha silenciosa com log de warning."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    try:
        resp = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("Falha ao enviar mensagem Telegram: %s", exc)
