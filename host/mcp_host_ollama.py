#!/usr/bin/env python3
import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path

import requests

# Caminho do servidor Lua (ajuste se necessário)
BASE_DIR = Path(__file__).resolve().parent.parent
DT_SERVER_CMD = ["lua", str(BASE_DIR / "server" / "dt_mcp_server.lua")]

# Config padrão do Ollama
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "llama3.1"  # ajuste pro modelo que você tiver
POPULAR_MODELS = [
    "llama3.2",
    "llama3.1",
    "phi3",
    "mistral",
    "gemma2",
]
PROTOCOL_VERSION = "2024-11-05"
APP_VERSION = "0.2.0"
CLIENT_INFO = {"name": "darktable-mcp-ollama", "version": APP_VERSION}

LOG_DIR = BASE_DIR / "logs"
PROMPT_DIR = BASE_DIR / "config" / "prompts"


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


# --------- UTIL: cliente MCP (stdio) ---------
class McpClient:
    def __init__(self, cmd):
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.msg_id = 0

    def _next_id(self):
        self.msg_id += 1
        return str(self.msg_id)

    def request(self, method, params=None):
        req_id = self._next_id()
        req = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {},
        }
        line = json.dumps(req)
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()

        resp_line = self.proc.stdout.readline()
        if not resp_line:
            raise RuntimeError("Servidor MCP não respondeu (stdout vazio)")
        resp = json.loads(resp_line)
        if "error" in resp:
            raise RuntimeError(resp["error"])
        return resp["result"]

    def initialize(self):
        params = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
        }
        return self.request("initialize", params)

    def list_tools(self):
        return self.request("tools/list", {})

    def call_tool(self, name, arguments=None):
        params = {"name": name, "arguments": arguments or {}}
        return self.request("tools/call", params)

    def close(self):
        try:
            self.proc.terminate()
        except Exception:
            pass


# --------- CLI ---------
def parse_args():
    p = argparse.ArgumentParser(
        description="Host MCP para darktable + Ollama (rating/tagging/export)."
    )
    p.add_argument("--version", action="version", version=f"darktable-mcp-host {APP_VERSION}")
    p.add_argument("--mode", choices=["rating", "tagging", "export"], default="rating")
    p.add_argument("--source", choices=["all", "path", "tag"], default="all")
    p.add_argument("--path-contains", help="Filtro por trecho de path (source=path).")
    p.add_argument("--tag", help="Filtro por tag (source=tag).")
    p.add_argument("--min-rating", type=int, default=-2, help="Rating mínimo.")
    p.add_argument("--only-raw", action="store_true", help="Apenas arquivos RAW.")
    p.add_argument("--dry-run", action="store_true", help="Não aplica, só mostra plano.")
    p.add_argument("--limit", type=int, default=200, help="Limite de imagens enviadas ao modelo.")
    p.add_argument("--model", help="Nome do modelo no Ollama.")
    p.add_argument("--ollama-url", help="URL do servidor Ollama.")
    p.add_argument(
        "--download-model",
        help=(
            "Baixa um modelo no Ollama antes de executar. Exemplos populares: "
            + ", ".join(POPULAR_MODELS)
        ),
    )
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
    return p.parse_args()


# --------- UTIL: carregar prompt ---------
def load_prompt(mode, prompt_file=None):
    if prompt_file:
        path = Path(prompt_file)
    else:
        default_map = {
            "rating": "rating_basico.md",
            "tagging": "tagging_cliente.md",
            "export": "export_job.md",
        }
        fname = default_map.get(mode)
        if not fname:
            raise ValueError(f"Modo desconhecido para prompt: {mode}")
        path = PROMPT_DIR / fname

    if not path.exists():
        raise FileNotFoundError(f"Prompt não encontrado: {path}")
    return path.read_text(encoding="utf-8")


# --------- UTIL: buscar imagens ----------

