#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

import requests

from common import (
    BASE_DIR,
    DT_SERVER_CMD,
    LOG_DIR,
    McpClient,
    append_export_result_to_log,
    check_dependencies,
    extract_export_errors,
    fallback_user_prompt,
    fetch_images,
    load_prompt,
    prepare_vision_payloads,
    probe_darktable_state,
    save_log,
)

# Config padrão do Ollama
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = ""

PROTOCOL_VERSION = "2024-11-05"
APP_VERSION = "0.2.0"
CLIENT_INFO = {"name": "darktable-mcp-ollama", "version": APP_VERSION}
DEPENDENCY_BINARIES = ["lua", "darktable-cli"]


# --------- UTIL: chamada ao Ollama / downloads ---------
def _normalize_base_url(url: str | None) -> str:
    base = url or OLLAMA_URL
    return base.rstrip("/")


def call_ollama(system_prompt, user_prompt, model=None, url=None):
    base = _normalize_base_url(url)
    model = model or OLLAMA_MODEL

    chat_url = f"{base}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
    }
    resp = requests.post(chat_url, json=payload)
    resp.raise_for_status()
    data = resp.json()
    return data["message"]["content"]


def call_ollama_messages(messages, model=None, url=None):
    base = _normalize_base_url(url)
    model = model or OLLAMA_MODEL

    chat_url = f"{base}/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    resp = requests.post(chat_url, json=payload)
    resp.raise_for_status()
    data = resp.json()
    return data["message"]["content"]


def pull_ollama_model(model: str, url: str | None = None):
    base = _normalize_base_url(url)
    pull_url = f"{base}/api/pull"
    resp = requests.post(pull_url, json={"model": model}, stream=True, timeout=5)
    resp.raise_for_status()

    statuses = []
    for line in resp.iter_lines():
        if not line:
            continue
        try:
            data = json.loads(line.decode("utf-8"))
        except Exception:
            continue
        status = data.get("status") or data.get("message")
        if status:
            statuses.append(status)

    if not statuses:
        statuses.append("Download iniciado; acompanhe logs do Ollama para progresso.")
    return statuses
# --------- CLI ---------
def parse_args():
    p = argparse.ArgumentParser(
        description="Host MCP para darktable + Ollama (rating/tagging/export)."
    )
    p.add_argument("--version", action="version", version=f"darktable-mcp-host {APP_VERSION}")
    p.add_argument("--mode", choices=["rating", "tagging", "export", "tratamento"], default="rating")
    p.add_argument("--source", choices=["all", "path", "tag", "collection"], default="all")
    p.add_argument("--path-contains", help="Filtro por trecho de path (source=path).")
    p.add_argument("--tag", help="Filtro por tag (source=tag).")
    p.add_argument(
        "--collection",
        help=(
            "Nome ou caminho da coleção (source=collection). Combine com --list-collections "
            "para descobrir opções."
        ),
    )
    p.add_argument("--min-rating", type=int, default=-2, help="Rating mínimo.")
    p.add_argument("--only-raw", action="store_true", help="Apenas arquivos RAW.")
    p.add_argument("--dry-run", action="store_true", help="Não aplica, só mostra plano.")
    p.add_argument("--limit", type=int, default=200, help="Limite de imagens enviadas ao modelo.")
    p.add_argument("--model", help="Nome do modelo no Ollama.")
    p.add_argument("--ollama-url", help="URL do servidor Ollama.")
    p.add_argument(
        "--target-dir",
        help="Diretório de saída para export (obrigatório em --mode export).",
    )
    p.add_argument(
        "--prompt-file",
        help="Override do prompt (caminho para .md)."
    )
    p.add_argument(
        "--check-deps",
        action="store_true",
        help="Valida a presença de 'lua' e 'darktable-cli' antes de executar.",
    )
    p.add_argument(
        "--check-darktable",
        action="store_true",
        help=(
            "Valida a conectividade com o darktable, lista coleções e retorna uma amostra "
            "das fotos disponíveis."
        ),
    )
    p.add_argument(
        "--text-only",
        action="store_true",
        help="Não envia a imagem ao modelo (modo texto/metadados).",
    )
    p.add_argument(
        "--list-collections",
        action="store_true",
        help="Lista coleções conhecidas no darktable e sai.",
    )
    p.add_argument(
        "--download-model",
        help="Baixa um modelo específico do Ollama e sai.",
    )
    return p.parse_args()

