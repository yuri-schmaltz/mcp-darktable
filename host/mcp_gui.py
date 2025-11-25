#!/usr/bin/env python3
"""GUI para orquestrar os hosts MCP (Ollama ou LM Studio).

A interface reúne em uma única janela todos os parâmetros necessários,
permite checar conectividade, listar modelos disponíveis e executar
os hosts mostrando o progresso das atividades.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, List, Optional
from urllib.parse import urlsplit

import requests

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QRadioButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from interactive_cli import DEFAULT_LIMIT, DEFAULT_MIN_RATING, RunConfig
from mcp_host_lmstudio import LMSTUDIO_MODEL, LMSTUDIO_URL
from mcp_host_ollama import OLLAMA_MODEL, OLLAMA_URL


def _base_url(full_url: str) -> str:
    parsed = urlsplit(full_url)
    return f"{parsed.scheme}://{parsed.netloc}"


class MCPGui(QMainWindow):
    log_signal = Signal(str)
    status_signal = Signal(str)
    progress_signal = Signal(bool)
    error_signal = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("darktable MCP - GUI")
        self.resize(960, 720)
        self.setMinimumSize(880, 640)
        self._current_thread: Optional[threading.Thread] = None

        self.log_signal.connect(self._append_log_ui)
        self.status_signal.connect(self._set_status_ui)
        self.progress_signal.connect(self._toggle_progress)
        self.error_signal.connect(self._show_error)

        self._apply_global_style()
        self._build_layout()
        self._apply_defaults()
        self._connect_dynamic_behaviors()

    def _apply_global_style(self) -> None:
        self.setStyleSheet(
            """
            QWidget { font-size: 14px; }
            QGroupBox { font-weight: 600; }
            QLabel { color: #2c3e50; }
            QPushButton { padding: 6px 12px; min-height: 34px; }
            QLineEdit, QComboBox, QSpinBox { padding: 6px; min-height: 32px; }
            QTextEdit { padding: 8px; min-height: 140px; font-family: "JetBrains Mono", "Fira Code", monospace; }
            QCheckBox, QRadioButton { min-height: 28px; }
            """
        )

    def _build_layout(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(12)

        top_group = QGroupBox("Parâmetros principais")
        top_layout = QVBoxLayout(top_group)
        top_layout.setContentsMargins(8, 12, 8, 12)
        top_layout.setSpacing(10)

        host_layout = QHBoxLayout()
        host_layout.setSpacing(12)
        host_layout.addWidget(QLabel("Framework:"))
        self.host_group = QButtonGroup(self)
        self.host_ollama = QRadioButton("Ollama")
        self.host_ollama.setChecked(True)
        self.host_lmstudio = QRadioButton("LM Studio")
        self.host_group.addButton(self.host_ollama)
        self.host_group.addButton(self.host_lmstudio)
        host_layout.addWidget(self.host_ollama)
        host_layout.addWidget(self.host_lmstudio)
        host_layout.addStretch()
        top_layout.addLayout(host_layout)

        mode_layout = QHBoxLayout()
        mode_layout.setSpacing(12)
        mode_layout.addWidget(QLabel("Modo:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["rating", "tagging", "export"])
        mode_layout.addWidget(self.mode_combo)
        mode_layout.addSpacing(12)

        mode_layout.addWidget(QLabel("Fonte:"))
        self.source_combo = QComboBox()
        self.source_combo.addItems(["all", "path", "tag"])
        mode_layout.addWidget(self.source_combo)
        mode_layout.addSpacing(12)

        mode_layout.addWidget(QLabel("Rating mínimo:"))
        self.min_rating_spin = QSpinBox()
        self.min_rating_spin.setRange(-2, 5)
        self.min_rating_spin.setValue(DEFAULT_MIN_RATING)
        self.min_rating_spin.setFixedWidth(70)
        mode_layout.addWidget(self.min_rating_spin)
        mode_layout.addSpacing(12)

        mode_layout.addWidget(QLabel("Limite:"))
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 2000)
        self.limit_spin.setValue(DEFAULT_LIMIT)
        self.limit_spin.setFixedWidth(90)
        mode_layout.addWidget(self.limit_spin)
        mode_layout.addStretch()
        top_layout.addLayout(mode_layout)

        main_layout.addWidget(top_group)

        filter_group = QGroupBox("Filtros e opções")
        filter_layout = QVBoxLayout(filter_group)
        filter_layout.setContentsMargins(8, 12, 8, 12)
        filter_layout.setSpacing(10)

        self.path_contains_edit = self._add_labeled_row(filter_layout, "Path contains:")
        self.tag_edit = self._add_labeled_row(filter_layout, "Tag:")
        prompt_layout, self.prompt_edit = self._add_labeled_row(filter_layout, "Prompt custom:", return_layout=True)
        prompt_button = QPushButton("Selecionar")
        prompt_button.clicked.connect(self._choose_prompt_file)
        prompt_layout.addWidget(prompt_button)

        target_layout, self.target_edit = self._add_labeled_row(filter_layout, "Dir export:", return_layout=True)
        self.target_button = QPushButton("Selecionar")
        self.target_button.clicked.connect(self._choose_target_dir)
        target_layout.addWidget(self.target_button)

        flags_layout = QHBoxLayout()
        flags_layout.setSpacing(12)
        self.only_raw_check = QCheckBox("Apenas RAW")
        self.dry_run_check = QCheckBox("Dry-run")
        self.dry_run_check.setChecked(True)
        flags_layout.addWidget(self.only_raw_check)
        flags_layout.addSpacing(12)
        flags_layout.addWidget(self.dry_run_check)
        flags_layout.addStretch()
        filter_layout.addLayout(flags_layout)

        main_layout.addWidget(filter_group)

        llm_group = QGroupBox("LLM")
        llm_layout = QVBoxLayout(llm_group)
        llm_layout.setContentsMargins(8, 12, 8, 12)
        llm_layout.setSpacing(10)

        self.model_edit = self._add_labeled_row(llm_layout, "Modelo:")
        self.url_edit = self._add_labeled_row(llm_layout, "URL do servidor:")

        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(8)
        check_button = QPushButton("Verificar conectividade")
        check_button.clicked.connect(self.check_connectivity)
        actions_layout.addWidget(check_button)

        list_button = QPushButton("Listar modelos")
        list_button.clicked.connect(self.list_models)
        actions_layout.addWidget(list_button)

        download_button = QPushButton("Baixar modelo")
        download_button.clicked.connect(self.download_model)
        actions_layout.addWidget(download_button)

        run_button = QPushButton("Executar host")
        run_button.clicked.connect(self.run_host)
        actions_layout.addWidget(run_button)
        actions_layout.addStretch()
        llm_layout.addLayout(actions_layout)

        main_layout.addWidget(llm_group)

        status_layout = QHBoxLayout()
        status_layout.setSpacing(10)
        self.status_label = QLabel("Pronto para configurar a execução.")
        self.status_label.setWordWrap(True)
        status_layout.addWidget(self.status_label, alignment=Qt.AlignmentFlag.AlignLeft)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(180)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        status_layout.addWidget(self.progress)
        main_layout.addLayout(status_layout)

        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(8, 12, 8, 12)
        log_layout.setSpacing(10)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        clear_log = QPushButton("Limpar log")
        clear_log.setToolTip("Remove o conteúdo exibido acima")
        clear_log.clicked.connect(self.log_text.clear)
        log_layout.addWidget(self.log_text)
        log_layout.addWidget(clear_log, alignment=Qt.AlignmentFlag.AlignRight)
        main_layout.addWidget(log_group, stretch=1)

    def _add_labeled_row(
        self, layout: QVBoxLayout, label: str, *, return_layout: bool = False
    ) -> QLineEdit | tuple[QHBoxLayout, QLineEdit]:
        row_layout = QHBoxLayout()
        row_layout.setSpacing(10)
        lbl = QLabel(label)
        lbl.setFixedWidth(120)
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row_layout.addWidget(lbl)
        line_edit = QLineEdit()
        line_edit.setMinimumWidth(260)
        row_layout.addWidget(line_edit, stretch=1)
        layout.addLayout(row_layout)
        if return_layout:
            return row_layout, line_edit
        return line_edit

    def _choose_prompt_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Escolher prompt", "", "Markdown (*.md);;Todos (*.*)"
        )
        if path:
            self.prompt_edit.setText(path)

    def _choose_target_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Escolher diretório de export")
        if path:
            self.target_edit.setText(path)

    def _apply_defaults(self) -> None:
        self.path_contains_edit.setPlaceholderText("/cliente-x/viagem")
        self.tag_edit.setPlaceholderText("job:cliente")
        self.prompt_edit.setPlaceholderText("Arquivo .md opcional com prompt customizado")
        self.target_edit.setPlaceholderText("Diretório de export (apenas modo export)")
        self.model_edit.setPlaceholderText("Nome do modelo disponível no host")
        self.url_edit.setPlaceholderText("http://localhost:11434 ou http://localhost:1234/v1")
        self.log_text.setPlaceholderText("Logs e progresso serão exibidos aqui...")
        self._apply_host_defaults()
        self._update_source_fields(self.source_combo.currentText())
        self._update_mode_fields(self.mode_combo.currentText())

    def _connect_dynamic_behaviors(self) -> None:
        self.host_ollama.toggled.connect(lambda checked: checked and self._apply_host_defaults())
        self.host_lmstudio.toggled.connect(lambda checked: checked and self._apply_host_defaults())
        self.source_combo.currentTextChanged.connect(self._update_source_fields)
        self.mode_combo.currentTextChanged.connect(self._update_mode_fields)

    def _apply_host_defaults(self) -> None:
        host = self._selected_host()
        model_default = OLLAMA_MODEL if host == "ollama" else LMSTUDIO_MODEL
        url_default = OLLAMA_URL if host == "ollama" else LMSTUDIO_URL

        current_model = self.model_edit.text().strip()
        current_url = self.url_edit.text().strip()

        if not current_model or current_model in {OLLAMA_MODEL, LMSTUDIO_MODEL}:
            self.model_edit.setText(model_default)
        if not current_url or current_url in {OLLAMA_URL, LMSTUDIO_URL}:
            self.url_edit.setText(url_default)

    def _update_source_fields(self, source: str) -> None:
        is_path = source == "path"
        is_tag = source == "tag"
        self.path_contains_edit.setEnabled(is_path)
        self.tag_edit.setEnabled(is_tag)
        self.path_contains_edit.setToolTip("Filtrar apenas por caminho contendo este trecho" if is_path else "Disponível somente quando a fonte for 'path'")
        self.tag_edit.setToolTip("Tag existente no darktable" if is_tag else "Disponível somente quando a fonte for 'tag'")

    def _update_mode_fields(self, mode: str) -> None:
        is_export = mode == "export"
        self.target_edit.setEnabled(is_export)
        self.target_button.setEnabled(is_export)
        tooltip = "Necessário apenas para export" if is_export else "Habilite ao selecionar modo export"
        self.target_edit.setToolTip(tooltip)
        self.target_button.setToolTip(tooltip)

    # --------------------------- Tarefas assíncronas ---------------------------
    def _run_async(self, description: str, target: Callable[[], None]) -> None:
        if self._current_thread and self._current_thread.is_alive():
            QMessageBox.warning(self, "Execução em andamento", "Aguarde a finalização da tarefa atual.")
            return

        self.status_signal.emit(description)
        self.progress_signal.emit(True)
        self._current_thread = threading.Thread(target=self._wrap_task, args=(target,), daemon=True)
        self._current_thread.start()

    def _wrap_task(self, target) -> None:
        try:
            target()
        except Exception as exc:  # noqa: BLE001 (feedback no log é importante aqui)
            self._append_log(f"[erro] {exc}")
            self.error_signal.emit(str(exc))
        finally:
            self.progress_signal.emit(False)

    def _append_log(self, text: str) -> None:
        self.log_signal.emit(text)

    @Slot(str)
    def _append_log_ui(self, text: str) -> None:
        self.log_text.append(text)
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())

    @Slot(str)
    def _set_status_ui(self, text: str) -> None:
        self.status_label.setText(text)

    @Slot(bool)
    def _toggle_progress(self, running: bool) -> None:
        if running:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 1)
            self.progress.setValue(0)
            self.status_label.setText("Pronto.")

    @Slot(str)
    def _show_error(self, message: str) -> None:
        QMessageBox.critical(self, "Erro", message)

    # --------------------------- Conectividade ---------------------------
    def check_connectivity(self) -> None:
        def task():
            host = self._selected_host()
            url = self.url_edit.text().strip() or (OLLAMA_URL if host == "ollama" else LMSTUDIO_URL)
            if host == "ollama":
                message = self._check_ollama(url)
            else:
                message = self._check_lmstudio(url)
            self._append_log(message)
            self.status_signal.emit(message)

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
            host = self._selected_host()
            url = self.url_edit.text().strip() or (OLLAMA_URL if host == "ollama" else LMSTUDIO_URL)
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

    def download_model(self) -> None:
        def task():
            host = self._selected_host()
            if host != "ollama":
                self._append_log("Download automático disponível apenas para Ollama.")
                return

            model = self.model_edit.text().strip() or OLLAMA_MODEL
            url = self.url_edit.text().strip() or OLLAMA_URL
            statuses = self._pull_ollama_model(model, url)
            self._append_log(
                f"Download de '{model}':\n- " + "\n- ".join(statuses)
            )

        self._run_async("Baixando modelo...", task)

    def _pull_ollama_model(self, model: str, url: str) -> List[str]:
        base = _base_url(url)
        resp = requests.post(f"{base}/api/pull", json={"model": model}, stream=True, timeout=5)
        resp.raise_for_status()

        statuses: List[str] = []
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
            QMessageBox.critical(self, "Parâmetros inválidos", str(exc))
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
        host = self._selected_host()
        mode = self.mode_combo.currentText()
        source = self.source_combo.currentText()

        path_contains = self.path_contains_edit.text().strip() or None
        tag = self.tag_edit.text().strip() or None
        prompt_file_input = self.prompt_edit.text().strip() or None
        prompt_file = Path(prompt_file_input).expanduser() if prompt_file_input else None
        target_dir = self.target_edit.text().strip() or None

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
            min_rating=int(self.min_rating_spin.value()),
            only_raw=bool(self.only_raw_check.isChecked()),
            dry_run=bool(self.dry_run_check.isChecked()),
            limit=int(self.limit_spin.value()),
            model=self.model_edit.text().strip() or model_default,
            llm_url=self.url_edit.text().strip() or url_default,
            target_dir=target_dir,
            prompt_file=prompt_file,
            extra_flags=[],
        )

    def _selected_host(self) -> str:
        return "ollama" if self.host_ollama.isChecked() else "lmstudio"


def main() -> None:
    qt_app = QApplication(sys.argv)
    qt_app.setStyle("Fusion")
    window = MCPGui()
    window.show()
    qt_app.exec()


if __name__ == "__main__":
    main()
