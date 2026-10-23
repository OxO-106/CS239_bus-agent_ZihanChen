"""Ollama client. Every agent calls chat(); config comes from .env with per-agent overrides."""
import base64
import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_env(path=ROOT / ".env"):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


_load_env()


def _setting(name, agent, default):
    if agent:
        value = os.environ.get(f"{name}_{agent.upper()}")
        if value is not None:
            return value
    return os.environ.get(name, default)


def encode_image(path):
    return base64.b64encode(Path(path).read_bytes()).decode()


def chat(messages, tools=None, format=None, agent=None, timeout=300):
    """POST /api/chat and return the full response dict (message, eval_count, durations)."""
    body = {
        "model": _setting("MODEL", agent, "gemma4:12b"),
        "messages": messages,
        "stream": False,
        "think": _setting("THINK", agent, "false").lower() == "true",
        "keep_alive": os.environ.get("OLLAMA_KEEP_ALIVE", "30m"),
        "options": {"num_ctx": int(os.environ.get("OLLAMA_NUM_CTX", "16384")), "temperature": 0},
    }
    if tools:
        body["tools"] = tools
    if format:
        body["format"] = format
    url = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/") + "/api/chat"
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)
