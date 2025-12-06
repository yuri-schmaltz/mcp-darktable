#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Adiciona o diretório atual ao path para garantir imports
sys.path.append(str(Path(__file__).parent))

from common import (
    DT_SERVER_CMD,
    McpClient,
    check_dependencies,
    probe_darktable_state,
    list_available_collections,
    load_prompt,
    setup_logging
)
from llm_api import OllamaProvider
from batch_processor import BatchProcessor

PROTOCOL_VERSION = "2024-11-05"
APP_VERSION = "0.3.0"
CLIENT_INFO = {"name": "darktable-mcp-ollama", "version": APP_VERSION}
DEPENDENCY_BINARIES = ["lua", "darktable-cli"]

DEFAULT_OLLAMA_URL = "http://localhost:11434"
OLLAMA_URL = DEFAULT_OLLAMA_URL
OLLAMA_MODEL = "llama3.2"

def parse_args():
    p = argparse.ArgumentParser(description="Host MCP darktable + Ollama (Refactored)")
    p.add_argument("--version", action="version", version=f"v{APP_VERSION}")
    p.add_argument("--mode", choices=["rating", "tagging", "export", "tratamento", "completo"], default="rating")
    
    # Filtros
    p.add_argument("--source", choices=["all", "path", "tag", "collection"], default="all")
    p.add_argument("--path-contains", help="Filtro path")
    p.add_argument("--tag", help="Filtro tag")
    p.add_argument("--collection", help="Filtro collection")
    p.add_argument("--min-rating", type=int, default=-2)
    p.add_argument("--only-raw", action="store_true")
    
    # Controle
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=200)
    p.add_argument("--target-dir", help="Para export")
    
    # LLM
    p.add_argument("--model", help="Modelo Ollama")
    p.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL)
    p.add_argument("--timeout", type=float, default=60.0)
    p.add_argument("--text-only", action="store_true")
    p.add_argument("--prompt-file")
    p.add_argument("--prompt-variant", default="basico")
    
    # Utils
    p.add_argument("--check-deps", action="store_true")
    p.add_argument("--check-darktable", action="store_true")
    p.add_argument("--list-collections", action="store_true")
    p.add_argument("--download-model")
    
    # Logging
    p.add_argument("--verbose", action="store_true", help="Ativa logs detalhados no console")
    
    return p.parse_args()

def main():
    args = parse_args()
    setup_logging(verbose=args.verbose)
    
    # 1. Dependencias
    if args.check_deps:
        check_dependencies(DEPENDENCY_BINARIES)
        return

    if args.check_darktable:
        # Reusa lógica de probe do common
        # Para simplificar, instanciamos o probe direto aqui se fosse necessario,
        # mas probe_darktable_state é uma função pura.
        probe = probe_darktable_state(
            PROTOCOL_VERSION, CLIENT_INFO,
            min_rating=args.min_rating,
            only_raw=args.only_raw,
            sample_limit=args.limit
        )
        # Exibe resultado (simplificado)
        print(probe) 
        return

    # 2. Setup Provider
    provider = OllamaProvider(args.ollama_url, args.model or "llama3.2", args.timeout)
    
    if args.download_model:
        print(f"Baixando {args.download_model}...")
        for status in provider.download_model(args.download_model):
            print(status)
        return

    # 3. Execução Principal
    try:
        from common import _find_appimage
        appimage = _find_appimage()
        if appimage:
            print(f"[ollama-host] Usando AppImage: {appimage}")

        with McpClient(DT_SERVER_CMD, PROTOCOL_VERSION, CLIENT_INFO, appimage_path=appimage) as client:
            client.initialize()
            
            if args.list_collections:
                available = list_available_collections(client)
                for entry in available:
                    print(f"- {entry.get('path')} ({entry.get('image_count')})")
                return

            processor = BatchProcessor(client, provider, dry_run=args.dry_run)
            processor.run(args.mode, args)
            
    except Exception as e:
        print(f"Erro fatal: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