def build_ollama_messages_for_images(
    system_prompt: str, sample: list[dict], vision_images
):
    if not vision_images:
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": fallback_user_prompt(sample)},
        ]

    messages = [{"role": "system", "content": system_prompt}]
    for item in vision_images:
        meta = item.meta
        colorlabels = ",".join(meta.get("colorlabels", []))
        description = (
            "Avalie a imagem a seguir e proponha ajustes para pós-processo. "
            f"id={meta.get('id')} path={item.path} rating_atual={meta.get('rating')} "
            f"raw={meta.get('is_raw')} colorlabels=[{colorlabels}]"
        )
        messages.append({"role": "user", "content": description, "images": [item.b64]})

    messages.append(
        {
            "role": "user",
            "content": "Retorne um único JSON cobrindo todas as imagens acima, seguindo o formato solicitado.",
        }
    )
    return messages


def list_available_collections(client):
    res = client.call_tool("list_available_collections", {})
    return res["content"][0]["json"]


# --------- MODOS ---------

def run_mode_rating(client, args):
    images = fetch_images(client, args)
    print(f"[rating] Imagens filtradas: {len(images)}")

    if not images:
        print("Nada para processar.")
        return

    sample = images[: args.limit]
    system_prompt = load_prompt("rating", args.prompt_file)
    vision_images, vision_errors = prepare_vision_payloads(sample, attach_images=not args.text_only)
    if vision_errors:
        print("[rating] Avisos ao carregar imagens:")
        for warn in vision_errors:
            print("  -", warn)

    messages = build_ollama_messages_for_images(system_prompt, sample, vision_images)

    answer = call_ollama_messages(
        messages,
        model=args.model or OLLAMA_MODEL,
        url=args.ollama_url or OLLAMA_URL,
    )
    print("[rating] Resposta bruta do modelo:")
    print(answer)

    log_file = save_log(
        "rating",
        args.source,
        sample,
        answer,
        extra={
            "vision": {
                "attached": len(vision_images),
                "errors": vision_errors,
                "mode": "text-only" if args.text_only else "multimodal",
            }
        },
    )
    print(f"[rating] Log salvo em: {log_file}")

    try:
        parsed = json.loads(answer)
        edits = parsed.get("edits", [])
    except Exception as e:
        print("[rating] Erro ao parsear JSON:", e)
        return

    if not edits:
        print("[rating] Nenhuma edição retornada.")
        return

    print(f"[rating] {len(edits)} imagens com rating sugerido.")
    if args.dry_run:
        print("[rating] DRY-RUN: não aplicando mudanças.")
        return

    res = client.call_tool("apply_batch_edits", {"edits": edits})
    print("[rating] Resultado apply_batch_edits:", res["content"][0]["text"])


def run_mode_tagging(client, args):
    images = fetch_images(client, args)
    print(f"[tagging] Imagens filtradas: {len(images)}")

    if not images:
        print("Nada para processar.")
        return

    sample = images[: args.limit]
    system_prompt = load_prompt("tagging", args.prompt_file)
    vision_images, vision_errors = prepare_vision_payloads(sample, attach_images=not args.text_only)
    if vision_errors:
        print("[tagging] Avisos ao carregar imagens:")
        for warn in vision_errors:
            print("  -", warn)

    messages = build_ollama_messages_for_images(system_prompt, sample, vision_images)

    answer = call_ollama_messages(
        messages,
        model=args.model or OLLAMA_MODEL,
        url=args.ollama_url or OLLAMA_URL,
    )
    print("[tagging] Resposta bruta do modelo:")
    print(answer)

    log_file = save_log(
        "tagging",
        args.source,
        sample,
        answer,
        extra={
            "vision": {
                "attached": len(vision_images),
                "errors": vision_errors,
                "mode": "text-only" if args.text_only else "multimodal",
            }
        },
    )
    print(f"[tagging] Log salvo em: {log_file}")

    try:
        parsed = json.loads(answer)
        tags_entries = parsed.get("tags", [])
    except Exception as e:
        print("[tagging] Erro ao parsear JSON:", e)
        return

    if not tags_entries:
        print("[tagging] Nenhuma tag retornada.")
        return

    if args.dry_run:
        print("[tagging] DRY-RUN: plano de tags:")
        for entry in tags_entries:
            print(f"  tag={entry.get('tag')} -> {len(entry.get('ids', []))} imagens")
        return

    total_ops = 0
    for entry in tags_entries:
        tag = entry.get("tag")
        ids = entry.get("ids", [])
        if not tag or not ids:
            continue
        res = client.call_tool("tag_batch", {"tag": tag, "ids": ids})
        print(f"[tagging] tag_batch '{tag}':", res["content"][0]["text"])
        total_ops += 1

    print(f"[tagging] tag_batch executado {total_ops} vez(es).")


