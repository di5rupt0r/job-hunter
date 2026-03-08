"""
Agente de candidatura usando browser-use.
Recebe URL, título e empresa. Retorna: SUCCESS | CAPTCHA_DETECTED | ERROR: ...
"""
import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from browser_use import Agent, Browser, BrowserConfig

load_dotenv(Path(__file__).parent / ".env")

# ─── Constantes ───────────────────────────────────────────────────────────────
MAX_ACTIONS_PER_STEP = 10
MAX_STEPS = 30
MAX_PROFILE_CHARS = 3000

llm = ChatOpenAI(
    model="gpt-4o-mini",
    base_url="https://models.inference.ai.azure.com",
    api_key=os.environ["GITHUB_TOKEN"],
    temperature=0.2,
)

# Importa perfil do Basic Memory via collect.py
from collect import load_profile_and_policy


def build_task(url: str, title: str, company: str) -> str:
    profile_md, _ = load_profile_and_policy()
    return f"""
Sua tarefa: Candidatar-se à vaga de estágio abaixo.

URL da vaga: {url}
Título: {title}
Empresa: {company}

Perfil do candidato (em Markdown/YAML):
{profile_md[:MAX_PROFILE_CHARS]}

Instruções obrigatórias:
1. Acesse a URL da vaga.
2. Encontre o botão de candidatura e clique.
3. Preencha TODOS os campos obrigatórios com os dados do perfil acima.
4. Para campos de "apresentação" ou "carta de motivação": escreva texto personalizado
   de no máximo 200 palavras, mencionando o cargo e a empresa.
5. Se encontrar upload de currículo: pule (não temos arquivo disponível neste fluxo).
6. Se encontrar CAPTCHA visual (imagem, reCAPTCHA, hCaptcha): PARE imediatamente.
   Retorne exatamente: CAPTCHA_DETECTED
7. Ao finalizar com sucesso: retorne exatamente: SUCCESS
8. Se encontrar erro irrecuperável: retorne: ERROR: <descrição breve>

Comportamento esperado:
- Aguarde entre 1 e 3 segundos após cada ação (simula humano).
- Se um campo não estiver no perfil, deixe em branco ou coloque "A combinar".
- Não invente dados que não estão no perfil.
"""


async def run_agent(url: str, title: str, company: str) -> str:
    browser_config = BrowserConfig(
        headless=True,
        extra_chromium_args=[
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
        ],
    )
    browser = Browser(config=browser_config)
    agent = Agent(
        task=build_task(url, title, company),
        llm=llm,
        browser=browser,
        max_actions_per_step=MAX_ACTIONS_PER_STEP,
    )

    try:
        history = await agent.run(max_steps=MAX_STEPS)
        result = str(history.final_result() or "").strip()
        return result if result else "ERROR: sem resultado"
    except Exception as e:
        return f"ERROR: {str(e)[:200]}"
    finally:
        await browser.close()


def apply_sync(url: str, title: str, company: str) -> str:
    return asyncio.run(run_agent(url, title, company))
