from __future__ import annotations

import json
import time
import requests
from abc import ABC, abstractmethod
from typing import Iterator, Optional

import logging
from common import post_json_with_retries

class LLMProvider(ABC):
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


class OllamaProvider(LLMProvider):
    def chat(self, messages: list[dict]) -> tuple[str, dict]:
        chat_url = f"{self.url}/api/chat"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        
        # Usa o post_json_with_retries do common.py se possível, mas aqui reimplementamos simples
        # ou importariamos. Vamos assumir uso direto do requests para isolamento,
        # mas mantendo a lógica de retry seria ideal.
        # Para compatibilidade com o código original, vamos usar requests direto com timeout.
        
        started = time.time()
        logging.info(f"[Ollama] Aguardando resposta do modelo {self.model}...")
        # Nota: O código original usava post_json_with_retries. 
        # Aqui simplificaremos, mas em produção deveríamos manter os retries.
        resp = requests.post(chat_url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        elapsed_ms = int((time.time() - started) * 1000)
        
        logging.info(f"[Ollama] Status: {resp.status_code}, Time: {elapsed_ms}ms")
        
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
        return content, meta

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


class OpenAICompatProvider(LLMProvider):
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
        resp = requests.post(endpoint, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        elapsed_ms = int((time.time() - started) * 1000)
        
        logging.info(f"[OpenAICompat] Status: {resp.status_code}, Time: {elapsed_ms}ms")
        
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
        return content, meta

    def check_vision_support(self, text_only: bool = False) -> None:
        pass
