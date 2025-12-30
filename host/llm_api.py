class ILLMProvider(ABC):
    """
    Interface para providers LLM (Ollama, OpenAI, etc).
    Permite mocks, testes e extensão futura.
    """
    def chat(self, messages: list[dict]) -> tuple[str, dict]:
        raise NotImplementedError

    def check_vision_support(self, text_only: bool = False) -> None:
        raise NotImplementedError

    # Métodos utilitários opcionais:
    def download_model(self, model: str):
        pass
from __future__ import annotations

import json
import time
import requests
from abc import ABC, abstractmethod


class LLMProviderBase(ABC):
        # Implementa ILLMProvider para polimorfismo e mocks
    """Interface base para providers LLM. Permite mocks e extensão futura."""
    def __init__(self, url: str, model: str, timeout: float = 60.0):
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout

    @abstractmethod
    def chat(self, messages: list[dict]) -> tuple[str, dict]:
        """
        Envia mensagens para o LLM.
        Retorna (conteúdo_da_resposta, metadados).
        """
        pass

    @abstractmethod
    def check_vision_support(self, text_only: bool = False) -> None:
        pass
from typing import Iterator, Optional

import logging
from common import post_json_with_retries


# Alias para compatibilidade retroativa
LLMProvider = LLMProviderBase


class OllamaProvider(LLMProviderBase):
    def chat(self, messages: list[dict]) -> tuple[str, dict]:
        chat_url = f"{self.url}/api/chat"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        started = time.time()
        logging.info(f"[Ollama] Aguardando resposta do modelo {self.model}...")
        try:
            resp, elapsed_ms = post_json_with_retries(chat_url, payload, timeout=self.timeout, retries=2, retry_delay=2.0, description="Ollama chat")
            resp.raise_for_status()
            data = resp.json()
            content = data["message"]["content"]
            meta = {
                "provider": "ollama",
                "model": self.model,
                "url": self.url,
                "status_code": resp.status_code,
                "latency_ms": elapsed_ms,
                "eval_count": data.get("eval_count"),
                "eval_duration": data.get("eval_duration"),
            }
            logging.info(f"[Ollama] Status: {resp.status_code}, Time: {elapsed_ms}ms")
            return content, meta
        except Exception as e:
            logging.error(f"[Ollama] Erro na chamada ao modelo: {e}")
            raise

    def check_vision_support(self, text_only: bool = False) -> None:
        if text_only:
            return
        # Lógica simplificada de verificação (baseada no script original)
        # Em refatoração real, moveria _fetch_ollama_model_metadata pra cá.
        pass

    def download_model(self, model: str) -> Iterator[str]:
        pull_url = f"{self.url}/api/pull"
        resp = requests.post(pull_url, json={"model": model}, stream=True, timeout=10)
        resp.raise_for_status()
        
        for line in resp.iter_lines():
            if not line: continue
            try:
                data = json.loads(line.decode("utf-8"))
                status = data.get("status") or data.get("message")
                if status:
                    yield status
            except Exception:
                pass


class OpenAICompatProvider(LLMProviderBase):
    def chat(self, messages: list[dict]) -> tuple[str, dict]:
        # Ajuste de URL para comtatibilidade com /v1/chat/completions
        endpoint = self.url
        if not endpoint.endswith("/chat/completions"):
            endpoint = f"{endpoint}/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        started = time.time()
        try:
            resp, elapsed_ms = post_json_with_retries(endpoint, payload, timeout=self.timeout, retries=2, retry_delay=2.0, description="OpenAICompat chat")
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            meta = {
                "provider": "openai-compat",
                "model": self.model,
                "url": self.url,
                "status_code": resp.status_code,
                "latency_ms": elapsed_ms,
                "usage": data.get("usage"),
            }
            logging.info(f"[OpenAICompat] Status: {resp.status_code}, Time: {elapsed_ms}ms")
            return content, meta
        except Exception as e:
            logging.error(f"[OpenAICompat] Erro na chamada ao modelo: {e}")
            raise

    def check_vision_support(self, text_only: bool = False) -> None:
        pass
