"""Replaceable LLM layer (currently Google Gemini). Swap this file to use another provider."""
import json, os, re
from google import genai
from google.genai import types
from .config import LLM_MODEL

_client = None


def _c():
    global _client
    if _client is None:
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY is missing. Add it to your .env file.")
        _client = genai.Client(api_key=key)
    return _client


def _generate(system: str, user: str, max_tokens: int, json_mode: bool) -> str:
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        max_output_tokens=max_tokens * 4,  # Gemini 2.5 "thinking" tokens also count toward this limit
        response_mime_type="application/json" if json_mode else None,
    )
    r = _c().models.generate_content(model=LLM_MODEL, contents=user, config=cfg)
    return r.text or ""


def complete(system: str, user: str, max_tokens: int = 2000) -> str:
    return _generate(system, user, max_tokens, json_mode=False)


def complete_json(system: str, user: str, max_tokens: int = 2500) -> dict:
    raw = _generate(system + "\nRespond with ONE JSON object only.", user, max_tokens, json_mode=True)
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    s, e = raw.find("{"), raw.rfind("}")
    return json.loads(raw[s:e + 1])
