from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

import httpx

CACHE_PATH = Path(__file__).resolve().parent / "cache" / "scene2.json"
MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"
MODEL = "mistral-small-latest"
TIMEOUT_SECONDS = 4


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w’'-]+\b", text, flags=re.UNICODE))


def validate_case(
    result: dict[str, Any], fired_rule_refs: set[str]
) -> dict[str, Any]:
    required = {"summary", "explanation", "citations", "reportDraft"}
    if not required.issubset(result):
        raise ValueError("case response is missing required fields")
    citations = result["citations"]
    if not isinstance(citations, list) or not set(citations).issubset(fired_rule_refs):
        raise ValueError("case citations must be a subset of fired rule references")
    explanation = str(result["explanation"])
    if _word_count(explanation) > 120:
        raise ValueError("case explanation exceeds 120 words")
    return {
        "summary": str(result["summary"]),
        "explanation": explanation,
        "citations": citations,
        "reportDraft": str(result["reportDraft"]),
    }


def _cached_case(fired_rule_refs: set[str]) -> dict[str, Any]:
    cached = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    citations = [
        reference
        for reference in cached.get("citations", [])
        if reference in fired_rule_refs
    ]
    case = validate_case(cached | {"citations": citations}, fired_rule_refs)
    return case | {"cached": True}


def _parse_content(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        raise ValueError("Mistral response content must be JSON text")
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?|```$", "", cleaned, flags=re.IGNORECASE).strip()
    result = json.loads(cleaned)
    if not isinstance(result, dict):
        raise ValueError("Mistral response must be a JSON object")
    return result


async def investigate(
    events: list[dict[str, Any]],
    fired_rule_refs: set[str] | list[str],
    *,
    allow_live: bool = True,
) -> dict[str, Any]:
    allowed = set(fired_rule_refs)
    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key or not allow_live:
        return _cached_case(allowed)

    prompt = {
        "events": events,
        "allowedCitations": sorted(allowed),
        "outputSchema": {
            "summary": "string",
            "explanation": "string, at most 120 words",
            "citations": ["rule reference from allowedCitations"],
            "reportDraft": "string",
        },
    }
    try:
        async with asyncio.timeout(TIMEOUT_SECONDS):
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                response = await client.post(
                    MISTRAL_URL,
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": MODEL,
                        "temperature": 0,
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "Build a concise payment case using only supplied "
                                    "events. Cite only allowed rule references. Return JSON."
                                ),
                            },
                            {"role": "user", "content": json.dumps(prompt)},
                        ],
                        "response_format": {"type": "json_object"},
                    },
                )
                response.raise_for_status()
                payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        case = validate_case(_parse_content(content), allowed)
        return case | {"cached": False}
    except (httpx.HTTPError, TimeoutError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return _cached_case(allowed)
