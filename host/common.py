from __future__ import annotations

import base64
import json
import mimetypes
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"
PROMPT_DIR = BASE_DIR / "config" / "prompts"
DT_SERVER_CMD = ["lua", str(BASE_DIR / "server" / "dt_mcp_server.lua")]


@dataclass
class VisionImage:
    meta: dict
    path: Path
    b64: str
    data_url: str


class McpClient:
    def __init__(self, cmd: List[str], protocol_version: str, client_info: dict):
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.msg_id = 0
        self.protocol_version = protocol_version
        self.client_info = client_info

    def _next_id(self) -> str:
        self.msg_id += 1
        return str(self.msg_id)

    def request(self, method: str, params: Optional[dict] = None):
        req_id = self._next_id()
        req = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {},
        }
        line = json.dumps(req)
        assert self.proc.stdin is not None
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()

        assert self.proc.stdout is not None
        resp_line = self.proc.stdout.readline()
        if not resp_line:
            raise RuntimeError("Servidor MCP não respondeu (stdout vazio)")
        resp = json.loads(resp_line)
        if "error" in resp:
            raise RuntimeError(resp["error"])
        return resp["result"]

    def initialize(self):
        params = {
            "protocolVersion": self.protocol_version,
            "capabilities": {},
            "clientInfo": self.client_info,
        }
        return self.request("initialize", params)

    def list_tools(self):
        return self.request("tools/list", {})

    def call_tool(self, name: str, arguments: Optional[dict] = None):
        params = {"name": name, "arguments": arguments or {}}
        return self.request("tools/call", params)

    def close(self):
        try:
            self.proc.terminate()
        except Exception:
            pass


def _ensure_paths() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def _flatpak_darktable_prefixes() -> list[Path]:
    home = Path.home()
    return [
        home / ".local/share/flatpak/app/org.darktable.Darktable/current/active/files",
        Path("/var/lib/flatpak/app/org.darktable.Darktable/current/active/files"),
    ]


def _flatpak_darktable_available() -> bool:
    if shutil.which("flatpak") is None:
        return False

    for prefix in _flatpak_darktable_prefixes():
        if (prefix / "lib" / "libdarktable.so").exists() or (prefix / "lib64" / "libdarktable.so").exists():
            return True
    return False


def _suggested_darktable_cli() -> str | None:
    override = os.environ.get("DARKTABLE_CLI_CMD")
    if override:
        return override

    direct = shutil.which("darktable-cli")
    if direct:
        return direct

    if _flatpak_darktable_available():
        return "flatpak run --command=darktable-cli org.darktable.Darktable"

    return None


def dependency_status(binaries: Iterable[str]) -> dict[str, str | None]:
    checks: dict[str, str | None] = {}

    for name in binaries:
        if name == "darktable-cli":
            checks[name] = _suggested_darktable_cli()
        else:
            checks[name] = shutil.which(name)

    return checks


def check_dependencies(binaries: Iterable[str], *, exit_on_success: bool = True) -> list[str]:
    checks = dependency_status(binaries)

    print("[check-deps] Resultado:")
    for name, location in checks.items():
        if location:
            print(f"  - {name}: OK ({location})")
        else:
            print(f"  - {name}: NÃO ENCONTRADO")

    missing = [name for name, location in checks.items() if not location]
    if missing:
        if exit_on_success:
            raise SystemExit(1)
        return missing

    if exit_on_success:
        raise SystemExit(0)
    return []


def load_prompt(mode: str, prompt_file: Optional[str] = None) -> str:
    if prompt_file:
        path = Path(prompt_file)
    else:
        default_map = {
            "rating": "rating_basico.md",
            "tagging": "tagging_cliente.md",
            "export": "export_job.md",
            "tratamento": "tratamento_basico.md",
        }
        fname = default_map.get(mode)
        if not fname:
            raise ValueError(f"Modo desconhecido para prompt: {mode}")
        path = PROMPT_DIR / fname

    if not path.exists():
        raise FileNotFoundError(f"Prompt não encontrado: {path}")
    return path.read_text(encoding="utf-8")


def encode_image_to_base64(image_path: Path) -> tuple[str, str]:
    raw = image_path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    mime, _ = mimetypes.guess_type(image_path.name)
    mime = mime or "image/jpeg"
    data_url = f"data:{mime};base64,{b64}"
    return b64, data_url


