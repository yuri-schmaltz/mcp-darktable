class IMcpClient:
    """
    Interface para comunicação com o servidor MCP (Lua).
    Permite mocks, testes e extensão futura.
    """
    def initialize(self):
        raise NotImplementedError

    def list_tools(self):
        raise NotImplementedError

    def call_tool(self, name: str, arguments: Optional[dict] = None):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError

    # Métodos utilitários opcionais:
    def start(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False
from __future__ import annotations

import base64
import json
import mimetypes
import os
import shutil
import select
import subprocess
import time
import io
import logging
import logging.handlers
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable, List, Optional, Callable

import requests

try:
    from PIL import Image
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"
PROMPT_DIR = BASE_DIR / "config" / "prompts"
DT_SERVER_CMD = ["lua", str(BASE_DIR / "server" / "dt_mcp_server.lua")]

def setup_logging(verbose: bool = False, json_logging: bool = True):
    """Setup logging with optional JSON format for structured logs."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "mcp_host_debug.log"
    json_log_file = LOG_DIR / "mcp_host_structured.json"
    
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Capture everything
    
    # Standard formatter for text logs
    file_fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    console_fmt = logging.Formatter('[%(levelname)s] %(message)s')
    
    # File Handler (Rotating) - Text format
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_fmt)
    root_logger.addHandler(file_handler)
    
    # JSON File Handler (if enabled)
    if json_logging:
        try:
            from pythonjsonlogger import jsonlogger
            
            json_handler = logging.handlers.RotatingFileHandler(
                json_log_file, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8'
            )
            json_handler.setLevel(logging.DEBUG)
            json_fmt = jsonlogger.JsonFormatter(
                '%(asctime)s %(levelname)s %(name)s %(message)s %(pathname)s %(lineno)d'
            )
            json_handler.setFormatter(json_fmt)
            root_logger.addHandler(json_handler)
            logging.info(f"JSON logging enabled: {json_log_file}")
        except ImportError:
            logging.warning("python-json-logger not installed, skipping JSON logs")
    
    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO if not verbose else logging.DEBUG)
    console_handler.setFormatter(console_fmt)
    root_logger.addHandler(console_handler)
    
    logging.info(f"Logging initialized. File: {log_file}")



@dataclass
class VisionImage:
    meta: dict
    path: Path
    b64: str
    data_url: str


class McpClient:
        # Implementa IMcpClient para permitir polimorfismo e mocks
    def __init__(
        self,
        command: str,
        protocol_version: str,
        client_info: dict,
        log_file: Optional[Path] = None,
        env: Optional[dict] = None,
        response_timeout: float = 30.0,
        appimage_path: Optional[str] = None,
    ):
        self.command = command
        # Se command for AppImage, ajustamos env automaticamente
        self._appimage_proc: Optional[subprocess.Popen] = None
        self._appimage_mount: Optional[str] = None
        self._setup_appimage_env(env, appimage_path)
        
        self.protocol_version = protocol_version
        self.client_info = client_info
        
        # Se montamos um appimage, talvez precisemos ajustar self.command se ele for "lua ..."
        # O script lua precisa saber onde estão as libs. Já injetamos no env.
        
        self.proc = None
        self.request_id = 0
        self.msg_id = 0
        self.log_file = log_file
        self.response_timeout = response_timeout
        self._next_req_id = 1
        
    def _setup_appimage_env(self, env: Optional[dict], appimage_path: Optional[str] = None):
        """Se o comando for um AppImage ou appimage_path for fornecido, monta e configura LD_LIBRARY_PATH."""
        if isinstance(self.command, list):
            exe = self.command[0]
        else:
            cmd_parts = self.command.split()
            exe = cmd_parts[0]
        
        target_appimage = appimage_path
        if not target_appimage:
             if exe.lower().endswith(".appimage") or ".appimage" in exe.lower():
                 target_appimage = exe
        
        if not target_appimage:
             self.env = env
             return

        print(f"[AppImage] Detectado: {target_appimage}")
        try:
            # Inicia montagem
            self._appimage_proc = subprocess.Popen(
                [target_appimage, "--appimage-mount"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Lê a primeira linha para pegar o mount point
            if self._appimage_proc.stdout:
                mount_point = self._appimage_proc.stdout.readline().strip()
                if mount_point:
                    self._appimage_mount = mount_point
                    print(f"[AppImage] Montado em: {mount_point}")
                    
                    # Configura ambiente
                    new_env = (env or os.environ).copy()
                    current_ld = new_env.get("LD_LIBRARY_PATH", "")
                    
                    # Caminhos comuns dentro do AppImage do Darktable
                    libs = [
                        f"{mount_point}/usr/lib",
                        f"{mount_point}/usr/lib/darktable",
                        f"{mount_point}/usr/lib/x86_64-linux-gnu",
                        f"{mount_point}/usr/lib/x86_64-linux-gnu/darktable",
                        f"{mount_point}/usr/lib64",
                        f"{mount_point}/usr/lib64/darktable",
                    ]
                    
                    # Lua path também pode ser necessário
                    current_lua_path = new_env.get("LUA_PATH", "")
                    lua_paths = [
                         f"{mount_point}/usr/share/darktable/lua/?.lua",
                         f"{mount_point}/usr/share/darktable/lua/?/init.lua"
                    ]
                    
                    extra_ld = ":".join(libs)
                    
                    new_env["LD_LIBRARY_PATH"] = f"{extra_ld}:{current_ld}"
                    # new_env["LUA_PATH"] = f"{extra_lua};{current_lua_path}" # Opcional, geralmente lua acha seus libs
                    
                    # IMPORTANTE: Definir DARKTABLE_LIB_PATH para o script Lua saber onde procurar se ele usar lógica customizada
                    # Verifica onde está o libdarktable.so
                    lib_so = Path(mount_point) / "usr/lib/libdarktable.so"
                    if not lib_so.exists():
                         lib_so = Path(mount_point) / "usr/lib64/libdarktable.so"
                    
                    if not lib_so.exists():
                         # Tenta busca profunda se não achar nos padroes
                         print("[AppImage] Procurando libdarktable.so...")
                         found_libs = list(Path(mount_point).rglob("libdarktable.so"))
                         if found_libs:
                             lib_so = found_libs[0]
                    
                    if lib_so.exists():
                        new_env["DARKTABLE_LIB_PATH"] = str(lib_so)
                        print(f"[AppImage] Lib path: {lib_so}")
                    
                    # Tenta achar o darktable-cli dentro do AppImage para usar como comando CLI
                    # Mas cuidado: rodar binários de dentro do AppImage pode falhar sem o ambiente do AppImage
                    # Geralmente melhor usar o próprio AppImage como comando
                    new_env["DARKTABLE_CLI_CMD"] = target_appimage 

                    # Prevent Lua script from trying to re-exec or check flatpak
                    new_env["DT_MCP_LD_REEXEC"] = "1"

                    # CHECK FOR BUNDLED LUA
                    # Se o comando original chama "lua", vamos tentar usar o lua do AppImage
                    # para evitar ABI mismatch (ex: sistema usa 5.3, DT usa 5.4).
                    if isinstance(self.command, list) and self.command[0] == "lua":
                         # Check for bundled first (rare for AppImage to expose it)
                         bundled_lua = Path(mount_point) / "usr/bin/lua"
                         if not bundled_lua.exists():
                             bundled_lua = Path(mount_point) / "usr/bin/luajit"
                         
                         if bundled_lua.exists():
                             print(f"[AppImage] Usando Lua embutido: {bundled_lua}")
                             self.command[0] = str(bundled_lua)
                         else:
                             # Fallback: check for system lua5.4 which matches Darktable's requirements
                             sys_lua54 = shutil.which("lua5.4")
                             if sys_lua54:
                                  print(f"[AppImage] Usando Lua do sistema ({sys_lua54}) para compatibilidade ABI.")
                                  self.command[0] = sys_lua54
                    
                    self.env = new_env
                    return
        except Exception as e:
            print(f"[AppImage] Erro ao montar: {e}")
            self._cleanup_appimage()
            
        self.env = env

    def _cleanup_appimage(self):
        if self._appimage_proc:
            print("[AppImage] Desmontando...")
            self._appimage_proc.terminate()
            try:
                self._appimage_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._appimage_proc.kill()
            self._appimage_proc = None

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
        logging.debug(f"MCP TX: {line}")
        
        assert self.proc.stdin is not None
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()

        assert self.proc.stdout is not None
        ready, _, _ = select.select([self.proc.stdout], [], [], self.response_timeout)
        if not ready:
            stderr_output = self._drain_stderr()
            extra = f" | stderr: {stderr_output}" if stderr_output else ""
            logging.error(f"MCP Timeout: {extra}")
            raise TimeoutError(
                f"Servidor MCP não respondeu em {self.response_timeout}s (timeout){extra}"
            )

        resp_line = self.proc.stdout.readline()
        if not resp_line:
            stderr_output = self._drain_stderr()
            extra = f" | stderr: {stderr_output}" if stderr_output else ""
            logging.error(f"MCP Empty Response: {extra}")
            raise RuntimeError(f"Servidor MCP não respondeu (stdout vazio){extra}")
            
        logging.debug(f"MCP RX: {resp_line.strip()}")
        resp = json.loads(resp_line)
        if "error" in resp:
            raise RuntimeError(resp["error"])
        return resp["result"]

    def _drain_stderr(self) -> str:
        assert self.proc.stderr is not None
        lines = []
        while True:
            ready, _, _ = select.select([self.proc.stderr], [], [], 0)
            if not ready:
                break
            line = self.proc.stderr.readline()
            if not line:
                break
            lines.append(line.strip())
            
        content = " | ".join(lines)
        if content:
            logging.warning(f"MCP STDERR: {content}")
        return content

    def start(self):
        """Inicia o subprocesso do servidor MCP."""
        if self.proc:
            return

        self.proc = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=self.env
        )

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        self._cleanup_appimage()
        return False

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
        if not self.proc:
            return

        still_running = self.proc.poll() is None

        if still_running:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                try:
                    self.proc.wait(timeout=5)
                except Exception:
                    pass
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass

        for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            try:
                if stream:
                    stream.close()
            except Exception:
                pass
        
        self.proc = None


def _ensure_paths() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def post_json_with_retries(
    url: str,
    payload: dict,
    *,
    timeout: float,
    retries: int = 1,
    retry_delay: float = 1.0,
    description: str | None = None,
):
    """Faz POST JSON com retries curtos e logs de tentativa.

    Parameters
    ----------
    url: str
        URL alvo.
    payload: dict
        Corpo JSON enviado.
    timeout: float
        Timeout em segundos.
    retries: int
        Número de novas tentativas após a primeira.
    retry_delay: float
        Intervalo entre tentativas, em segundos.
    description: str | None
        Texto amigável para logs. Se omitido, usa a própria URL.
    """

    desc = description or f"POST {url}"
    attempts = retries + 1
    last_error: Exception | None = None
    last_timeout_msg: str | None = None

    for attempt in range(1, attempts + 1):
        try:
            started = time.time()
            resp = requests.post(url, json=payload, timeout=timeout)
            elapsed_ms = int((time.time() - started) * 1000)
            if attempt > 1:
                print(f"[http] {desc} concluído após retry ({elapsed_ms} ms).")
            return resp, elapsed_ms
        except requests.Timeout as exc:
            last_timeout_msg = (
                f"{desc} excedeu o tempo limite de {timeout}s (tentativa {attempt}/{attempts}). "
                "Ajuste --timeout ou OLLAMA_TIMEOUT se precisar de mais tempo."
            )
            print(f"[http] {last_timeout_msg}")
            last_error = exc
        except requests.RequestException as exc:
            last_error = exc
            print(
                f"[http] Erro ao {desc}: {exc} (tentativa {attempt}/{attempts})."
            )

        if attempt < attempts:
            time.sleep(retry_delay)

    if last_timeout_msg:
        raise SystemExit(last_timeout_msg)

    if last_error:
        raise SystemExit(f"Falha ao {desc}: {last_error}")

    raise SystemExit(f"Falha desconhecida ao {desc}")


def _flatpak_darktable_prefixes() -> list[Path]:
    home = Path.home()
    return [
        home / ".local/share/flatpak/app/org.darktable.Darktable/current/active/files",
        Path("/var/lib/flatpak/app/org.darktable.Darktable/current/active/files"),
    ]


def _flatpak_darktable_available() -> bool:
    if shutil.which("flatpak") is None:
        return False

    # Check if org.darktable.Darktable is installed via flatpak info
    # This is more robust than checking hardcoded paths which might vary
    try:
        subprocess.check_call(
            ["flatpak", "info", "org.darktable.Darktable"], 
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    for prefix in _flatpak_darktable_prefixes():
        if (prefix / "lib" / "libdarktable.so").exists() or (prefix / "lib64" / "libdarktable.so").exists():
            return True
    return False


def _find_appimage() -> str | None:
    """Procura por um AppImage do Darktable em locais comuns."""
    # Prioritize specific known paths to avoid slow recursion
    known_paths = [
        Path.home() / "Apps/Darktable/Darktable.AppImage",
        Path.home() / "Apps/Darktable.AppImage",
    ]
    for p in known_paths:
        if p.exists():
            return str(p)

    search_dirs = [
        Path.cwd(),
        Path.home() / "Apps",
        Path.home() / "Applications",
        Path.home() / "Downloads",
        Path.home() / "bin",
    ]
    
    # Adicionar diretório pai do script se estivermos em modo dev
    try:
        search_dirs.append(Path(__file__).parent.parent)
    except Exception:
        pass

    for d in search_dirs:
        if not d.exists():
            continue
        
        # Avoid recursive search in large directories like Downloads if possible, or limit depth?
        # rglob is too slow for Downloads. Let's use glob for immediate children and
        # maybe one level deep manually if needed. 
        # But for 'Apps' recursion is usually fine.
        
        if d.name in ("Downloads", "bin"):
             # Shallow search for these
             glob_method = d.glob
        else:
             # Deep search for Apps/Applications
             glob_method = d.rglob

        for pattern in ["*Darktable*.AppImage", "*darktable*.AppImage"]:
            try:
                found = list(glob_method(pattern))
                if found:
                    return str(found[0].resolve())
            except Exception:
                pass
    return None


def _suggested_darktable_cli() -> str | None:
    override = os.environ.get("DARKTABLE_CLI_CMD")
    if override:
        return override

    direct = shutil.which("darktable-cli")
    if direct:
        return direct

    if _flatpak_darktable_available():
        return "flatpak run --command=darktable-cli org.darktable.Darktable"

    # Se tiver appimage, assumimos que ele contém o darktable-cli
    # (Ou o usuário deve rodar o AppImage com argumentos específicos)
    # Por enquanto, retornamos o caminho do AppImage como "comando CLI"
    # Opcional: tentar verificar se 'darktable-cli' funciona chamando o AppImage
    appimage = _find_appimage()
    if appimage:
        return appimage

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


def load_prompt(
    mode: str, prompt_file: Optional[str] = None, *, variant: str = "basico"
) -> str:
    if prompt_file:
        path = Path(prompt_file)
    else:
        default_map = {
            "rating": {
                "basico": "rating_basico.md",
                "avancado": "rating_avancado.md",
            },
            "tagging": {
                "basico": "tagging_cliente.md",
                "avancado": "tagging_avancado.md",
            },
            "export": {
                "basico": "export_job.md",
                "avancado": "export_avancado.md",
            },
            "tratamento": {
                "basico": "tratamento_basico.md",
                "avancado": "tratamento_avancado.md",
            },
            "completo": "completo.md",
        }
        mode_entry = default_map.get(mode)
        if not mode_entry:
            raise ValueError(f"Modo desconhecido para prompt: {mode}")

        if isinstance(mode_entry, dict):
            fname = mode_entry.get(variant) or mode_entry.get("basico")
        else:
            fname = mode_entry

        if not fname:
            raise ValueError(f"Prompt não configurado para modo={mode} variante={variant}")
        path = PROMPT_DIR / fname

    if not path.exists():
        raise FileNotFoundError(f"Prompt não encontrado: {path}")
    return path.read_text(encoding="utf-8")


def encode_image_to_base64(image_path: Path, max_dimension: int = 1600) -> tuple[str, str]:
    """
    Lê a imagem, redimensiona se necessário (e se Pillow estiver disponível) 
    e retorna (b64_string, data_url).
    Converte para JPEG para reduzir tamanho de tráfego, a menos que falhe.
    """
    mime, _ = mimetypes.guess_type(image_path.name)
    mime = mime or "image/jpeg"

    if not HAS_PILLOW:
        # Fallback sem otimização
        raw = image_path.read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
        return b64, f"data:{mime};base64,{b64}"

    try:
        with Image.open(image_path) as img:
            # Converter para RGB se necessário (ex: PNG com alpha ou RAWs suportados)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            
            # Redimensionar se for muito grande
            w, h = img.size
            if w > max_dimension or h > max_dimension:
                img.thumbnail((max_dimension, max_dimension))
            
            # Salvar em buffer como JPEG
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=85)
            raw = buffer.getvalue()
            
            # Atualiza mime para JPEG pois convertemos
            mime = "image/jpeg"
            b64 = base64.b64encode(raw).decode("ascii")
            return b64, f"data:{mime};base64,{b64}"

    except Exception as e:
        print(f"[aviso] Falha ao otimizar imagem {image_path.name}: {e}. Usando original.")
        # Fallback em caso de erro no Pillow (ex: arquivo corrompido ou formato não suportado)
        raw = image_path.read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
        return b64, f"data:{mime};base64,{b64}"


def prepare_vision_payloads(
    images: Iterable[dict], 
    attach_images: bool = True,
    progress_callback: Optional[Callable[[int, int, str], None]] = None
):
    payloads: list[VisionImage] = []
    errors: list[str] = []

    if not attach_images:
        return payloads, errors

    # Convert to list to get count
    images_list = list(images)
    total_count = len(images_list)
    
    if total_count > 0:
        logging.info(f"Preparando {total_count} imagem(ns) para envio ao modelo...")
    
    total_b64_size = 0
    
    for idx, img in enumerate(images_list, 1):
        image_path = Path(img.get("path", "")) / str(img.get("filename", ""))
        
        # Get original file size
        try:
            original_size_mb = image_path.stat().st_size / (1024 * 1024)
        except:
            original_size_mb = 0
        
        try:
            b64, data_url = encode_image_to_base64(image_path)
            b64_size_kb = len(b64) / 1024
            total_b64_size += len(b64)
            
            # Log every 10 images or if it's a large set, log less frequently
            log_interval = 50 if total_count > 200 else 10
            if idx % log_interval == 0 or idx == 1 or idx == total_count:
                logging.info(
                    f"Processando imagem {idx}/{total_count}: {image_path.name} "
                    f"({original_size_mb:.1f} MB → {b64_size_kb:.0f} KB base64)"
                )
            
            # Report progress to GUI if callback provided
            if progress_callback and (idx % 3 == 0 or idx == 1 or idx == total_count):
                progress_callback(idx, total_count, "Preparando imagens")
                
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
    
    if payloads:
        total_mb = total_b64_size / (1024 * 1024)
        logging.info(f"{len(payloads)} imagem(ns) preparada(s) ({total_mb:.1f} MB total em base64)")

    return payloads, errors


def prepare_vision_payloads_async(
    images: Iterable[dict], 
    attach_images: bool = True,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    max_workers: int = 4
):
    """
    Asynchronous version of prepare_vision_payloads using ThreadPoolExecutor.
    
    Processes multiple images in parallel for better performance on multi-core systems.
    Maintains compatibility with progress callbacks and error handling.
    
    Args:
        images: Iterable of image dictionaries
        attach_images: Whether to attach images or not
        progress_callback: Optional callback for progress updates (current, total, message)
        max_workers: Maximum number of worker threads (default: 4)
    
    Returns:
        Tuple of (payloads list, errors list)
    """
    payloads: list[VisionImage] = []
    errors: list[str] = []
    
    if not attach_images:
        return payloads, errors
    
    # Convert to list to get count
    images_list = list(images)
    total_count = len(images_list)
    
    if total_count == 0:
        return payloads, errors
    
    logging.info(f"Preparando {total_count} imagem(ns) para envio ao modelo (async com {max_workers} workers)...")
    
    # Thread-safe counter and list
    completed_lock = threading.Lock()
    completed_count = [0]  # Use list to allow modification in nested function
    total_b64_size = [0]
    
    def process_single_image(idx: int, img: dict):
        """Process a single image and return result."""
        image_path = Path(img.get("path", "")) / str(img.get("filename", ""))
        
        # Get original file size
        try:
            original_size_mb = image_path.stat().st_size / (1024 * 1024)
        except:
            original_size_mb = 0
        
        try:
            b64, data_url = encode_image_to_base64(image_path)
            b64_size_kb = len(b64) / 1024
            
            # Thread-safe updates
            with completed_lock:
                completed_count[0] += 1
                total_b64_size[0] += len(b64)
                current = completed_count[0]
            
            # Log every 10 images or if it's a large set, log less frequently
            log_interval = 50 if total_count > 200 else 10
            if idx % log_interval == 0 or idx == 1 or idx == total_count:
                logging.info(
                    f"Processando imagem {idx}/{total_count}: {image_path.name} "
                    f"({original_size_mb:.1f} MB → {b64_size_kb:.0f} KB base64)"
                )
            
            # Report progress to GUI if callback provided (every 3 images)
            if progress_callback and (current % 3 == 0 or current == 1 or current == total_count):
                progress_callback(current, total_count, "Preparando imagens")
            
            return (idx, VisionImage(
                meta=img,
                path=image_path,
                b64=b64,
                data_url=data_url,
            ), None)
            
        except FileNotFoundError:
            error_msg = f"Arquivo não encontrado: {image_path}"
            return (idx, None, error_msg)
        except OSError as exc:
            error_msg = f"Falha ao ler {image_path}: {exc}"
            return (idx, None, error_msg)
        except Exception as exc:
            error_msg = f"Erro inesperado processando {image_path}: {exc}"
            return (idx, None, error_msg)
    
    # Process images in parallel
    results = {}  # idx -> (VisionImage or None, error or None)
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        futures = {
            executor.submit(process_single_image, idx, img): idx 
            for idx, img in enumerate(images_list, 1)
        }
        
        # Collect results as they complete
        for future in as_completed(futures):
            idx, payload, error = future.result()
            results[idx] = (payload, error)
    
    # Reconstruct payloads in original order
    for idx in sorted(results.keys()):
        payload, error = results[idx]
        if error:
            errors.append(error)
        elif payload:
            payloads.append(payload)
    
    if payloads:
        total_mb = total_b64_size[0] / (1024 * 1024)
        logging.info(f"{len(payloads)} imagem(ns) preparada(s) ({total_mb:.1f} MB total em base64)")
    
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



def list_available_collections(client) -> list[dict]:
    res = client.call_tool("list_available_collections", {})
    return res["content"][0]["json"]


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
        # Se falta algo, antes de desistir, vemos se achamos um AppImage
        appimage_path = _find_appimage()
        if appimage_path:
             print(f"[probe] AppImage encontrado: {appimage_path}")
             # Nesse caso, 'missing' pode conter 'darktable-cli', mas o AppImage supre isso.
             # E o 'lua' é do sistema, que deve estar OK (se não, falha igual).
        else:
            return result

    try:
        # Se achou appimage, passa ele
        appimage_path = _find_appimage()
        client = McpClient(
            DT_SERVER_CMD, 
            protocol_version, 
            client_info, 
            appimage_path=appimage_path
        )
        
        # Precisamos conectar startar o processo
        client.start()

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
