"""
Unified LLM caller for the GEO extraction pipeline.

Public API:
    call_model(model_id, prompt) -> raw response text
    parse_json(text) -> dict   (with fallback for trailing junk)

Tunables:
    default_models    which models to run by default for multi-model studies
    max_retries       per-call retry budget
    retry_backoff     base seconds; doubles per attempt
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Optional

# default model list
default_models = [
    os.environ.get("gemini_model", "gemini-3.5-flash"),
]

max_retries = int(os.environ.get("gemini_max_retries", "5"))
retry_backoff = float(os.environ.get("gemini_retry_backoff", "2"))
retry_backoff_cap = float(os.environ.get("gemini_retry_backoff_cap", "60"))


def is_gemini(model_id: str) -> bool:
    return model_id.startswith("gemini")


def call_gemini(model_id: str, prompt: str) -> str:
    """Call Google Gemini with retries. Returns raw JSON-formatted text."""
    from google import genai

    api_key = os.environ.get("gemini_api_key", "")
    if not api_key:
        raise RuntimeError("gemini_api_key not set")

    client = genai.Client(api_key=api_key)
    service_tier = os.environ.get("gemini_service_tier", "").strip()
    timeout_ms = int(os.environ.get("gemini_timeout_ms", "900000" if service_tier == "flex" else "120000"))
    config = {
        "response_mime_type": "application/json",
    }
    if service_tier:
        config["service_tier"] = service_tier
        config["http_options"] = {"timeout": timeout_ms}

    last_err: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.models.generate_content(
                model=model_id,
                contents=prompt,
                config=config,
            )
            return resp.text or ""
        except Exception as e:
            last_err = e
            print(f"    {model_id} attempt {attempt}/{max_retries}: {e}")
            if "400 INVALID_ARGUMENT" in str(e) or "FreeTier" in str(e) or "free_tier" in str(e):
                break
            if attempt < max_retries:
                time.sleep(min(retry_backoff * (2 ** (attempt - 1)), retry_backoff_cap))
    raise RuntimeError(f"{model_id} failed after {max_retries} retries: {last_err}")


def call_model(model_id: str, prompt: str) -> str:
    """Dispatch to the right backend based on the model id prefix."""
    if is_gemini(model_id):
        return call_gemini(model_id, prompt)
    raise ValueError(f"Unrecognized model id: {model_id!r}")


def parse_json(text: str) -> dict:
    """Robust JSON parse with fallbacks for the common Gemini/GPT quirks.

    Handles:
      - markdown code fences (```json ... ```)
      - trailing junk after a valid JSON object (uses raw_decode)
      - array-wrapped single object: [{...}] -> {...}
    Returns {} on total failure.
    """
    text = (text or "").strip()
    if not text:
        return {}
    # strip code fences
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    # primary parse
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # try parsing just the first valid JSON value at the start
        try:
            decoder = json.JSONDecoder()
            data, _ = decoder.raw_decode(text)
        except Exception:
            return {}
    # unwrap single-element list (some Gemini runs do this)
    if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict):
        data = data[0]
    return data if isinstance(data, dict) else {}


def format_evidence(evidence) -> str:
    """Flatten a list of {quote, source} dicts to a single string for an Excel cell."""
    if not evidence:
        return ""
    if isinstance(evidence, list):
        parts = []
        for e in evidence:
            if isinstance(e, dict):
                q = e.get("quote", "")
                s = e.get("source", "")
                parts.append(f'"{q}"  [{s}]' if s else f'"{q}"')
            else:
                parts.append(str(e))
        return "\n---\n".join(parts)
    return str(evidence)
