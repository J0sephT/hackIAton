"""
config.py — Configuración central del sistema.
Cambia LLM_PROVIDER en .env para intercambiar el modelo sin tocar el agente.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ─── App ──────────────────────────────────────────────────────────────────────
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "8000"))
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "dev_secret")

# ─── LLM ──────────────────────────────────────────────────────────────────────
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

# ─── Notificaciones ───────────────────────────────────────────────────────────
HOSPITAL_WEBHOOK_URL = os.getenv("HOSPITAL_WEBHOOK_URL", "https://httpbin.org/post")
GESTOR_WEBHOOK_URL = os.getenv("GESTOR_WEBHOOK_URL", "https://httpbin.org/post")

# ─── Rutas de datos mock ──────────────────────────────────────────────────────
import pathlib
BASE_DIR = pathlib.Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
POLIZAS_PATH = DATA_DIR / "polizas.json"
HISTORIAL_PATH = DATA_DIR / "historial_medico.json"


def get_llm():
    """
    Factory que devuelve el LLM configurado.
    Para cambiar de proveedor: edita LLM_PROVIDER en .env
    """
    if LLM_PROVIDER == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=LLM_MODEL,
            temperature=0,
            api_key=os.getenv("OPENAI_API_KEY")
        )

    elif LLM_PROVIDER == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=LLM_MODEL,
            temperature=0,
            api_key=os.getenv("ANTHROPIC_API_KEY")
        )

    elif LLM_PROVIDER == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(
            model=LLM_MODEL,
            temperature=0,
            api_key=os.getenv("GROQ_API_KEY")
        )

    else:
        raise ValueError(f"Proveedor LLM no soportado: {LLM_PROVIDER}")
