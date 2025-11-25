#!/usr/bin/env python3
"""GUI para orquestrar os hosts MCP (Ollama ou LM Studio).

A interface reúne em uma única janela todos os parâmetros necessários,
permite checar conectividade, listar modelos disponíveis e executar
os hosts mostrando o progresso das atividades.
"""
from __future__ import annotations

import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional
from urllib.parse import urlsplit

import requests

from interactive_cli import DEFAULT_LIMIT, DEFAULT_MIN_RATING, RunConfig
from mcp_host_lmstudio import LMSTUDIO_MODEL, LMSTUDIO_URL
from mcp_host_ollama import OLLAMA_MODEL, OLLAMA_URL


def _base_url(full_url: str) -> str:
    parsed = urlsplit(full_url)
    return f"{parsed.scheme}://{parsed.netloc}"


class MCPGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("darktable MCP - GUI")
        self.geometry("960x720")
        self.minsize(880, 640)
        self._current_thread: Optional[threading.Thread] = None

        self._build_variables()
        self._build_layout()

    def _build_variables(self) -> None:
        self.host_var = tk.StringVar(value="ollama")
        self.mode_var = tk.StringVar(value="rating")
        self.source_var = tk.StringVar(value="all")
        self.path_contains_var = tk.StringVar()
        self.tag_var = tk.StringVar()
        self.min_rating_var = tk.IntVar(value=DEFAULT_MIN_RATING)
        self.only_raw_var = tk.BooleanVar(value=False)
        self.dry_run_var = tk.BooleanVar(value=True)
        self.limit_var = tk.IntVar(value=DEFAULT_LIMIT)
        self.model_var = tk.StringVar()
        self.url_var = tk.StringVar()
        self.prompt_file_var = tk.StringVar()
        self.target_dir_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Pronto para configurar a execução.")

    def _build_layout(self) -> None:
        main = ttk.Frame(self, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        # Seleção de host e modo
        top_frame = ttk.LabelFrame(main, text="Parâmetros principais", padding=10)
        top_frame.pack(fill=tk.X, pady=(0, 10))

        host_frame = ttk.Frame(top_frame)
        host_frame.pack(fill=tk.X, pady=4)
        ttk.Label(host_frame, text="Framework:").pack(side=tk.LEFT)
        for value, label in (("ollama", "Ollama"), ("lmstudio", "LM Studio")):
            ttk.Radiobutton(host_frame, text=label, value=value, variable=self.host_var).pack(
                side=tk.LEFT, padx=(6, 0)
            )

        mode_frame = ttk.Frame(top_frame)
        mode_frame.pack(fill=tk.X, pady=4)
        ttk.Label(mode_frame, text="Modo:").pack(side=tk.LEFT)
        ttk.Combobox(mode_frame, textvariable=self.mode_var, values=["rating", "tagging", "export"], width=12).pack(
            side=tk.LEFT, padx=6
        )
        ttk.Label(mode_frame, text="Fonte:").pack(side=tk.LEFT, padx=(12, 0))
        ttk.Combobox(mode_frame, textvariable=self.source_var, values=["all", "path", "tag"], width=12).pack(
            side=tk.LEFT, padx=6
        )
        ttk.Label(mode_frame, text="Rating mínimo:").pack(side=tk.LEFT, padx=(12, 0))
        ttk.Spinbox(mode_frame, from_=-2, to=5, textvariable=self.min_rating_var, width=5).pack(
            side=tk.LEFT, padx=6
        )
        ttk.Label(mode_frame, text="Limite:").pack(side=tk.LEFT, padx=(12, 0))
        ttk.Spinbox(mode_frame, from_=1, to=2000, textvariable=self.limit_var, width=7).pack(
            side=tk.LEFT, padx=6
        )

        # Filtros
        filter_frame = ttk.LabelFrame(main, text="Filtros e opções", padding=10)
        filter_frame.pack(fill=tk.X, pady=(0, 10))

        path_row = ttk.Frame(filter_frame)
        path_row.pack(fill=tk.X, pady=4)
        ttk.Label(path_row, text="Path contains:", width=15).pack(side=tk.LEFT)
        ttk.Entry(path_row, textvariable=self.path_contains_var).pack(side=tk.LEFT, fill=tk.X, expand=True)

        tag_row = ttk.Frame(filter_frame)
        tag_row.pack(fill=tk.X, pady=4)
        ttk.Label(tag_row, text="Tag:", width=15).pack(side=tk.LEFT)
        ttk.Entry(tag_row, textvariable=self.tag_var).pack(side=tk.LEFT, fill=tk.X, expand=True)

        prompt_row = ttk.Frame(filter_frame)
        prompt_row.pack(fill=tk.X, pady=4)
        ttk.Label(prompt_row, text="Prompt custom:", width=15).pack(side=tk.LEFT)
        ttk.Entry(prompt_row, textvariable=self.prompt_file_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(prompt_row, text="Selecionar", command=self._choose_prompt_file).pack(side=tk.LEFT, padx=6)

        target_row = ttk.Frame(filter_frame)
        target_row.pack(fill=tk.X, pady=4)
        ttk.Label(target_row, text="Dir export:", width=15).pack(side=tk.LEFT)
        ttk.Entry(target_row, textvariable=self.target_dir_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(target_row, text="Selecionar", command=self._choose_target_dir).pack(side=tk.LEFT, padx=6)

        flags_row = ttk.Frame(filter_frame)
        flags_row.pack(fill=tk.X, pady=4)
        ttk.Checkbutton(flags_row, text="Apenas RAW", variable=self.only_raw_var).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Checkbutton(flags_row, text="Dry-run", variable=self.dry_run_var).pack(side=tk.LEFT)

        # LLM
        llm_frame = ttk.LabelFrame(main, text="LLM", padding=10)
        llm_frame.pack(fill=tk.X, pady=(0, 10))

        model_row = ttk.Frame(llm_frame)
        model_row.pack(fill=tk.X, pady=4)
        ttk.Label(model_row, text="Modelo:", width=15).pack(side=tk.LEFT)
        ttk.Entry(model_row, textvariable=self.model_var).pack(side=tk.LEFT, fill=tk.X, expand=True)

        url_row = ttk.Frame(llm_frame)
        url_row.pack(fill=tk.X, pady=4)
        ttk.Label(url_row, text="URL do servidor:", width=15).pack(side=tk.LEFT)
        ttk.Entry(url_row, textvariable=self.url_var).pack(side=tk.LEFT, fill=tk.X, expand=True)

        action_row = ttk.Frame(llm_frame)
        action_row.pack(fill=tk.X, pady=8)
        ttk.Button(action_row, text="Verificar conectividade", command=self.check_connectivity).pack(
            side=tk.LEFT
        )
        ttk.Button(action_row, text="Listar modelos", command=self.list_models).pack(side=tk.LEFT, padx=6)
        ttk.Button(action_row, text="Executar host", command=self.run_host).pack(side=tk.LEFT, padx=6)

        # Status e log
        status_frame = ttk.Frame(main)
        status_frame.pack(fill=tk.X, pady=(4, 2))
        ttk.Label(status_frame, textvariable=self.status_var).pack(side=tk.LEFT, anchor=tk.W)
        self.progress = ttk.Progressbar(status_frame, mode="indeterminate", length=180)
        self.progress.pack(side=tk.RIGHT)

        log_frame = ttk.LabelFrame(main, text="Log", padding=8)
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.log_text = tk.Text(log_frame, wrap=tk.WORD, height=16)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=scrollbar.set)

    def _choose_prompt_file(self) -> None:
        path = filedialog.askopenfilename(title="Escolher prompt", filetypes=[("Markdown", "*.md"), ("Todos", "*.*")])
        if path:
            self.prompt_file_var.set(path)

    def _choose_target_dir(self) -> None:
        path = filedialog.askdirectory(title="Escolher diretório de export")
        if path:
            self.target_dir_var.set(path)

    # --------------------------- Tarefas assíncronas ---------------------------
    def _run_async(self, description: str, target) -> None:
        if self._current_thread and self._current_thread.is_alive():
            messagebox.showwarning("Execução em andamento", "Aguarde a finalização da tarefa atual.")
            return

        self.status_var.set(description)
        self.progress.start(10)
        self._current_thread = threading.Thread(target=self._wrap_task, args=(target,), daemon=True)
        self._current_thread.start()

    def _wrap_task(self, target) -> None:
        try:
            target()
        except Exception as exc:  # noqa: BLE001 (feedback no log é importante aqui)
            self._append_log(f"[erro] {exc}")
            self._after_ui(lambda: messagebox.showerror("Erro", str(exc)))
        finally:
            self._after_ui(self._stop_progress)

    def _after_ui(self, func) -> None:
        self.after(0, func)

    def _stop_progress(self) -> None:
        self.progress.stop()
        self.status_var.set("Pronto.")

    def _append_log(self, text: str) -> None:
        def _inner():
            self.log_text.insert(tk.END, text + "\n")
            self.log_text.see(tk.END)

        self._after_ui(_inner)

    # --------------------------- Conectividade ---------------------------
    def check_connectivity(self) -> None:
        def task():
            host = self.host_var.get()
            url = self.url_var.get().strip() or (OLLAMA_URL if host == "ollama" else LMSTUDIO_URL)
            if host == "ollama":
                message = self._check_ollama(url)
            else:
                message = self._check_lmstudio(url)
            self._append_log(message)
            self._after_ui(lambda: self.status_var.set(message))

        self._run_async("Verificando conectividade...", task)

    def _check_ollama(self, url: str) -> str:
        base = _base_url(url)
        resp = requests.get(f"{base}/api/tags", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        count = len(data.get("models", []))
        return f"Ollama OK ({count} modelos disponíveis)" if count else "Ollama OK (nenhum modelo listado)"

    def _check_lmstudio(self, url: str) -> str:
        base = _base_url(url)
        resp = requests.get(f"{base}/v1/models", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        models = data.get("data", [])
        count = len(models)
        return f"LM Studio OK ({count} modelos disponíveis)" if count else "LM Studio OK (nenhum modelo listado)"

    # --------------------------- Modelos ---------------------------
    def list_models(self) -> None:
        def task():
            host = self.host_var.get()
            url = self.url_var.get().strip() or (OLLAMA_URL if host == "ollama" else LMSTUDIO_URL)
            if host == "ollama":
                names = self._list_ollama_models(url)
            else:
                names = self._list_lmstudio_models(url)

            if names:
                self._append_log("Modelos disponíveis:\n- " + "\n- ".join(names))
            else:
                self._append_log("Nenhum modelo retornado pelo servidor.")

        self._run_async("Consultando modelos...", task)

    def _list_ollama_models(self, url: str) -> List[str]:
        base = _base_url(url)
        resp = requests.get(f"{base}/api/tags", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        return [m.get("name", "") for m in data.get("models", []) if m.get("name")]

    def _list_lmstudio_models(self, url: str) -> List[str]:
        base = _base_url(url)
        resp = requests.get(f"{base}/v1/models", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        return [m.get("id", "") for m in data.get("data", []) if m.get("id")]

    # --------------------------- Execução ---------------------------
    def run_host(self) -> None:
        try:
            config = self._build_config()
        except ValueError as exc:
            messagebox.showerror("Parâmetros inválidos", str(exc))
            return

        def task():
            cmd = config.build_command()
            self._append_log("Executando: " + " ".join(cmd))
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            assert proc.stdout is not None
            for line in proc.stdout:
                self._append_log(line.rstrip())
            ret = proc.wait()
            if ret == 0:
                self._append_log("Execução concluída com sucesso.")
            else:
                self._append_log(f"Execução finalizada com código {ret}.")

        self._run_async("Executando host...", task)

    def _build_config(self) -> RunConfig:
        host = self.host_var.get()
        mode = self.mode_var.get()
        source = self.source_var.get()

        path_contains = self.path_contains_var.get().strip() or None
        tag = self.tag_var.get().strip() or None
        prompt_file_input = self.prompt_file_var.get().strip() or None
        prompt_file = Path(prompt_file_input).expanduser() if prompt_file_input else None
        target_dir = self.target_dir_var.get().strip() or None

        if source == "path" and not path_contains:
            raise ValueError("'Path contains' é obrigatório quando a fonte é 'path'.")
        if source == "tag" and not tag:
            raise ValueError("Tag é obrigatória quando a fonte é 'tag'.")
        if mode == "export" and not target_dir:
            raise ValueError("Diretório de export é obrigatório em modo export.")

        model_default = OLLAMA_MODEL if host == "ollama" else LMSTUDIO_MODEL
        url_default = OLLAMA_URL if host == "ollama" else LMSTUDIO_URL

        return RunConfig(
            host=host,
            mode=mode,
            source=source,
            path_contains=path_contains,
            tag=tag,
            min_rating=int(self.min_rating_var.get()),
            only_raw=bool(self.only_raw_var.get()),
            dry_run=bool(self.dry_run_var.get()),
            limit=int(self.limit_var.get()),
            model=self.model_var.get().strip() or model_default,
            llm_url=self.url_var.get().strip() or url_default,
            target_dir=target_dir,
            prompt_file=prompt_file,
            extra_flags=[],
        )


def main() -> None:
    app = MCPGui()
    app.mainloop()


if __name__ == "__main__":
    main()
