import json
import os
import re
import traceback

try:
    from google import genai
    from google.genai import types
except Exception:  # pragma: no cover
    genai = None
    types = None

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
_client: "genai.Client | None" = None
_client_key: str | None = None


def get_client():
    global _client, _client_key
    if genai is None:
        raise RuntimeError("google-genai package not installed. Run: pip install google-genai")
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Set GOOGLE_API_KEY environment variable to use Gemini.")
    if _client is None or _client_key != api_key:
        _client = genai.Client(api_key=api_key)
        _client_key = api_key
    return _client


def check_model_available(model: str | None = None) -> tuple[bool, str]:
    model = model or DEFAULT_MODEL
    if genai is None:
        return False, "google-genai package not installed. Run: pip install google-genai"
    if not os.getenv("GOOGLE_API_KEY"):
        return False, "Set GOOGLE_API_KEY environment variable to use Gemini."
    return True, model


def _parse_json_response(content: str) -> dict | list:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", content)
        if match:
            return json.loads(match.group(1))
        raise ValueError(f"Model did not return valid JSON:\n{content[:500]}")


def chat_json(
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = None,
) -> dict | list:
    model = model or DEFAULT_MODEL
    client = get_client()

    config_kwargs: dict = {
        "system_instruction": system_prompt,
        "temperature": float(temperature),
        "response_mime_type": "application/json",
    }
    if max_tokens:
        config_kwargs["max_output_tokens"] = int(max_tokens)

    try:
        resp = client.models.generate_content(
            model=model,
            contents=user_prompt,
            config=types.GenerateContentConfig(**config_kwargs),
        )
        content = resp.text or ""
    except Exception as exc:
        tb = traceback.format_exc()
        raise RuntimeError(f"Gemini chat failed: {exc}\n{tb}")

    return _parse_json_response(content)