def run_mode_tratamento(client, args):
    images = fetch_images(client, args)
    print(f"[tratamento] Imagens filtradas: {len(images)}")

    if not images:
        print("Nada para processar.")
        return

    sample = images[: args.limit]
    system_prompt = load_prompt("tratamento", args.prompt_file)
    vision_images, vision_errors = prepare_vision_payloads(sample, attach_images=not args.text_only)

    if vision_errors:
        print("[tratamento] Avisos ao carregar imagens:")
        for warn in vision_errors:
            print("  -", warn)

    messages = build_ollama_messages_for_images(system_prompt, sample, vision_images)
    answer = call_ollama_messages(
        messages,
        model=args.model or OLLAMA_MODEL,
        url=args.ollama_url or OLLAMA_URL,
    )

    print("[tratamento] Resposta bruta do modelo:")
    print(answer)

    log_file = save_log(
        "tratamento",
        args.source,
        sample,
        answer,
        extra={
            "vision": {
                "attached": len(vision_images),
                "errors": vision_errors,
                "mode": "text-only" if args.text_only else "multimodal",
            }
        },
    )
    print(f"[tratamento] Log salvo em: {log_file}")

    if args.dry_run:
        print("[tratamento] DRY-RUN: mantendo somente a sugestão do modelo.")


def run_mode_export(client, args):
    if not args.target_dir:
        raise ValueError("--target-dir é obrigatório em --mode export")

    images = fetch_images(client, args)
    print(f"[export] Imagens filtradas: {len(images)}")

    if not images:
        print("Nada para processar.")
        return

    sample = images[: args.limit]
    system_prompt = load_prompt("export", args.prompt_file)
    vision_images, vision_errors = prepare_vision_payloads(sample, attach_images=not args.text_only)
    if vision_errors:
        print("[export] Avisos ao carregar imagens:")
        for warn in vision_errors:
            print("  -", warn)

    messages = build_ollama_messages_for_images(system_prompt, sample, vision_images)

    answer = call_ollama_messages(
        messages,
        model=args.model or OLLAMA_MODEL,
        url=args.ollama_url or OLLAMA_URL,
    )
    print("[export] Resposta bruta do modelo:")
    print(answer)

    log_file = save_log(
        "export",
        args.source,
        sample,
        answer,
        extra={
            "target_dir": args.target_dir,
            "vision": {
                "attached": len(vision_images),
                "errors": vision_errors,
                "mode": "text-only" if args.text_only else "multimodal",
            },
        },
    )
    print(f"[export] Log salvo em: {log_file}")

    try:
        parsed = json.loads(answer)
        ids = parsed.get("ids_para_exportar") or parsed.get("ids") or []
    except Exception as e:
        print("[export] Erro ao parsear JSON:", e)
        return

    if not ids:
        print("[export] Nenhum id retornado para export.")
        return

    print(f"[export] {len(ids)} imagens selecionadas para export.")
    if args.dry_run:
        print("[export] DRY-RUN: NÃO exportando. Dir alvo:", args.target_dir)
        print("IDs:", ids[:20], "..." if len(ids) > 20 else "")
        return

    params = {
        "target_dir": args.target_dir,
        "ids": ids,
        "format": "jpg",
        "overwrite": False,
    }
    res = client.call_tool("export_collection", params)
    summary = res["content"][0]["text"]
    print("[export] Resultado export_collection:", summary)

    errors = extract_export_errors(res)
    if errors:
        print("[export] Falhas detalhadas:")
        for err in errors:
            print(
                f"  id={err.get('id')} exit={err.get('exit')} reason={err.get('exit_reason')} "
                f"cmd={err.get('command')}"
            )
            stderr_msg = (err.get("stderr") or "").strip()
            if stderr_msg:
                print("    stderr:", stderr_msg)

    stored_log = append_export_result_to_log(log_file, res)
    if stored_log != log_file:
        print(f"[export] Resultado de export salvo em log adicional: {stored_log}")


# --------- DEPENDÊNCIAS ---------
def run_dependency_check():
    check_dependencies([*DEPENDENCY_BINARIES])


