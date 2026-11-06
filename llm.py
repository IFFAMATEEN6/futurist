"""Optional language assistance: Groq primary/fallback models, then configured Ollama.

Every agent calls ask(). It never raises.
Returns (result, note):
  - result: str, or dict/list when want_json=True, or None if every provider failed
  - note:   provider name that answered, or a short error summary (put it in the message log)
If result is None, the agent must use its plain-code fallback.
"""
import json
import re
import time
import urllib.error
import urllib.request

import config

GROQ_API_KEY = config.GROQ_API_KEY
GROQ_MODEL = config.GROQ_MODEL

TIMEOUT = max(1, config.LLM_TIMEOUT)
MAX_RETRIES = max(0, config.LLM_RETRIES)


class RateLimitError(Exception):
    pass


class ProviderError(Exception):
    def __init__(self, message, *, transient=False):
        super().__init__(message)
        self.transient = transient


# ---------- providers ----------

def _post_json(url, body, headers=None):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "opportunity-network/1.0")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise RateLimitError(f"HTTP 429 from {url}")
        raise ProviderError(f"HTTP {e.code} from {url}", transient=e.code >= 500)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ProviderError(f"cannot reach {url}", transient=True)


def _groq(prompt, system, want_json, model=None):
    if not GROQ_API_KEY:
        raise ProviderError("GROQ_API_KEY missing")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    body = {"model": model or GROQ_MODEL, "messages": messages, "temperature": config.LLM_TEMPERATURE,
            "max_tokens": max(1, config.LLM_MAX_TOKENS)}
    if want_json:
        body["response_format"] = {"type": "json_object"}
    out = _post_json(
        "https://api.groq.com/openai/v1/chat/completions",
        body,
        {"Authorization": f"Bearer {GROQ_API_KEY}"},
    )
    try:
        return out["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise ProviderError("unexpected Groq response")


# Order matters. Tests can replace this list with fake providers.
def _groq_fallback(prompt, system, want_json):
    return _groq(prompt, system, want_json, config.GROQ_FALLBACK_MODEL)


def _ollama(prompt, system, want_json):
    if not config.OLLAMA_MODEL:
        raise ProviderError("local model is not configured")
    body = {"model": config.OLLAMA_MODEL, "prompt": prompt, "system": system, "stream": False,
            "options": {"temperature": config.LLM_TEMPERATURE, "num_predict": config.LLM_MAX_TOKENS}}
    if want_json:
        body["format"] = "json"
    return _post_json(config.OLLAMA_URL.rstrip("/") + "/api/generate", body).get("response", "")


PROVIDERS = [("groq", _groq), ("groq fallback", _groq_fallback)]
if config.OLLAMA_MODEL:
    PROVIDERS.append(("ollama", _ollama))


# ---------- helpers ----------

def _parse_json(text):
    """Strip ``` fences and parse. Raises ValueError if not valid JSON."""
    if not text:
        raise ValueError("empty response")
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.IGNORECASE).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    # fall back to the first {...} or [...] block
    m = re.search(r"(\{.*\}|\[.*\])", t, flags=re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    raise ValueError("response is not valid JSON")


# ---------- public API ----------

def ask(prompt, system="", want_json=False):
    """Try each provider in order. Never raises. Returns (result, note)."""
    if want_json:
        prompt = prompt + "\n\nRespond with valid JSON only. No extra text."

    errors = []
    for name, fn in PROVIDERS:
        for attempt in range(MAX_RETRIES + 1):
            try:
                text = fn(prompt, system, want_json)
                if want_json:
                    return _parse_json(text), name
                text = (text or "").strip()
                if not text:
                    raise ValueError("empty response")
                return text, name
            except RateLimitError:
                if attempt < MAX_RETRIES:
                    time.sleep(2 ** (attempt + 1))   # 2s, 4s
                    continue
                errors.append(f"{name}: rate limited")
                break
            except ValueError as e:                  # bad JSON or empty: retry same provider
                if attempt < MAX_RETRIES:
                    continue
                errors.append(f"{name}: {e}")
                break
            except ProviderError as e:
                if e.transient and attempt < MAX_RETRIES:
                    time.sleep(min(2 ** attempt, 4))
                    continue
                errors.append(f"{name}: {str(e)[:120]}")
                break
            except Exception as e:                   # missing key, offline, HTTP error
                errors.append(f"{name}: {str(e)[:120]}")
                break

    return None, "all LLM providers failed (" + "; ".join(errors) + ")"
