"""Triagem de vagas em duas camadas: hardcoded (zero tokens) + LLM."""
from __future__ import annotations

import logging
import os
from typing import Dict

from openai import OpenAI

logger = logging.getLogger(__name__)


BLACKLIST_TERMS = [
    "vendas",
    "comercial",
    "atendimento",
    "suporte",
    "helpdesk",
    "telemarketing",
    "sdr",
    "bdr",
    "closer",
    "caixa",
    "financeiro",
    "fiscal",
    "contabilidade",
    "logística",
]

RMC_CITIES = [
    "campinas",
    "hortolândia",
    "paulínia",
    "sumaré",
    "americana",
    "santa bárbara d'oeste",
    "nova odessa",
    "cosmopolis",
    "artur nogueira",
    "eng. coelho",
    "indaiatuba",
    "valinhos",
    "vinhedo",
    "itu",
    "limeira",
]


def _is_rmc(city: str) -> bool:
    city_lower = (city or "").lower()
    return any(c in city_lower for c in RMC_CITIES)


def filter_hard(job: Dict) -> bool:
    """Camada 1 — filtro hardcoded. True = passa para LLM, False = descarta."""
    title_lower = job.get("title", "").lower()
    if any(term in title_lower for term in BLACKLIST_TERMS):
        return False

    is_remote = bool(job.get("is_remote")) or str(job.get("modality", "")).lower() == "remoto"
    if is_remote:
        return True

    city = job.get("city", "") or ""
    if not _is_rmc(city):
        return False

    return True


def get_client() -> OpenAI:
    """Wrapper simples para obter cliente OpenAI‑compat de acordo com o provider."""
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
    provider = os.getenv("LLM_PROVIDER", "groq")
    if provider == "groq":
        return "llama-3.1-70b-versatile"
    if provider == "github":
        return "gpt-4o-mini"
    raise ValueError(f"Provider desconhecido: {provider}")


def score_job(
    title: str,
    company: str,
    city: str,
    modality: str,
    description: str,
    policy_md: str,
) -> int:
    """Camada 2 — score via LLM. Retorna inteiro 0‑100; -1 indica descarte/erro."""
    client = get_client()
    model = get_model()

    system_prompt = (
        "Você é um assistente que faz triagem de vagas de estágio em tecnologia.\n"
        "Considere a política de triagem abaixo (markdown) e retorne APENAS um número inteiro "
        "entre 0 e 100 indicando o quão boa é a vaga para o candidato. "
        "Use -1 se a vaga deve ser descartada imediatamente.\n\n"
        "Política de triagem (markdown):\n"
        f"{policy_md}\n"
    )

    user_prompt = (
        f"Título: {title}\n"
        f"Empresa: {company}\n"
        f"Cidade: {city}\n"
        f"Modalidade: {modality}\n"
        f"Descrição:\n{description}\n\n"
        "Responda apenas com o número inteiro (sem texto extra)."
    )

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=8,
        )
        raw = resp.choices[0].message.content.strip()
        score = int(raw)
        if score < -1 or score > 100:
            logger.warning("Score fora do intervalo esperado: %s", score)
            return -1
        return score
    except Exception as exc:
        logger.warning("Erro ao chamar LLM para score_job: %s", exc)
        return -1

