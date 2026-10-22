"""One LLM client for both providers via the `openai` SDK.

LLM_PROVIDER=openai (default) -> OPENAI_API_KEY; LLM_PROVIDER=nvidia -> NVIDIA_API_KEY on the
NVIDIA OpenAI-compatible endpoint. The model always comes from LLM_MODEL.
"""

import json
from typing import Any

from pydantic import BaseModel, ValidationError

from app.config import secret

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"


class LLMValidationError(Exception):
    """The model returned JSON that failed validation twice."""


_client: Any = None


def set_client(client: Any) -> None:
    """Inject a client (tests pass a fake with .chat.completions.create)."""
    global _client
    _client = client


def client() -> Any:
    global _client
    if _client is None:
        from openai import OpenAI

        if (secret("LLM_PROVIDER") or "openai").lower() == "nvidia":
            _client = OpenAI(base_url=NVIDIA_BASE_URL, api_key=secret("NVIDIA_API_KEY"))
        else:
            _client = OpenAI(api_key=secret("OPENAI_API_KEY"))
    return _client


def model() -> str:
    m = secret("LLM_MODEL")
    if not m:
        raise RuntimeError("LLM_MODEL is not set")
    return m


def _chat(messages: list[dict], json_mode: bool) -> str:
    kw: dict[str, Any] = {"response_format": {"type": "json_object"}} if json_mode else {}
    r = client().chat.completions.create(model=model(), messages=messages, temperature=0, **kw)
    return r.choices[0].message.content or ""


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
    return raw


def complete_json[M: BaseModel](system: str, user: str, model_cls: type[M]) -> M:
    """Ask for JSON matching `model_cls`; retry once with the validation error, then raise."""
    schema = json.dumps(model_cls.model_json_schema())
    messages = [
        {"role": "system", "content": f"{system}\n\nReply with ONE JSON object matching this "
                                      f"JSON schema, nothing else:\n{schema}"},
        {"role": "user", "content": user},
    ]
    err: Exception | None = None
    for _ in range(2):
        raw = _chat(messages, json_mode=True)
        try:
            return model_cls.model_validate_json(_strip_fences(raw))
        except ValidationError as e:
            err = e
            messages += [{"role": "assistant", "content": raw},
                         {"role": "user", "content": f"That JSON was invalid:\n{e}\n"
                                                     "Reply with the corrected JSON only."}]
    raise LLMValidationError(str(err))


ANSWER_SYSTEM = """You answer questions about the user's own credit card offers and rewards.
Use ONLY the DATA below (offers, card rules, transactions). Never invent offers, rates, merchants
or dates. If the DATA does not cover the question, say "My data doesn't cover that." and stop.
Be brief; show dollar math when you recommend a card."""


def answer_question(question: str, context: dict) -> str:
    data = json.dumps(context, default=str)
    return _chat([{"role": "system", "content": f"{ANSWER_SYSTEM}\n\nDATA:\n{data}"},
                  {"role": "user", "content": question}], json_mode=False).strip()