def fetch_images(client, args):
    params = {
        "min_rating": args.min_rating,
        "only_raw": bool(args.only_raw),
    }

    if args.source == "all":
        tool_name = "list_collection"
    elif args.source == "path":
        tool_name = "list_by_path"
        if not args.path_contains:
            raise ValueError("--path-contains é obrigatório com --source path")
        params["path_contains"] = args.path_contains
    elif args.source == "tag":
        tool_name = "list_by_tag"
        if not args.tag:
            raise ValueError("--tag é obrigatório com --source tag")
        params["tag"] = args.tag
    else:
        raise ValueError(f"source inválido: {args.source}")

    result = client.call_tool(tool_name, params)
    images = result["content"][0]["json"]
    return images


# --------- LOG ---------
def save_log(mode, source, images, model_answer, extra=None):
    LOG_DIR.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    log_file = LOG_DIR / f"batch-{mode}-{ts}.json"

    data = {
        "timestamp": ts,
        "mode": mode,
        "source": source,
        "images_sample": images,
        "model_answer": model_answer,
    }
    if extra:
        data["extra"] = extra

    with log_file.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return log_file


# --------- MODOS ---------

def run_mode_rating(client, args):
    images = fetch_images(client, args)
    print(f"[rating] Imagens filtradas: {len(images)}")

    if not images:
        print("Nada para processar.")
        return

    sample = images[: args.limit]
    system_prompt = load_prompt("rating", args.prompt_file)
    user_prompt = "Lista (amostra) de imagens do darktable:\n" + json.dumps(
        sample, ensure_ascii=False
    )

    answer = call_ollama(
        system_prompt,
        user_prompt,
        model=args.model or OLLAMA_MODEL,
        url=args.ollama_url or OLLAMA_URL,
    )
    print("[rating] Resposta bruta do modelo:")
    print(answer)

    log_file = save_log("rating", args.source, sample, answer)
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
    user_prompt = "Lista (amostra) de imagens do darktable:\n" + json.dumps(
        sample, ensure_ascii=False
    )

    answer = call_ollama(
        system_prompt,
        user_prompt,
        model=args.model or OLLAMA_MODEL,
        url=args.ollama_url or OLLAMA_URL,
    )
    print("[tagging] Resposta bruta do modelo:")
    print(answer)

    log_file = save_log("tagging", args.source, sample, answer)
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
    if not args.target_dir:
        raise ValueError("--target-dir é obrigatório em --mode export")

    images = fetch_images(client, args)
    print(f"[export] Imagens filtradas: {len(images)}")

    if not images:
        print("Nada para processar.")
        return

    sample = images[: args.limit]
    system_prompt = load_prompt("export", args.prompt_file)
    user_prompt = "Lista (amostra) de imagens do darktable:\n" + json.dumps(
        sample, ensure_ascii=False
    )

    answer = call_ollama(
        system_prompt,
        user_prompt,
        model=args.model or OLLAMA_MODEL,
        url=args.ollama_url or OLLAMA_URL,
    )
    print("[export] Resposta bruta do modelo:")
    print(answer)

    log_file = save_log("export", args.source, sample, answer, extra={"target_dir": args.target_dir})
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
    print("[export] Resultado export_collection:", res["content"][0]["text"])


# --------- DEPENDÊNCIAS ---------
def check_dependencies():
    checks = {
        "lua": shutil.which("lua") is not None,
        "darktable-cli": shutil.which("darktable-cli") is not None,
        "requests": True,
    }

    print("[check-deps] Resultado:")
    for name, ok in checks.items():
        print(f"  - {name}: {'OK' if ok else 'NÃO ENCONTRADO'}")

    missing = [name for name, ok in checks.items() if not ok]
    if missing:
        raise SystemExit(1)
    raise SystemExit(0)


# --------- MAIN ---------
def main():
    args = parse_args()

    if args.check_deps:
        check_dependencies()

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

    try:
        client = McpClient(DT_SERVER_CMD)
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

        if args.mode == "rating":
            run_mode_rating(client, args)
        elif args.mode == "tagging":
            run_mode_tagging(client, args)
        elif args.mode == "export":
            run_mode_export(client, args)
        else:
            print("Modo desconhecido:", args.mode)

    finally:
        client.close()


if __name__ == "__main__":
    main()
