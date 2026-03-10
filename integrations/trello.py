"""Wrapper para a API REST do Trello — chamadas HTTP diretas via httpx."""
import os

import httpx

_BASE = "https://api.trello.com/1"


def _auth() -> dict:
    return {"key": os.environ["TRELLO_API_KEY"], "token": os.environ["TRELLO_TOKEN"]}


def list_cards(list_id: str) -> list[dict]:
    """Retorna os cards de uma lista Trello."""
    resp = httpx.get(
        f"{_BASE}/lists/{list_id}/cards",
        params={**_auth(), "fields": "id,name,desc"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def create_card(list_id: str, name: str, desc: str) -> dict:
    """Cria um card na lista e retorna o dict com .id."""
    resp = httpx.post(
        f"{_BASE}/cards",
        params=_auth(),
        json={"idList": list_id, "name": name, "desc": desc},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def move_card(card_id: str, list_id: str, name: str | None = None) -> None:
    """Move um card para outra lista, renomeando opcionalmente."""
    payload: dict = {"idList": list_id}
    if name is not None:
        payload["name"] = name
    resp = httpx.put(
        f"{_BASE}/cards/{card_id}",
        params=_auth(),
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
