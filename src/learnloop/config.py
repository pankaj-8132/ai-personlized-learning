"""Environment loading, paths, and settings."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
SAMPLES_DIR = DATA_DIR / "samples"
CACHE_DIR = DATA_DIR / "cache"
OUTPUT_DIR = DATA_DIR / "output"

for d in (SAMPLES_DIR, CACHE_DIR, OUTPUT_DIR):
    d.mkdir(parents=True, exist_ok=True)


@dataclass
class Settings:
    pageindex_api_key: str = field(default_factory=lambda: os.environ["PAGEINDEX_API_KEY"])
    gemini_api_key: str = field(default_factory=lambda: os.environ["GEMINI_API_KEY"])
    gemini_model_reasoning: str = field(
        default_factory=lambda: os.environ.get("GEMINI_MODEL_REASONING", "gemini-3.5-flash")
    )
    gemini_model_answer: str = field(
        default_factory=lambda: os.environ.get("GEMINI_MODEL_ANSWER", "gemini-3.5-flash-lite")
    )
    llm_concurrency: int = field(
        default_factory=lambda: int(os.environ.get("LLM_CONCURRENCY", "3"))
    )
    llm_delay_ms: int = field(
        default_factory=lambda: int(os.environ.get("LLM_DELAY_MS", "200"))
    )


def get_settings() -> Settings:
    return Settings()