def run_darktable_probe(args) -> bool:
    print("[probe] Verificando darktable + dependências...")
    probe = probe_darktable_state(
        PROTOCOL_VERSION,
        CLIENT_INFO,
        min_rating=args.min_rating,
        only_raw=bool(args.only_raw),
        sample_limit=max(1, min(args.limit, 50)),
    )

    deps = probe.get("dependencies", {})
    missing = probe.get("missing_dependencies", [])
    for name, location in deps.items():
        status = f"OK ({location})" if location else "NÃO encontrado"
        print(f"  - {name}: {status}")

    cli_cmd = deps.get("darktable-cli") or ""
    if cli_cmd.startswith("flatpak run"):
        print(
            "  > darktable-cli disponível via Flatpak. Ajuste DARKTABLE_FLATPAK_PREFIX "
            "caso use um prefixo alternativo."
        )

    if missing:
        print("[probe] Dependências ausentes; instale-as e tente novamente.")
        return False

    if probe.get("error"):
        print(f"[probe] Erro ao consultar darktable: {probe['error']}")
        return False

    server_info = probe.get("server_info") or {}
    tools = probe.get("tools") or []
    print(f"[probe] Servidor MCP inicializado: {server_info}")
    print(f"[probe] Ferramentas disponíveis: {', '.join(tools) or 'nenhuma'}")

    collections = probe.get("collections") or []
    print(f"[probe] Coleções detectadas ({len(collections)}):")
    for entry in collections[:10]:
        path = entry.get("path")
        count = entry.get("image_count", 0)
        film = entry.get("film_roll")
        film_suffix = f" [filme: {film}]" if film else ""
        print(f"  - {path} ({count} imagens){film_suffix}")
    if len(collections) > 10:
        print(f"  ... +{len(collections) - 10} coleções")

    total_images = probe.get("image_total", 0)
    sample = probe.get("sample_images") or []
    print(f"[probe] Imagens disponíveis: {total_images} (amostra de {len(sample)})")
    for item in sample:
        image_path = f"{item.get('path', '')}/{item.get('filename', '')}"
        print(
            f"  - id={item.get('id')} rating={item.get('rating')} raw={item.get('is_raw')} "
            f"labels={','.join(item.get('colorlabels', []))} {image_path}"
        )

    return True


# --------- MAIN ---------
def main():
    args = parse_args()

    if args.check_deps:
        run_dependency_check()

    if args.check_darktable:
        ok = run_darktable_probe(args)
        raise SystemExit(0 if ok else 1)

    if not args.download_model:
        missing = check_dependencies([*DEPENDENCY_BINARIES], exit_on_success=False)
        if missing:
            print(
                "[deps] Dependências ausentes; instale-as e execute novamente ou use "
                "--check-deps para revalidar."
            )
            raise SystemExit(1)

    # Apenas garante que diretórios existem
    LOG_DIR.mkdir(exist_ok=True)

    target_model = args.download_model
    if target_model:
        try:
            statuses = pull_ollama_model(target_model, args.ollama_url)
            print(f"[download] Progresso do download de '{target_model}':")
            for status in statuses:
                print("  -", status)
        except Exception as exc:
            print(f"[download] Falha ao iniciar download de '{target_model}': {exc}")
            raise SystemExit(1)
        else:
            return

    try:
        client = McpClient(DT_SERVER_CMD, PROTOCOL_VERSION, CLIENT_INFO)
    except FileNotFoundError as exc:
        friendly = (
            "Falha ao iniciar o servidor MCP. Certifique-se de que 'lua' e 'darktable-cli' "
            "estão instalados e no PATH, ou use --check-deps para validar antes de rodar."
        )
        print(friendly)
        check_dependencies([*DEPENDENCY_BINARIES], exit_on_success=False)
        raise SystemExit(1) from exc
    try:
        init = client.initialize()
        print("Inicializado:", init["serverInfo"])

        tools = client.list_tools()
        names = [t["name"] for t in tools["tools"]]
        print("Ferramentas MCP disponíveis:", ", ".join(names))

        if args.list_collections:
            available = list_available_collections(client)
            print("Coleções conhecidas (path -> imagens):")
            for entry in available:
                print(
                    f"  - {entry.get('path')}"
                    f" ({entry.get('image_count', 0)} imagens)"
                    + (f" [filme: {entry.get('film_roll')}]" if entry.get("film_roll") else "")
                )
            return

        if args.mode == "rating":
            run_mode_rating(client, args)
        elif args.mode == "tagging":
            run_mode_tagging(client, args)
        elif args.mode == "export":
            run_mode_export(client, args)
        elif args.mode == "tratamento":
            run_mode_tratamento(client, args)
        else:
            print("Modo desconhecido:", args.mode)

    finally:
        client.close()


if __name__ == "__main__":
    main()
