from __future__ import annotations

import argparse
import json
import time

import requests

from common import (
    BASE_DIR,
    LOG_DIR,
    McpClient,
    VisionImage,
    append_export_result_to_log,
    check_dependencies,
    extract_export_errors,
    fallback_user_prompt,
    fetch_images,
    load_prompt,
    prepare_vision_payloads,
    save_log,
)

PROTOCOL_VERSION = "2024-11-05"
APP_VERSION = "0.2.0"
CLIENT_INFO = {"name": "darktable-mcp-lmstudio", "version": APP_VERSION}

DT_SERVER_CMD = ["lua", str(BASE_DIR / "server" / "dt_mcp_server.lua")]

# Config padrão do LM Studio (API OpenAI-like)
LMSTUDIO_URL = "http://localhost:1234/v1/chat/completions"  # ajuste a porta se for diferente
LMSTUDIO_MODEL = ""
DEPENDENCY_BINARIES = ["lua", "darktable-cli"]


# --------- UTIL: chamada ao LM Studio ---------
def call_lmstudio(system_prompt, user_prompt, model=None, url=None):
    url = url or LMSTUDIO_URL
    model = model or LMSTUDIO_MODEL

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
    }
    started = time.time()
    resp = requests.post(url, json=payload)
    elapsed_ms = int((time.time() - started) * 1000)
    resp.raise_for_status()
    data = resp.json()
    # API OpenAI-like
    content = data["choices"][0]["message"]["content"]
    meta = {
        "model": model,
        "url": url,
        "status_code": resp.status_code,
        "latency_ms": elapsed_ms,
    }
    return content, meta


def call_lmstudio_messages(messages, model=None, url=None):
    url = url or LMSTUDIO_URL
    model = model or LMSTUDIO_MODEL

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    started = time.time()
    resp = requests.post(url, json=payload)
    elapsed_ms = int((time.time() - started) * 1000)
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    meta = {
        "model": model,
        "url": url,
        "status_code": resp.status_code,
        "latency_ms": elapsed_ms,
    }
    return content, meta


# --------- CLI ---------
def parse_args():
    p = argparse.ArgumentParser(
        description="Host MCP para darktable + LM Studio (rating/tagging/export).",
    )
    p.add_argument("--version", action="version", version=f"darktable-mcp-host {APP_VERSION}")
    p.add_argument(
        "--check-deps",
        action="store_true",
        help="Só verifica dependências e sai (lua, darktable-cli, requests).",
    )
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
    p.add_argument("--model", help="Nome do modelo no LM Studio.")
    p.add_argument("--lm-url", help="URL do servidor LM Studio (OpenAI API).")
    p.add_argument(
        "--target-dir",
        help="Diretório de saída para export (obrigatório em --mode export).",
    )
    p.add_argument(
        "--prompt-file",
        help="Override do prompt (caminho para .md).",
    )
    p.add_argument(
        "--text-only",
        action="store_true",
        help="Não envia a imagem ao modelo (usa só metadados).",
    )
    p.add_argument(
        "--list-collections",
        action="store_true",
        help="Lista coleções conhecidas no darktable e sai.",
    )
    return p.parse_args()


# --------- UTIL: multimodal / imagens ----------
def build_lmstudio_messages_for_images(
    system_prompt: str, sample: list[dict], vision_images: list[VisionImage]
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
            "Analise a imagem e sugira correções e tags coerentes. "
            f"id={meta.get('id')} path={item.path} rating_atual={meta.get('rating')} "
            f"raw={meta.get('is_raw')} colorlabels=[{colorlabels}]"
        )
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": description},
                    {"type": "image_url", "image_url": {"url": item.data_url}},
                ],
            }
        )

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


# --------- DEPENDÊNCIAS ---------
def run_dependency_check():
    check_dependencies([*DEPENDENCY_BINARIES])


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

    messages = build_lmstudio_messages_for_images(system_prompt, sample, vision_images)

    answer, meta = call_lmstudio_messages(
        messages,
        model=args.model or LMSTUDIO_MODEL,
        url=args.lm_url or LMSTUDIO_URL,
    )
    print(
        f"[rating] Modelo={meta['model']} status={meta['status_code']} "
        f"latência={meta['latency_ms']}ms @ {meta['url']}"
    )
    print("[rating] Resposta bruta do modelo:")
    print(answer)

    log_file = save_log(
        "rating",
        args.source,
        sample,
        answer,
        extra={
            "llm": meta,
            "vision": {
                "attached": len(vision_images),
                "errors": vision_errors,
                "mode": "text-only" if args.text_only else "multimodal",
            },
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

    messages = build_lmstudio_messages_for_images(system_prompt, sample, vision_images)

    answer, meta = call_lmstudio_messages(
        messages,
        model=args.model or LMSTUDIO_MODEL,
        url=args.lm_url or LMSTUDIO_URL,
    )
    print(
        f"[tagging] Modelo={meta['model']} status={meta['status_code']} "
        f"latência={meta['latency_ms']}ms @ {meta['url']}"
    )
    print("[tagging] Resposta bruta do modelo:")
    print(answer)

    log_file = save_log(
        "tagging",
        args.source,
        sample,
        answer,
        extra={
            "llm": meta,
            "vision": {
                "attached": len(vision_images),
                "errors": vision_errors,
                "mode": "text-only" if args.text_only else "multimodal",
            },
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


def run_mode_export(client, args):
    images = fetch_images(client, args)
    print(f"[export] Imagens filtradas: {len(images)}")

    if not images:
        print("Nada para processar.")
        return

    if not args.target_dir:
        print("[export] --target-dir é obrigatório em modo export.")
        return

    sample = images[: args.limit]
    system_prompt = load_prompt("export", args.prompt_file)
    vision_images, vision_errors = prepare_vision_payloads(sample, attach_images=not args.text_only)
    if vision_errors:
        print("[export] Avisos ao carregar imagens:")
        for warn in vision_errors:
            print("  -", warn)

    messages = build_lmstudio_messages_for_images(system_prompt, sample, vision_images)

    answer, meta = call_lmstudio_messages(
        messages,
        model=args.model or LMSTUDIO_MODEL,
        url=args.lm_url or LMSTUDIO_URL,
    )
    print(
        f"[export] Modelo={meta['model']} status={meta['status_code']} "
        f"latência={meta['latency_ms']}ms @ {meta['url']}"
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
            "llm": meta,
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

    messages = build_lmstudio_messages_for_images(system_prompt, sample, vision_images)

    answer, meta = call_lmstudio_messages(
        messages,
        model=args.model or LMSTUDIO_MODEL,
        url=args.lm_url or LMSTUDIO_URL,
    )
    print(
        f"[tratamento] Modelo={meta['model']} status={meta['status_code']} "
        f"latência={meta['latency_ms']}ms @ {meta['url']}"
    )
    print("[tratamento] Resposta bruta do modelo:")
    print(answer)

    log_file = save_log(
        "tratamento",
        args.source,
        sample,
        answer,
        extra={
            "llm": meta,
            "vision": {
                "attached": len(vision_images),
                "errors": vision_errors,
                "mode": "text-only" if args.text_only else "multimodal",
            },
        },
    )
    print(f"[tratamento] Log salvo em: {log_file}")

    try:
        parsed = json.loads(answer)
    except Exception as exc:
        print("[tratamento] Erro ao parsear JSON:", exc)
        return

    plano = parsed.get("plano") or parsed.get("plan")
    if not plano:
        print("[tratamento] Nenhum plano retornado pelo modelo.")
        return

    print("[tratamento] Plano sugerido:")
    print(plano)


# --------- MAIN ---------
def main():
    args = parse_args()

    if args.check_deps:
        run_dependency_check()

    LOG_DIR.mkdir(exist_ok=True)

    try:
        client = McpClient(DT_SERVER_CMD, PROTOCOL_VERSION, CLIENT_INFO)
    except FileNotFoundError as exc:
        friendly = (
            "Falha ao iniciar o servidor MCP. Certifique-se de que 'lua' e 'darktable-cli' "
            "estão instalados e no PATH, ou use --check-deps para validar antes de rodar."
        )
        raise SystemExit(friendly) from exc
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
