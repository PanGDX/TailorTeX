"""
ai_manager.py
Handles all AI provider communication, API key persistence, and session logging.

Supported providers: OpenAI, Anthropic (Claude), Google Gemini
"""

import os
import json
import datetime
from pathlib import Path

# ── Directory where prompt/response logs are stored ──────────────────────────
AI_LOGS_DIR = "ai-logs"

# ── .env file path (project root) ─────────────────────────────────────────────
ENV_FILE = ".env"

# ── Structured JSON prompt sent to every provider ─────────────────────────────
SYSTEM_PROMPT = (
    "You are a LaTeX resume editor. "
    "The user will supply their current resume as raw LaTeX source and a job description. "
    "Your task is to tailor the resume content to better match the job description: "
    "reorder or emphasise relevant skills/experience, adjust wording, and ensure all "
    "achievements are framed in terms relevant to the role. "
    "RULES:\n"
    "  1. Output ONLY a valid JSON object — no prose, no markdown fences.\n"
    "  2. The JSON must have exactly one key: \"latex\", whose value is the full, "
    "     compilable LaTeX source as a single string.\n"
    "  3. Do NOT alter the document class, preamble packages, or overall structure "
    "     unless strictly required for correctness.\n"
    "  4. Do NOT add placeholder text or comments explaining your changes.\n"
    "  5. The LaTeX must compile with Tectonic without errors."
)

USER_PROMPT_TEMPLATE = (
    "=== CURRENT LATEX RESUME ===\n"
    "{latex}\n\n"
    "=== JOB DESCRIPTION ===\n"
    "{job_description}\n\n"
    "Return ONLY the JSON object as specified."
)

RETRY_PROMPT_TEMPLATE = (
    "The LaTeX you returned failed to compile. Here is the compiler error:\n\n"
    "{error}\n\n"
    "Please fix the LaTeX so it compiles cleanly and return the corrected JSON object."
)


# ══════════════════════════════════════════════════════════════════════════════
# .env helpers
# ══════════════════════════════════════════════════════════════════════════════

def _read_env() -> dict[str, str]:
    """Parse .env into a dict. Lines without '=' are ignored."""
    env: dict[str, str] = {}
    if not Path(ENV_FILE).exists():
        return env
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    return env


def _write_env(env: dict[str, str]):
    """Overwrite .env with the provided dict."""
    lines = [f"{k}={v}\n" for k, v in env.items()]
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.writelines(lines)


def load_api_key(provider: str) -> str:
    """Return the stored API key for *provider*, or '' if not set."""
    key_name = _env_key_name(provider)
    return _read_env().get(key_name, "")


def save_api_key(provider: str, api_key: str):
    """Persist the API key for *provider* into .env."""
    env = _read_env()
    env[_env_key_name(provider)] = api_key
    _write_env(env)


def load_provider() -> str:
    """Return the last-used provider, or '' if none set."""
    return _read_env().get("AI_PROVIDER", "")


def save_provider(provider: str):
    """Persist the selected provider name into .env."""
    env = _read_env()
    env["AI_PROVIDER"] = provider
    _write_env(env)


def _env_key_name(provider: str) -> str:
    mapping = {
        "OpenAI":         "OPENAI_API_KEY",
        "Claude":         "ANTHROPIC_API_KEY",
        "Google Gemini":  "GEMINI_API_KEY",
    }
    return mapping.get(provider, f"{provider.upper()}_API_KEY")


# ══════════════════════════════════════════════════════════════════════════════
# Session log helpers
# ══════════════════════════════════════════════════════════════════════════════

def _session_dir(session_id: str) -> Path:
    p = Path(AI_LOGS_DIR) / session_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def _now_str() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H-%M-%S")


def log_exchange(session_id: str, attempt: int, prompt: str, response_raw: str):
    """
    Save one prompt/response pair to ai-logs/<session_id>/attempt_N.json.
    """
    d = _session_dir(session_id)
    record = {
        "timestamp": _now_str(),
        "attempt":   attempt,
        "prompt":    prompt,
        "response":  response_raw,
    }
    path = d / f"attempt_{attempt}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)


def session_log_dir(session_id: str) -> str:
    return str(_session_dir(session_id))


# ══════════════════════════════════════════════════════════════════════════════
# Provider calls
# ══════════════════════════════════════════════════════════════════════════════

def _parse_latex_from_response(raw: str) -> str:
    """
    Extract the 'latex' field from a JSON response.
    Strips markdown code fences if the model wrapped the JSON anyway.
    Raises ValueError if the JSON cannot be parsed or the key is missing.
    """
    text = raw.strip()
    # Strip ```json ... ``` or ``` ... ``` fences
    if text.startswith("```"):
        lines = text.splitlines()
        # drop first and last fence lines
        inner = []
        in_block = False
        for line in lines:
            if line.startswith("```") and not in_block:
                in_block = True
                continue
            if line.startswith("```") and in_block:
                break
            if in_block:
                inner.append(line)
        text = "\n".join(inner).strip()

    data = json.loads(text)
    if "latex" not in data:
        raise ValueError("Response JSON does not contain a 'latex' key.")
    return data["latex"]


def call_openai(api_key: str, messages: list[dict]) -> str:
    """
    Call OpenAI chat completions. Returns raw response text.
    Requires: pip install openai
    """
    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        raise ImportError(
            "The 'openai' package is not installed. Run: pip install openai"
        )
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content or ""


def call_claude(api_key: str, messages: list[dict]) -> str:
    """
    Call Anthropic Claude messages API. Returns raw response text.
    Requires: pip install anthropic
    """
    try:
        import anthropic  # type: ignore
    except ImportError:
        raise ImportError(
            "The 'anthropic' package is not installed. Run: pip install anthropic"
        )
    # Claude separates system from messages
    system_msg = messages[0]["content"] if messages[0]["role"] == "system" else ""
    user_msgs = [m for m in messages if m["role"] != "system"]

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4096,
        system=system_msg,
        messages=user_msgs,
    )
    return response.content[0].text if response.content else ""


def call_gemini(api_key: str, messages: list[dict]) -> str:
    """
    Call Google Gemini via the google-genai SDK (v2+). Returns raw response text.
    Requires: pip install google-genai

    The internal `messages` list follows the shared format used by all providers:
        [{"role": "system"|"user"|"assistant", "content": str}, ...]

    Mapping to the google-genai SDK:
      - The "system" message → GenerateContentConfig.system_instruction
      - "user" / "assistant" turns → list[types.Content] passed as `contents`,
        using role "user" and "model" respectively.

    JSON output is enforced via response_mime_type + response_json_schema so the
    model is constrained at the API level rather than relying on prompt-only
    instructions. This avoids the need to strip markdown fences.
    """
    try:
        from google import genai                      # type: ignore
        from google.genai import types as gtypes      # type: ignore
    except ImportError:
        raise ImportError(
            "The 'google-genai' package is not installed. "
            "Run: pip install google-genai"
        )

    # ── Separate system instruction from the conversation turns ───────────────
    system_instruction: str | None = None
    conversation: list[dict] = []
    for m in messages:
        if m["role"] == "system":
            system_instruction = m["content"]
        else:
            conversation.append(m)

    # ── Build types.Content list ───────────────────────────────────────────────
    # The google-genai SDK expects role to be "user" or "model".
    contents: list[gtypes.Content] = []
    for m in conversation:
        sdk_role = "model" if m["role"] == "assistant" else "user"
        contents.append(
            gtypes.Content(
                role=sdk_role,
                parts=[gtypes.Part.from_text(text=m["content"])],
            )
        )

    # ── JSON schema: enforce {"latex": "<string>"} at the API level ───────────
    latex_schema = {
        "type": "object",
        "properties": {
            "latex": {
                "type": "string",
                "description": "The full, compilable LaTeX resume source.",
            }
        },
        "required": ["latex"],
    }

    config = gtypes.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.3,
        max_output_tokens=8192,
        response_mime_type="application/json",
        response_json_schema=latex_schema,
    )

    # ── Call the API, close client when done ──────────────────────────────────
    with genai.Client(api_key=api_key) as client:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents,
            config=config,
        )

    return response.text or ""


_PROVIDER_CALLERS = {
    "OpenAI":        call_openai,
    "Claude":        call_claude,
    "Google Gemini": call_gemini,
}


# ══════════════════════════════════════════════════════════════════════════════
# Main entry point used by the GUI
# ══════════════════════════════════════════════════════════════════════════════

def build_initial_messages(latex: str, job_description: str) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": USER_PROMPT_TEMPLATE.format(
                latex=latex,
                job_description=job_description,
            ),
        },
    ]


def build_retry_messages(
    messages: list[dict], bad_latex: str, compile_error: str
) -> list[dict]:
    """Append the assistant reply and a follow-up user correction request."""
    return messages + [
        {"role": "assistant", "content": json.dumps({"latex": bad_latex})},
        {
            "role": "user",
            "content": RETRY_PROMPT_TEMPLATE.format(error=compile_error),
        },
    ]


def request_latex(
    provider: str,
    api_key: str,
    messages: list[dict],
    session_id: str,
    attempt: int,
) -> tuple[str, str]:
    """
    Send *messages* to *provider* and return (latex_source, raw_response).
    Logs the exchange to disk. Raises on network/parse errors.
    """
    caller = _PROVIDER_CALLERS.get(provider)
    if caller is None:
        raise ValueError(f"Unknown provider: {provider!r}")

    raw = caller(api_key, messages)
    # Log full exchange: last user message + raw response
    log_exchange(
        session_id=session_id,
        attempt=attempt,
        prompt=messages[-1]["content"],
        response_raw=raw,
    )
    latex = _parse_latex_from_response(raw)
    return latex, raw
