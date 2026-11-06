"""LLM wrapper: Groq only (Llama model). Plain-code fallback in each agent if it fails.

Every agent calls ask(). It never raises.
Returns (result, note):
  - result: str, or dict/list when want_json=True, or None if every provider failed
  - note:   provider name that answered, or a short error summary (put it in the message log)
If result is None, the agent must use its plain-code fallback.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

TIMEOUT = 30          # seconds per request
MAX_RETRIES = 2       # extra tries per provider (rate limit or bad JSON)


class RateLimitError(Exception):
    pass


class ProviderError(Exception):
    pass


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
        raise ProviderError(f"HTTP {e.code} from {url}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ProviderError(f"cannot reach {url}: {e}")


def _groq(prompt, system, want_json):
    if not GROQ_API_KEY:
        raise ProviderError("GROQ_API_KEY missing")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    body = {"model": GROQ_MODEL, "messages": messages, "temperature": 0.2}
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
PROVIDERS = [("groq", _groq)]


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
            except Exception as e:                   # missing key, offline, HTTP error
                errors.append(f"{name}: {str(e)[:120]}")
                break

    return None, "all LLM providers failed (" + "; ".join(errors) + ")"