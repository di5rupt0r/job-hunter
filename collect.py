"""
Coleta vagas de Gupy, faz scoring via LLM (GitHub Models API).
Carrega perfil e política de triagem do Basic Memory MCP (cache de 6h).
"""
import os
import re
import json
import time
import httpx
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
from jobspy import scrape_jobs

load_dotenv(Path(__file__).parent / ".env")

# ─── Constantes ───────────────────────────────────────────────────────────────
CACHE_TTL = 6 * 3600
HTTP_TIMEOUT = 15
GUPY_JOBS_PER_QUERY = 20
MAX_DESCRIPTION_CHARS = 800
SCORE_MAX_TOKENS = 200
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

# ─── LLM Client (GitHub Models API) ───────────────────────────────────────────
llm_client = OpenAI(
    base_url="https://models.inference.ai.azure.com",
    api_key=os.environ["GITHUB_TOKEN"],
    max_retries=0,  # falha rapido no 429 em vez de backoff automatico
    timeout=10.0,
)

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
        print(f"[WARN] Falha ao carregar Basic Memory: {e}. Usando fallback.")
        fallback_profile = "Candidato: Gabriel. Skills: Python, Docker, Linux, Cloud, APIs."
        fallback_policy = "score_minimo: 60. Blacklist: vendas, atendimento, suporte, helpdesk."
        return fallback_profile, fallback_policy


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _extract_company(job_data: dict) -> str:
    company = job_data.get("company", "")
    if isinstance(company, dict):
        return company.get("name", "")
    return str(company)


# ─── Scoring via LLM ──────────────────────────────────────────────────────────

def score_job(
    title: str, company: str, city: str, modality: str,
    description: str, policy_md: str, profile_md: str = ""
) -> dict:
    prompt_match = re.search(r"## Prompt de Triagem.*?```\n(.*?)```", policy_md, re.DOTALL)
    if prompt_match:
        scoring_prompt = prompt_match.group(1)
    else:
        scoring_prompt = policy_md

    user_content = (
        scoring_prompt
        .replace("{perfil}", profile_md)
        .replace("{titulo}", title)
        .replace("{empresa}", company)
        .replace("{cidade}", city)
        .replace("{modalidade}", modality)
        .replace("{descricao}", description[:MAX_DESCRIPTION_CHARS])
    )

    try:
        resp = llm_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": user_content}],
            temperature=0.1,
            max_tokens=SCORE_MAX_TOKENS,
        )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"^```json\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
        return json.loads(raw)
    except Exception as e:
        print(f"[WARN] Erro no scoring LLM: {e}")
        return {"score": 65, "descarte": False, "motivo": "scoring indisponivel - revisar manualmente", "alerta": "LLM_UNAVAILABLE"}


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
            print(f"[WARN] Gupy query '{q}': {e}")
    return jobs



def collect_jobspy(queries: list[str]) -> list[dict]:
    """Coleta vagas via python-jobspy (LinkedIn e Indeed — Glassdoor/Google não suportam BR)."""
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
            print(f"[WARN] JobSpy query {query!r}: {e}")
    return jobs

def collect_and_score() -> list[dict]:
    """Coleta vagas da Gupy, faz scoring e retorna vagas com score >= threshold."""
    profile_md, policy_md = load_profile_and_policy()

    threshold_match = re.search(r"score_minimo_candidatura:\s*(\d+)", policy_md)
    threshold = int(threshold_match.group(1)) if threshold_match else 60

    raw_jobs = collect_gupy() + collect_jobspy(JOBSPY_SEARCH_QUERIES)
    seen_urls = set()
    deduped = []
    for j in raw_jobs:
        if j["url"] not in seen_urls:
            seen_urls.add(j["url"])
            deduped.append(j)
    print(f"[INFO] Coletadas {len(deduped)} vagas brutas ({len(raw_jobs)} com duplicatas)")

    scored = []
    for job in deduped:
        result = score_job(
            title=job["title"],
            company=job["company"],
            city=job.get("city", ""),
            modality=job.get("modality", ""),
            description=job.get("description", ""),
            policy_md=policy_md,
            profile_md=profile_md,
        )
        if result.get("descarte"):
            continue
        score = result.get("score", 0)
        if score >= threshold:
            scored.append({**job, "score": score, "motivo": result.get("motivo", ""), "alerta": result.get("alerta")})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored
