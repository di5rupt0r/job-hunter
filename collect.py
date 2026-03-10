"""
Coleta vagas de Gupy e JobSpy.
Carrega perfil e política de triagem do Basic Memory MCP (cache de 6h).

A lógica de triagem (hardcoded + LLM) vive em `triage.py`.
"""
import logging
import os
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

logger = logging.getLogger(__name__)

# ─── Constantes ───────────────────────────────────────────────────────────────
CACHE_TTL = 6 * 3600
HTTP_TIMEOUT = 15
GUPY_JOBS_PER_QUERY = 20
MAX_DESCRIPTION_CHARS = 800
GUPY_SEARCH_QUERIES = [
    # Gupy jobName faz match literal no titulo - usar palavras unicas sem acento
    "estagio", "ciberseguranca", "devops", "python",
    "infraestrutura", "cloud", "backend", "dados",
    "linux", "docker", "automacao", "seguranca",
]
# Subset usada pelo JobSpy — portais internacionais são mais lentos, queries reduzidas
JOBSPY_SEARCH_QUERIES = [
    "software engineering intern", "cybersecurity intern", "devops intern",
    "backend intern campinas", "python intern brazil",
]

# ─── Basic Memory MCP Cache ───────────────────────────────────────────────────
_CACHE = {"profile": None, "policy": None, "loaded_at": 0}


_MCP_SESSION: dict = {}

def _call_mcp(tool: str, params: dict) -> str:
    url = os.environ["BASIC_MEMORY_MCP_URL"]
    h = {"Content-Type": "application/json",
         "Accept": "application/json, text/event-stream"}
    if "session_id" not in _MCP_SESSION:
        r = httpx.post(url, headers=h, timeout=HTTP_TIMEOUT, json={
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "collect", "version": "1.0"}},
        })
        r.raise_for_status()
        _MCP_SESSION["session_id"] = r.headers["mcp-session-id"]
    h["mcp-session-id"] = _MCP_SESSION["session_id"]
    r = httpx.post(url, headers=h, timeout=HTTP_TIMEOUT, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool, "arguments": params},
    })
    r.raise_for_status()
    return r.json()["result"]["content"][0]["text"]


def load_profile_and_policy():
    global _CACHE
    if _CACHE["profile"] and (time.time() - _CACHE["loaded_at"]) < CACHE_TTL:
        return _CACHE["profile"], _CACHE["policy"]
    try:
        project = os.environ.get("BASIC_MEMORY_PROJECT", "main")
        profile_md = _call_mcp("read_note", {
            "identifier": "projects/candidatura-estagio/perfil-gabriel-candidaturas",
            "project": project,
        })
        policy_md = _call_mcp("read_note", {
            "identifier": "projects/candidatura-estagio/candidatura-politica-de-triagem",
            "project": project,
        })
        _CACHE = {"profile": profile_md, "policy": policy_md, "loaded_at": time.time()}
        return profile_md, policy_md
    except Exception as e:
        logger.warning("Falha ao carregar Basic Memory: %s. Usando fallback.", e)
        fallback_profile = "Candidato: Gabriel. Skills: Python, Docker, Linux, Cloud, APIs."
        fallback_policy = "score_minimo: 60. Blacklist: vendas, atendimento, suporte, helpdesk."
        return fallback_profile, fallback_policy


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _extract_company(job_data: dict) -> str:
    company = job_data.get("company", "")
    if isinstance(company, dict):
        return company.get("name", "")
    return str(company)


# ─── Coletores ────────────────────────────────────────────────────────────────


def collect_gupy() -> list[dict]:
    """Coleta vagas da API pública da Gupy."""
    jobs = []
    seen = set()
    for q in GUPY_SEARCH_QUERIES:
        try:
            r = httpx.get(
                "https://portal.api.gupy.io/api/v1/jobs",
                params={"jobName": q, "limit": GUPY_JOBS_PER_QUERY, "offset": 0},
                timeout=HTTP_TIMEOUT,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            r.raise_for_status()
            for job in r.json().get("data", []):
                url = job.get("jobUrl") or f"https://portal.gupy.io/job/{job.get('id')}"
                if url in seen:
                    continue
                seen.add(url)
                jobs.append({
                    "url": url,
                    "title": job.get("name", ""),
                    "company": _extract_company(job),
                    "city": job.get("city", ""),
                    "modality": job.get("workplaceType", ""),
                    "description": job.get("description", "")[:MAX_DESCRIPTION_CHARS],
                    "platform": "gupy",
                })
        except Exception as e:
            logger.warning("Gupy query %r falhou: %s", q, e)
    return jobs



def collect_jobspy(queries: list[str]) -> list[dict]:
    """Coleta vagas via python-jobspy (LinkedIn e Indeed — Glassdoor/Google não suportam BR)."""
    from jobspy import scrape_jobs
    jobs = []
    seen: set[str] = set()
    for query in queries:
        try:
            results = scrape_jobs(
                site_name=["linkedin", "indeed"],
                search_term=query,
                location="Campinas, SP, Brasil",
                job_type="internship",
                results_wanted=5,
                hours_old=48,
                country_indeed="Brazil",
                verbose=0,
            )
            for _, row in results.iterrows():
                url = str(row.get("job_url", ""))
                if not url or url in seen:
                    continue
                seen.add(url)
                jobs.append({
                    "title": str(row.get("title", "")),
                    "company": str(row.get("company", "")),
                    "city": str(row.get("location", "")),
                    "modality": "remoto" if row.get("is_remote") else "on-site",
                    "description": str(row.get("description", ""))[:MAX_DESCRIPTION_CHARS],
                    "url": url,
                    "platform": str(row.get("site", "jobspy")),
                })
        except Exception as e:
            logger.warning("JobSpy query %r falhou: %s", query, e)
    return jobs


def collect_jobs() -> list[dict]:
    """Coleta vagas das fontes configuradas e deduplica por URL."""
    raw_jobs = collect_gupy() + collect_jobspy(JOBSPY_SEARCH_QUERIES)
    seen_urls: set[str] = set()
    deduped: list[dict] = []
    for job in raw_jobs:
        url = job.get("url")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        deduped.append(job)
    logger.info(
        "Coletadas %d vagas brutas (%d com duplicatas)", len(deduped), len(raw_jobs)
    )
    return deduped
