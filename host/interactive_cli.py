#!/usr/bin/env python3
"""
Interface interativa simples para orquestrar os hosts MCP (Ollama ou LM Studio).

Ela guia o usuário pelos parâmetros principais (modo, fonte, filtros, dry-run, etc.)
e monta o comando completo para o host escolhido. A intenção é reduzir erros de
digitação e deixar mais claro quais opções estão sendo usadas.
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import mcp_host_lmstudio
import mcp_host_ollama

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_LIMIT = 200
DEFAULT_MIN_RATING = -2


@dataclass
class RunConfig:
    host: str  # "ollama" ou "lmstudio"
    mode: str
    source: str
    path_contains: Optional[str] = None
    tag: Optional[str] = None
    min_rating: int = DEFAULT_MIN_RATING
    only_raw: bool = False
    dry_run: bool = True
    limit: int = DEFAULT_LIMIT
    model: Optional[str] = None
    llm_url: Optional[str] = None
    target_dir: Optional[str] = None
    prompt_file: Optional[Path] = None
    text_only: bool = False
    extra_flags: List[str] = field(default_factory=list)

    def build_command(self) -> List[str]:
        script = (
            BASE_DIR / "mcp_host_ollama.py"
            if self.host == "ollama"
            else BASE_DIR / "mcp_host_lmstudio.py"
        )

        cmd: List[str] = [sys.executable, str(script), "--mode", self.mode, "--source", self.source]

        if self.source == "path" and self.path_contains:
            cmd += ["--path-contains", self.path_contains]
        if self.source == "tag" and self.tag:
            cmd += ["--tag", self.tag]

        cmd += ["--min-rating", str(self.min_rating), "--limit", str(self.limit)]

        if self.only_raw:
            cmd.append("--only-raw")
        if self.dry_run:
            cmd.append("--dry-run")

        if self.model:
            cmd += ["--model", self.model]
        if self.llm_url:
            flag = "--ollama-url" if self.host == "ollama" else "--lm-url"
            cmd += [flag, self.llm_url]
        if self.prompt_file:
            cmd += ["--prompt-file", str(self.prompt_file)]
        if self.mode == "export" and self.target_dir:
            cmd += ["--target-dir", self.target_dir]
        if self.text_only:
            cmd.append("--text-only")

        cmd.extend(self.extra_flags)
        return cmd


# ----------------------------- UTILIDADES DE INPUT -----------------------------
def _ask_choice(prompt: str, options: List[str], default: str) -> str:
    options_str = "/".join(options)
    while True:
        resp = input(f"{prompt} ({options_str}) [default={default}]: ").strip().lower()
        if not resp:
            return default
        if resp in options:
            return resp
        print(f"Escolha inválida. Use um dos valores: {options_str}.")


def _ask_yes_no(prompt: str, default: bool = True) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        resp = input(f"{prompt} ({suffix}): ").strip().lower()
        if not resp:
            return default
        if resp in {"y", "yes", "s", "sim"}:
            return True
        if resp in {"n", "no", "nao", "não"}:
            return False
        print("Resposta inválida. Digite 'y' ou 'n'.")


def _ask_int(prompt: str, default: int) -> int:
    while True:
        resp = input(f"{prompt} [default={default}]: ").strip()
        if not resp:
            return default
        try:
            return int(resp)
        except ValueError:
            print("Digite um número inteiro.")


def _ask_optional_str(prompt: str) -> Optional[str]:
    resp = input(f"{prompt} (Enter para pular): ").strip()
    return resp or None


# ----------------------------- MONTAGEM DA CONFIG -----------------------------
def gather_config() -> RunConfig:
    print("=== darktable-mcp interface interativa ===")
    host = _ask_choice("Escolha o host LLM", ["ollama", "lmstudio"], default="ollama")
    mode = _ask_choice("Modo", ["rating", "tagging", "export"], default="rating")
    source = _ask_choice("Fonte", ["all", "path", "tag"], default="all")

    path_contains = None
    tag = None
    if source == "path":
        path_contains = _ask_optional_str("Trecho de caminho para filtrar (--path-contains)")
        if not path_contains:
            raise SystemExit("--path-contains é obrigatório quando source=path")
    elif source == "tag":
        tag = _ask_optional_str("Tag para filtrar (--tag)")
        if not tag:
            raise SystemExit("--tag é obrigatório quando source=tag")

    min_rating = _ask_int("Rating mínimo", DEFAULT_MIN_RATING)
    limit = _ask_int("Limite de imagens enviadas ao modelo", DEFAULT_LIMIT)
    only_raw = _ask_yes_no("Enviar apenas arquivos RAW?", default=False)
    dry_run = _ask_yes_no("Executar em modo DRY-RUN?", default=True)
    text_only = not _ask_yes_no(
        "Anexar as imagens ao modelo (multimodal)?", default=True
    )

    model_default = (
        mcp_host_ollama.OLLAMA_MODEL if host == "ollama" else mcp_host_lmstudio.LMSTUDIO_MODEL
    )
    model = _ask_optional_str(f"Modelo do LLM (default={model_default})")
    llm_url_default = (
        mcp_host_ollama.OLLAMA_URL if host == "ollama" else mcp_host_lmstudio.LMSTUDIO_URL
    )
    llm_url = _ask_optional_str(f"URL do servidor (default={llm_url_default})")

    prompt_file_input = _ask_optional_str("Caminho para prompt personalizado (.md)")
    prompt_file = Path(prompt_file_input).expanduser() if prompt_file_input else None

    target_dir = None
    if mode == "export":
        target_dir = _ask_optional_str("Diretório de saída para export")
        if not target_dir:
            raise SystemExit("--target-dir é obrigatório quando mode=export")

    extra_flags: List[str] = []
    if _ask_yes_no("Rodar check de dependências antes?", default=False):
        extra_flags.append("--check-deps")

    return RunConfig(
        host=host,
        mode=mode,
        source=source,
        path_contains=path_contains,
        tag=tag,
        min_rating=min_rating,
        only_raw=only_raw,
        dry_run=dry_run,
        limit=limit,
        model=model,
        llm_url=llm_url,
        target_dir=target_dir,
        prompt_file=prompt_file,
        text_only=text_only,
        extra_flags=extra_flags,
    )


# ----------------------------- MAIN -----------------------------
def main() -> None:
    config = gather_config()
    cmd = config.build_command()

    default_url = mcp_host_ollama.OLLAMA_URL if config.host == "ollama" else mcp_host_lmstudio.LMSTUDIO_URL
    default_model = (
        mcp_host_ollama.OLLAMA_MODEL if config.host == "ollama" else mcp_host_lmstudio.LMSTUDIO_MODEL
    )

    print("\n--- Resumo da execução ---")
    print(f"Host: {config.host}")
    print(f"Modo: {config.mode}")
    print(f"Fonte: {config.source}")
    if config.path_contains:
        print(f"  path-contains: {config.path_contains}")
    if config.tag:
        print(f"  tag: {config.tag}")
    print(f"Rating mínimo: {config.min_rating}")
    print(f"Limit: {config.limit}")
    print(f"Apenas RAW: {'sim' if config.only_raw else 'não'}")
    print(f"Dry-run: {'sim' if config.dry_run else 'não'}")
    print(f"Modelo: {config.model or default_model}")
    print(f"URL do servidor: {config.llm_url or default_url}")
    if config.prompt_file:
        print(f"Prompt personalizado: {config.prompt_file}")
    print(f"Enviar imagens ao modelo: {'não (texto/metadados)' if config.text_only else 'sim (multimodal)'}")
    if config.target_dir:
        print(f"Diretório de export: {config.target_dir}")
    if config.extra_flags:
        print(f"Flags extras: {' '.join(config.extra_flags)}")

    print("\nComando final:")
    print(" ".join(cmd))

    if not _ask_yes_no("Confirmar e executar?", default=False):
        print("Execução cancelada.")
        return

    env = os.environ.copy()
    try:
        subprocess.run(cmd, check=True, env=env)
    except subprocess.CalledProcessError as exc:
        print(f"[ERRO] Execução retornou código {exc.returncode}")


if __name__ == "__main__":
    main()
