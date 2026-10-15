"""
A thin, shared wrapper around the Groq API.

Every AI feature in LifeFlow (multilingual request parsing, the
role-aware assistant, and the plain-language shortage commentary) goes
through the two functions here, so there is exactly one place that
holds the API key, the model name, and the "AI isn't configured" fallback.

Groq exposes an OpenAI-compatible /chat/completions endpoint, so this
talks to it with plain HTTP (via `requests`) rather than a dedicated
SDK -- one less package to install, and it's trivial to point at a
different OpenAI-compatible provider later by changing GROQ_API_BASE_URL.

To enable these features, set an environment variable before starting
the backend:

    export GROQ_API_KEY="gsk_..."

Get a free key at https://console.groq.com/keys

Nothing else in the app breaks if this is left unset -- every AI
endpoint simply returns a clear, friendly message saying the assistant
isn't configured yet, instead of raising an error.
"""
import json
import re
from typing import Optional

import requests

from app.config import GROQ_API_KEY, GROQ_API_BASE_URL, AI_MODEL

NOT_CONFIGURED_MESSAGE = (
    "The AI assistant isn't set up on this server yet. Ask your administrator to set "
    "the GROQ_API_KEY environment variable (get a free key at https://console.groq.com/keys) "
    "and restart the backend to turn it on."
)

REQUEST_TIMEOUT_SECONDS = 20


def is_ai_configured() -> bool:
    return bool(GROQ_API_KEY)


FALLBACK_MODEL = "openai/gpt-oss-20b"  # smaller sibling of the default model, near-always-available on Groq


def _chat_completion(system_prompt: str, user_message: str, max_tokens: int, response_format_json: bool = False, _model: Optional[str] = None) -> Optional[str]:
    """Low-level call to Groq's chat completions endpoint. Returns the raw text reply, or None on any failure."""
    if not is_ai_configured():
        return None

    model = _model or AI_MODEL
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": 0.3,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    }
    if response_format_json:
        payload["response_format"] = {"type": "json_object"}

    try:
        response = requests.post(
            f"{GROQ_API_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if not response.ok:
            # Print the real reason to the backend's own console/log, since the
            # person using the app only ever sees a friendly fallback message.
            print(f"[ai_client] Groq API returned {response.status_code} for model '{model}': {response.text[:500]}")
            # A 400/404 here usually means the model name is wrong or was
            # decommissioned (Groq retires older models over time) -- retry
            # once with a small, generally-available model before giving up.
            if response.status_code in (400, 404) and model != FALLBACK_MODEL:
                return _chat_completion(system_prompt, user_message, max_tokens, response_format_json, _model=FALLBACK_MODEL)
            return None
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except Exception as error:  # noqa: BLE001 -- callers convert this into a friendly fallback
        print(f"[ai_client] Groq API call failed for model '{model}': {error!r}")
        return None


def ask_ai(system_prompt: str, user_message: str, max_tokens: int = 700) -> str:
    """
    Sends one message to the configured Groq model with the given
    system prompt and returns the plain-text reply. Used for the chat
    assistant and for the plain-language shortage commentary.
    """
    if not is_ai_configured():
        return NOT_CONFIGURED_MESSAGE

    reply = _chat_completion(system_prompt, user_message, max_tokens)
    if reply is None:
        return "The AI assistant hit an error and couldn't respond. Please try again shortly."
    return reply.strip() or "I couldn't generate a response just now -- please try again."


def ask_ai_for_json(system_prompt: str, user_message: str, max_tokens: int = 500) -> Optional[dict]:
    """
    Same as ask_ai, but instructs the model to reply with JSON only,
    and parses it. Returns None (never raises) if the AI isn't
    configured or the reply can't be parsed, so callers can fall back
    to asking the person to fill the form in by hand.
    """
    if not is_ai_configured():
        return None

    strict_system_prompt = (
        system_prompt
        + "\n\nRespond with ONLY a single valid JSON object. No prose, no markdown code fences, "
          "no explanation before or after -- just the JSON object itself."
    )
    raw_text = _chat_completion(strict_system_prompt, user_message, max_tokens, response_format_json=True)
    if raw_text is None:
        return None

    cleaned = raw_text.strip()
    cleaned = re.sub(r"^```(json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except Exception:  # noqa: BLE001 -- caller falls back to a manual form
        return None


GROQ_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"


def ask_ai_vision_json(system_prompt: str, instruction: str, image_base64: str, mime_type: str) -> Optional[dict]:
    """Sends one image plus an instruction to a Groq vision model and parses a JSON reply (None on any failure)."""
    if not is_ai_configured():
        return None
    import os
    payload = {
        "model": os.environ.get("GROQ_VISION_MODEL", GROQ_VISION_MODEL),
        "max_tokens": 400,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": system_prompt + " Reply with ONLY a JSON object."},
            {"role": "user", "content": [
                {"type": "text", "text": instruction},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_base64}"}},
            ]},
        ],
    }
    try:
        response = requests.post(
            f"{GROQ_API_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json=payload, timeout=40,
        )
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"].strip()
        text = re.sub(r"^```(json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return None


GROQ_WHISPER_MODEL = "whisper-large-v3-turbo"


def transcribe_audio(file_bytes: bytes, filename: str, content_type: str, language: Optional[str] = None) -> Optional[str]:
    """
    Sends an audio recording to Groq's hosted Whisper model and returns
    the transcript (auto-detects language). Returns None on any failure
    or if AI isn't configured -- callers fall back to typing.
    """
    if not is_ai_configured():
        return None
    try:
        form = {"model": GROQ_WHISPER_MODEL}
        if language in ("en", "ur", "sd"):
            form["language"] = language   # a hint helps Urdu and Sindhi a lot
        response = requests.post(
            f"{GROQ_API_BASE_URL}/audio/transcriptions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            files={"file": (filename, file_bytes, content_type or "audio/webm")},
            data=form,
            timeout=40,
        )
        if not response.ok and "language" in form:
            # Some model versions reject a language code (Sindhi especially). Retry without the hint.
            form.pop("language")
            response = requests.post(
                f"{GROQ_API_BASE_URL}/audio/transcriptions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                files={"file": (filename, file_bytes, content_type or "audio/webm")},
                data=form, timeout=40,
            )
        if not response.ok:
            print(f"[ai_client] Whisper transcription returned {response.status_code}: {response.text[:300]}")
            return None
        return response.json().get("text", "").strip() or None
    except Exception as error:  # noqa: BLE001
        print(f"[ai_client] Whisper transcription failed: {error!r}")
        return None


# Backward-compatible aliases (older parts of the codebase were written
# against a Claude-specific name for these two functions).
ask_claude = ask_ai
ask_claude_for_json = ask_ai_for_json
