"""Interface única para qualquer provider de LLM (OpenAI-compatible)."""
from __future__ import annotations
import os
import json
import urllib.request


class LLMProvider:
    """Provider genérico estilo OpenAI chat/completions.
    Funciona com DeepSeek (api.deepseek.com) e Ollama (modo /v1)."""

    def __init__(self, name: str, base_url: str, model: str,
                 api_key: str | None = None,
                 temperature: float = 0.3, max_tokens: int = 4096):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens

    def chat(self, system: str, user: str) -> str:
        return self.chat_messages([
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ])

    def chat_messages(self, messages: list[dict]) -> str:
        """Completa a partir de uma lista de mensagens (multi-turno)."""
        url = f"{self.base_url}/v1/chat/completions" \
            if "ollama" in self.name or "11434" in self.base_url \
            else f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "messages": messages,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
        return data["choices"][0]["message"]["content"]


def build_provider(name: str, cfg: dict) -> LLMProvider:
    api_key = None
    if "api_key_env" in cfg:
        api_key = os.environ.get(cfg["api_key_env"])
    return LLMProvider(
        name=name,
        base_url=cfg["base_url"],
        model=cfg["model"],
        api_key=api_key,
        temperature=cfg.get("temperature", 0.3),
        max_tokens=cfg.get("max_tokens", 4096),
    )
