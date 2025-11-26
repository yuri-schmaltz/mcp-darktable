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
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QGridLayout,
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
    QSizePolicy,
    QSpinBox,
    QStyle,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from interactive_cli import DEFAULT_LIMIT, DEFAULT_MIN_RATING, RunConfig
from mcp_host_lmstudio import LMSTUDIO_MODEL, LMSTUDIO_URL
from mcp_host_ollama import OLLAMA_MODEL, OLLAMA_URL, load_prompt as load_ollama_prompt


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
        self.resize(1040, 760)
        self.setMinimumSize(820, 620)
        self._current_thread: Optional[threading.Thread] = None

        self.log_signal.connect(self._append_log_ui)
        self.status_signal.connect(self._set_status_ui)
        self.progress_signal.connect(self._toggle_progress)
        self.error_signal.connect(self._show_error)

        self._apply_global_style()
        self._build_menu_bar()
        self._build_layout()
        self._apply_defaults()
        self._connect_dynamic_behaviors()

    # --------------------------------------------------------------------- UI --

    def _apply_global_style(self) -> None:
        # Estilo global bem neutro, só padronizando tamanhos e fontes
        self.setStyleSheet(
            """
            QWidget {
                font-size: 13px;
            }

            QGroupBox {
                font-weight: 600;
                margin-top: 10px;
            }

            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }

            QLabel {
                color: #e0e0e0;
            }

            QLineEdit,
            QComboBox,
            QSpinBox {
                padding: 4px 6px;
                min-height: 26px;
            }

            QTextEdit {
                padding: 4px 6px;
                min-height: 140px;
                font-family: "JetBrains Mono", "Fira Code", monospace;
            }

            QPushButton {
                padding: 6px 14px;
                min-height: 28px;
                min-width: 140px;
            }

            QCheckBox,
            QRadioButton {
                min-height: 22px;
            }

            QProgressBar {
                min-height: 16px;
            }
            """
        )

    def _build_layout(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(14)

        # ---------------------- Grupo: Parâmetros principais --------------------
        top_group = QGroupBox("Parâmetros principais")
        top_layout = QGridLayout(top_group)
        top_layout.setContentsMargins(14, 12, 14, 12)
        top_layout.setHorizontalSpacing(14)
        top_layout.setVerticalSpacing(12)

        # Linha: Modo / Fonte / Rating mínimo / Limite
        mode_label = QLabel("Modo:")
        mode_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["rating", "tagging", "export", "tratamento"])
        self.mode_combo.setToolTip(
            "Define o tipo de operação: atribuir notas, sugerir tags, exportar ou tratamento"
        )

        source_label = QLabel("Fonte:")
        source_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.source_combo = QComboBox()
        self.source_combo.addItems(["all", "path", "tag", "collection"])
        self.source_combo.setToolTip(
            "Escolhe de onde as imagens serão obtidas: todas, por caminho, por tag ou coleção"
        )

        min_label = QLabel("Rating mínimo:")
        min_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.min_rating_spin = QSpinBox()
        self.min_rating_spin.setRange(-2, 5)
        self.min_rating_spin.setValue(DEFAULT_MIN_RATING)
        self.min_rating_spin.setFixedWidth(80)
        self.min_rating_spin.setToolTip(
            "Nota mínima das imagens que serão consideradas (de -2 a 5)"
        )

        limit_label = QLabel("Limite:")
        limit_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 2000)
        self.limit_spin.setValue(DEFAULT_LIMIT)
        self.limit_spin.setFixedWidth(100)
        self.limit_spin.setToolTip(
            "Quantidade máxima de imagens processadas nesta execução"
        )

        top_layout.addWidget(mode_label, 0, 0)
        top_layout.addWidget(self.mode_combo, 0, 1)
        top_layout.addWidget(source_label, 0, 2)
        top_layout.addWidget(self.source_combo, 0, 3)
        top_layout.addWidget(min_label, 0, 4)
        top_layout.addWidget(self.min_rating_spin, 0, 5)
        top_layout.addWidget(limit_label, 0, 6)
        top_layout.addWidget(self.limit_spin, 0, 7)

        top_layout.setColumnStretch(1, 1)
        top_layout.setColumnStretch(3, 1)

        main_layout.addWidget(top_group)

        # -------------------------- Grupo: Filtros e opções ---------------------
        filter_group = QGroupBox("Filtros e opções")
        filter_layout = QGridLayout(filter_group)
        filter_layout.setContentsMargins(14, 12, 14, 12)
        filter_layout.setHorizontalSpacing(14)
        filter_layout.setVerticalSpacing(12)

        # col 0 = label, col 1 = campo (expansível), col 2 = botão
        filter_layout.setColumnStretch(1, 1)
        filter_layout.setColumnMinimumWidth(0, 120)
        filter_layout.setColumnMinimumWidth(2, 110)

        self.path_contains_edit = QLineEdit()
        self.tag_edit = QLineEdit()
        self.collection_edit = QLineEdit()
        self.prompt_edit = QLineEdit()
        self.target_edit = QLineEdit()
        self.prompt_edit.setToolTip(
            "Arquivo Markdown opcional com instruções adicionais para o modelo"
        )
        self.target_edit.setToolTip("Diretório onde as exportações serão salvas")

        # Path
        self._add_form_row(filter_layout, 0, "Path contains:", self.path_contains_edit)

        # Tag
        self._add_form_row(filter_layout, 1, "Tag:", self.tag_edit)

        # Collection
        self._add_form_row(filter_layout, 2, "Coleção:", self.collection_edit)

        # Prompt custom (+ botões Selecionar / Gerar modelo)
        self._add_form_row(filter_layout, 3, "Prompt custom:", self.prompt_edit)
        prompt_buttons = QHBoxLayout()
        prompt_buttons.setSpacing(8)

        self.prompt_button = QPushButton("Selecionar")
        self._standardize_button(self.prompt_button)
        self.prompt_button.clicked.connect(self._choose_prompt_file)
        prompt_buttons.addWidget(self.prompt_button)

        self.prompt_generate_button = QPushButton("Gerar modelo")
        self._standardize_button(self.prompt_generate_button)
        self.prompt_generate_button.clicked.connect(self._generate_prompt_template)
        prompt_buttons.addWidget(self.prompt_generate_button)

        prompt_buttons.addStretch()
        filter_layout.addLayout(prompt_buttons, 3, 2)

        # Dir export (+ botão Selecionar)
        self._add_form_row(filter_layout, 4, "Dir export:", self.target_edit)
        self.target_button = QPushButton("Selecionar")
        self._standardize_button(self.target_button)
        self.target_button.clicked.connect(self._choose_target_dir)
        self.target_button.setToolTip("Seleciona a pasta onde os arquivos exportados serão gravados")
        filter_layout.addWidget(self.target_button, 4, 2)

        # Checkboxes
        flags_layout = QHBoxLayout()
        flags_layout.setSpacing(20)

        self.only_raw_check = QCheckBox("Apenas RAW")
        self.dry_run_check = QCheckBox("Dry-run")
        self.dry_run_check.setChecked(True)
        self.only_raw_check.setToolTip("Processa somente arquivos RAW (ignora JPEGs e derivados)")
        self.dry_run_check.setToolTip(
            "Simula a execução sem escrever arquivos ou alterar metadados"
        )

        flags_layout.addStretch()
        flags_layout.addWidget(self.only_raw_check)
        flags_layout.addWidget(self.dry_run_check)
        flags_layout.addStretch()

        # ocupa as três colunas (label + campo + botão)
        filter_layout.addLayout(flags_layout, 5, 0, 1, 3)

        main_layout.addWidget(filter_group)

        # ------------------------------- Grupo LLM ------------------------------
        llm_group = QGroupBox("LLM")
        llm_layout = QGridLayout(llm_group)
        llm_layout.setContentsMargins(14, 12, 14, 12)
        llm_layout.setHorizontalSpacing(14)
        llm_layout.setVerticalSpacing(12)
        llm_layout.setColumnStretch(1, 1)
        llm_layout.setColumnStretch(3, 1)

        framework_label = QLabel("Framework:")
        framework_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.host_group = QButtonGroup(self)
        self.host_ollama = QRadioButton("Ollama")
        self.host_ollama.setChecked(True)
        self.host_lmstudio = QRadioButton("LM Studio")
        self.host_group.addButton(self.host_ollama)
        self.host_group.addButton(self.host_lmstudio)
        self.host_ollama.setToolTip("Usa um servidor Ollama para executar o modelo")
        self.host_lmstudio.setToolTip("Usa um servidor LM Studio para executar o modelo")
        host_layout = QHBoxLayout()
        host_layout.setSpacing(14)
        host_layout.addWidget(self.host_ollama)
        host_layout.addWidget(self.host_lmstudio)
        host_layout.addStretch()
        llm_layout.addWidget(framework_label, 0, 0)
        llm_layout.addLayout(host_layout, 0, 1)

        self.model_edit = QLineEdit()
        self.url_edit = QLineEdit()
        self.url_edit.setToolTip("URL base do servidor LLM escolhido")
        self.model_edit.setToolTip("Nome do modelo carregado no servidor selecionado")

        url_label = QLabel("URL do servidor:")
        url_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        url_label.setMinimumWidth(120)
        self._style_form_field(self.url_edit)

        model_label = QLabel("Modelo:")
        model_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        model_label.setMinimumWidth(120)
        self._style_form_field(self.model_edit)

        llm_layout.addWidget(url_label, 1, 0)
        llm_layout.addWidget(self.url_edit, 1, 1)
        llm_layout.addWidget(model_label, 1, 2)
        llm_layout.addWidget(self.model_edit, 1, 3)

        list_button = QPushButton()
        list_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogListView)
        )
        list_button.setToolTip("Listar modelos")
        list_button.setFixedSize(40, 32)
        list_button.clicked.connect(self.list_models)
        llm_layout.addWidget(list_button, 1, 4)

        check_button = QPushButton()
        check_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
        )
        check_button.setToolTip("Verificar conectividade")
        check_button.setFixedSize(40, 32)
        check_button.clicked.connect(self.check_connectivity)
        llm_layout.addWidget(check_button, 1, 5)

        main_layout.addWidget(llm_group)

        # ------------------------------------ Log -------------------------------
        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(14, 12, 14, 12)
        log_layout.setSpacing(10)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.log_text.setFixedHeight(70)
        self.log_text.setToolTip("Saída detalhada das ações executadas pelo host")

        clear_log = QPushButton("Limpar log")
        self._standardize_button(clear_log)
        clear_log.setToolTip("Remove o conteúdo exibido acima")
        clear_log.clicked.connect(self.log_text.clear)

        log_layout.addWidget(self.log_text)
        log_layout.addWidget(clear_log, alignment=Qt.AlignmentFlag.AlignRight)

        main_layout.addWidget(log_group, stretch=1)

        self.run_button = QPushButton("Executar host")
        self._standardize_button(self.run_button)
        self.run_button.setToolTip("Inicia o host com os parâmetros configurados")
        self.run_button.clicked.connect(self.run_host)

        run_row = QHBoxLayout()
        run_row.setContentsMargins(0, 8, 0, 0)
        run_row.addStretch()
        run_row.addWidget(self.run_button)

        main_layout.addLayout(run_row)

        self._build_status_bar()

    def _build_menu_bar(self) -> None:
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("Arquivo")

        quit_action = QAction(self.style().standardIcon(QStyle.SP_TitleBarCloseButton), "Sair", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

    def _build_status_bar(self) -> None:
        status_bar = QStatusBar()
        status_bar.setSizeGripEnabled(False)

        self.status_label = QLabel("Pronto para configurar a execução.")
        self.status_label.setMinimumWidth(260)
        self.status_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(16)
        self.progress.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self.progress.setFixedWidth(200)

        status_bar.addWidget(self.status_label, 1)
        status_bar.addPermanentWidget(self.progress)
        self.setStatusBar(status_bar)

    def _style_form_field(self, widget: QLineEdit) -> None:
        widget.setMinimumWidth(260)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def _add_form_row(
        self,
        layout: QGridLayout,
        row: int,
        label_text: str,
        widget: QLineEdit,
    ) -> QHBoxLayout:
        label = QLabel(label_text)
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        label.setMinimumWidth(120)

        self._style_form_field(widget)

        widget_layout = QHBoxLayout()
        widget_layout.setSpacing(10)
        widget_layout.addWidget(widget)

        layout.addWidget(label, row, 0)
        layout.addLayout(widget_layout, row, 1)

        return widget_layout

    def _standardize_button(self, button: QPushButton) -> None:
        button.setMinimumWidth(120)
        button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    # ----------------------------------------------------------------- Defaults --

    def _choose_prompt_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Escolher prompt",
            "",
            "Markdown (*.md);;Todos (*.*)",
        )
        if path:
            self.prompt_edit.setText(path)

    def _generate_prompt_template(self) -> None:
        mode = self.mode_combo.currentText()
        try:
            template = load_ollama_prompt(mode)
        except Exception as exc:  # pragma: no cover - apenas GUI
            QMessageBox.critical(
                self,
                "Erro ao gerar modelo",
                f"Não foi possível carregar o prompt padrão para '{mode}'.\n{exc}",
            )
            return

        suggested = Path.home() / f"prompt_{mode}.md"
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar modelo de prompt",
            str(suggested),
            "Markdown (*.md);;Todos (*.*)",
        )
        if not target:
            return

        try:
            target_path = Path(target).expanduser()
            target_path.write_text(template, encoding="utf-8")
        except Exception as exc:  # pragma: no cover - apenas GUI
            QMessageBox.critical(
                self,
                "Erro ao salvar",
                f"Não foi possível salvar o modelo em '{target}'.\n{exc}",
            )
            return

        self.prompt_edit.setText(str(target_path))
        QMessageBox.information(
            self,
            "Modelo criado",
            "Arquivo gerado a partir do prompt padrão do modo selecionado.\n"
            "Você pode editá-lo e o caminho já foi preenchido no campo de prompt.",
        )

    def _choose_target_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self,
            "Escolher diretório de export",
        )
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
        self.host_ollama.toggled.connect(
            lambda checked: checked and self._apply_host_defaults()
        )
        self.host_lmstudio.toggled.connect(
            lambda checked: checked and self._apply_host_defaults()
        )
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
        is_collection = source == "collection"

        self.path_contains_edit.setEnabled(is_path)
        self.tag_edit.setEnabled(is_tag)
        self.collection_edit.setEnabled(is_collection)

        self.path_contains_edit.setToolTip(
            "Filtrar apenas por caminho contendo este trecho"
            if is_path
            else "Disponível somente quando a fonte for 'path'"
        )
        self.tag_edit.setToolTip(
            "Tag existente no darktable"
            if is_tag
            else "Disponível somente quando a fonte for 'tag'"
        )
        self.collection_edit.setToolTip(
            "Coleção/pasta já presente no darktable"
            if is_collection
            else "Disponível somente quando a fonte for 'collection'"
        )

    def _update_mode_fields(self, mode: str) -> None:
        is_export = mode == "export"

        self.target_edit.setEnabled(is_export)
        self.target_button.setEnabled(is_export)

        tooltip = (
            "Necessário apenas para export"
            if is_export
            else "Habilite ao selecionar modo export"
        )
        self.target_edit.setToolTip(tooltip)
        self.target_button.setToolTip(tooltip)

    # ----------------------------------------------------------- Tarefas async --

    def _run_async(self, description: str, target: Callable[[], None]) -> None:
        if self._current_thread and self._current_thread.is_alive():
            QMessageBox.warning(
                self,
                "Execução em andamento",
                "Aguarde a finalização da tarefa atual.",
            )
            return

        self.status_signal.emit(description)
        self.progress_signal.emit(True)

        self._current_thread = threading.Thread(
            target=self._wrap_task,
            args=(target,),
            daemon=True,
        )
        self._current_thread.start()

    def _wrap_task(self, target: Callable[[], None]) -> None:
        try:
            target()
        except Exception as exc:  # noqa: BLE001
            self._append_log(f"[erro] {exc}")
            self.error_signal.emit(str(exc))
        finally:
            self.progress_signal.emit(False)

    def _append_log(self, text: str) -> None:
        self.log_signal.emit(text)

    @Slot(str)
    def _append_log_ui(self, text: str) -> None:
        self.log_text.append(text)
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )

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

    # ------------------------------------------------------------ Conectividade --

    def check_connectivity(self) -> None:
        def task() -> None:
            host = self._selected_host()
            url = self.url_edit.text().strip() or (
                OLLAMA_URL if host == "ollama" else LMSTUDIO_URL
            )

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
        return (
            f"Ollama OK ({count} modelos disponíveis)"
            if count
            else "Ollama OK (nenhum modelo listado)"
        )

    def _check_lmstudio(self, url: str) -> str:
        base = _base_url(url)
        resp = requests.get(f"{base}/v1/models", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        models = data.get("data", [])
        count = len(models)
        return (
            f"LM Studio OK ({count} modelos disponíveis)"
            if count
            else "LM Studio OK (nenhum modelo listado)"
        )

    # --------------------------------------------------------------- Modelos ----

    def list_models(self) -> None:
        def task() -> None:
            host = self._selected_host()
            url = self.url_edit.text().strip() or (
                OLLAMA_URL if host == "ollama" else LMSTUDIO_URL
            )

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
        return [
            m.get("name", "")
            for m in data.get("models", [])
            if m.get("name")
        ]

    def _list_lmstudio_models(self, url: str) -> List[str]:
        base = _base_url(url)
        resp = requests.get(f"{base}/v1/models", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        return [
            m.get("id", "")
            for m in data.get("data", [])
            if m.get("id")
        ]

    # -------------------------------------------------------------- Execução ----

    def run_host(self) -> None:
        try:
            config = self._build_config()
        except ValueError as exc:
            QMessageBox.critical(self, "Parâmetros inválidos", str(exc))
            return

        def task() -> None:
            cmd = config.build_command()
            self._append_log("Executando: " + " ".join(cmd))

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
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
        collection = self.collection_edit.text().strip() or None

        prompt_file_input = self.prompt_edit.text().strip() or None
        prompt_file = Path(prompt_file_input).expanduser() if prompt_file_input else None

        target_dir = self.target_edit.text().strip() or None

        if source == "path" and not path_contains:
            raise ValueError("'Path contains' é obrigatório quando a fonte é 'path'.")
        if source == "tag" and not tag:
            raise ValueError("Tag é obrigatória quando a fonte é 'tag'.")
        if source == "collection" and not collection:
            raise ValueError("Coleção é obrigatória quando a fonte é 'collection'.")
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
            collection=collection,
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

    # ---------------------------------------------------------- Utilidades -----

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
