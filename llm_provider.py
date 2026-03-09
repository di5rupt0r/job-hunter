"""Wrapper simples OpenAI‑compat para trocar de provider (Groq/GitHub)."""
from __future__ import annotations

import os
from openai import OpenAI


def get_client() -> OpenAI:
    """Retorna cliente OpenAI‑compat de acordo com `LLM_PROVIDER`."""
    provider = os.getenv("LLM_PROVIDER", "groq")
    if provider == "groq":
        return OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=os.environ["GROQ_API_KEY"],
        )
    if provider == "github":
        return OpenAI(
            base_url="https://models.inference.ai.azure.com",
            api_key=os.environ["GITHUB_TOKEN"],
        )
    raise ValueError(f"Provider desconhecido: {provider}")


def get_model() -> str:
    """Retorna nome do modelo configurado para o provider atual."""
    provider = os.getenv("LLM_PROVIDER", "groq")
    mapping = {
        "groq": "llama-3.1-70b-versatile",
        "github": "gpt-4o-mini",
    }
    try:
        return mapping[provider]
    except KeyError as exc:
        raise ValueError(f"Provider desconhecido: {provider}") from exc

