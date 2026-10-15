import os
from pathlib import Path

# Basic settings for the application.
# In a real deployment these values should come from environment variables,
# not from plain text in the code.

# Load backend/.env (if present) into the process environment, so anything
# you set there works the same as `export`ing it -- without this, a .env
# file just sits on disk unread. python-dotenv is intentionally imported
# with a fallback: if it isn't installed yet, .env is skipped rather than
# crashing the whole app, and real `export`ed variables still work either way.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

SECRET_KEY = os.environ.get("LIFEFLOW_SECRET_KEY", "change_this_secret_key_before_deployment")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 30  # 30 days, so login/history stays available between visits

DATABASE_URL = os.environ.get("LIFEFLOW_DATABASE_URL", "sqlite:///./lifeflow.db")

# --- AI features -----------------------------------------------------------
# LifeFlow's AI features (multilingual request parsing, the role-aware
# assistant, and shortage forecasting commentary) call Groq's API, which
# serves fast, free-tier-friendly open models (Llama, etc.) over an
# OpenAI-compatible endpoint. Set GROQ_API_KEY in your environment before
# running the backend; without it, the AI endpoints reply with a clear
# "not configured" message instead of crashing, so the rest of the app
# keeps working normally.
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_API_BASE_URL = os.environ.get("GROQ_API_BASE_URL", "https://api.groq.com/openai/v1")
AI_MODEL = os.environ.get("LIFEFLOW_AI_MODEL", "openai/gpt-oss-120b")