def prepare_vision_payloads(images: Iterable[dict], attach_images: bool = True):
    payloads: list[VisionImage] = []
    errors: list[str] = []

    if not attach_images:
        return payloads, errors

    for img in images:
        image_path = Path(img.get("path", "")) / str(img.get("filename", ""))
        try:
            b64, data_url = encode_image_to_base64(image_path)
        except FileNotFoundError:
            errors.append(f"Arquivo não encontrado: {image_path}")
            continue
        except OSError as exc:
            errors.append(f"Falha ao ler {image_path}: {exc}")
            continue

        payloads.append(
            VisionImage(
                meta=img,
                path=image_path,
                b64=b64,
                data_url=data_url,
            )
        )

    return payloads, errors


def fallback_user_prompt(sample: list[dict]) -> str:
    return "Lista (amostra) de imagens do darktable:\n" + json.dumps(sample, ensure_ascii=False)


def fetch_images(client: McpClient, args) -> list[dict]:
    params = {
        "min_rating": args.min_rating,
        "only_raw": bool(args.only_raw),
    }

    if args.source == "all":
        tool_name = "list_collection"
    elif args.source == "collection":
        tool_name = "list_collection"
        if not args.collection:
            raise ValueError("--collection é obrigatório quando source=collection")
        params["collection_path"] = args.collection
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


def probe_darktable_state(
    protocol_version: str,
    client_info: dict,
    *,
    min_rating: int = -2,
    only_raw: bool = False,
    sample_limit: int = 20,
) -> dict:
    """Executa uma sondagem rápida no darktable via MCP.

    Retorna dependências encontradas, ferramentas disponíveis, coleções e
    uma amostra das imagens conhecidas.
    """

    dep_map = dependency_status(["lua", "darktable-cli"])
    missing = [name for name, location in dep_map.items() if not location]

    result: dict = {
        "dependencies": dep_map,
        "missing_dependencies": missing,
    }

    if missing:
        return result

    try:
        client = McpClient(DT_SERVER_CMD, protocol_version, client_info)
    except FileNotFoundError as exc:  # noqa: BLE001
        result["error"] = f"Falha ao iniciar servidor MCP: {exc}"
        return result

    try:
        init = client.initialize()
        tools = client.list_tools()
        tool_names = [t.get("name") for t in tools.get("tools", []) if t.get("name")]

        collections_raw = client.call_tool("list_available_collections", {})
        collections_content = collections_raw.get("content") or []
        first_content = collections_content[0] if collections_content else {}
        collections = first_content.get("json", []) if isinstance(first_content, dict) else []
        collections_sorted = sorted(collections, key=lambda c: c.get("path", ""))

        probe_args = SimpleNamespace(
            source="all",
            min_rating=min_rating,
            only_raw=only_raw,
            path_contains=None,
            tag=None,
            collection=None,
        )
        images = fetch_images(client, probe_args)
        sample = images[: max(1, min(sample_limit, len(images)))]

        result.update(
            {
                "server_info": init.get("serverInfo", {}),
                "tools": tool_names,
                "collections": collections_sorted,
                "sample_images": sample,
                "image_total": len(images),
            }
        )
        return result
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
        return result
    finally:
        client.close()


def save_log(mode: str, source: str, images: list[dict], model_answer: str, extra=None):
    _ensure_paths()
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


def append_export_result_to_log(log_file: Path, export_result: dict) -> Path:
    try:
        existing = json.loads(log_file.read_text(encoding="utf-8"))
    except Exception:
        existing = None

    if isinstance(existing, dict):
        extra = existing.get("extra") or {}
        extra["export_result"] = export_result
        existing["extra"] = extra
        log_file.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        return log_file

    fallback = LOG_DIR / f"{log_file.stem}-export-result{log_file.suffix}"
    fallback.write_text(json.dumps(export_result, ensure_ascii=False, indent=2), encoding="utf-8")
    return fallback


def extract_export_errors(result_payload: dict):
    for part in result_payload.get("content", []):
        if isinstance(part, dict) and isinstance(part.get("json"), dict):
            maybe_errors = part["json"].get("errors")
            if maybe_errors:
                return maybe_errors
    return []
