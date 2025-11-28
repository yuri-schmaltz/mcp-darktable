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
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QFormLayout,
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
    models_signal = Signal(list)

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("Darktable MCP")
        self.resize(1280, 880)
        self.setMinimumSize(940, 680)
        self._apply_window_icon()
        self._current_thread: Optional[threading.Thread] = None

        self.log_signal.connect(self._append_log_ui)
        self.status_signal.connect(self._set_status_ui)
        self.progress_signal.connect(self._toggle_progress)
        self.error_signal.connect(self._show_error)
        self.models_signal.connect(self._populate_model_choices)

        self._apply_global_style()
        self._build_layout()
        self._apply_defaults()
        self._connect_dynamic_behaviors()

    # ----------------------------- UI --------------------------------------------

    def _apply_window_icon(self) -> None:
        """Define o ícone da janela e da aplicação (barra de título e tarefas)."""

        icon_path = Path(__file__).parent / "assets" / "darktable_like_icon.svg"
        if not icon_path.exists():
            return

        icon = QIcon(str(icon_path))
        QApplication.setWindowIcon(icon)
        self.setWindowIcon(icon)

    def _apply_global_style(self) -> None:
        """Tema dark consistente e componentes padronizados."""
        self.setStyleSheet(
            """
            /* BASE ----------------------------------------------------- */
            QWidget {
                font-size: 13px;
                color: #f2f2f2;
            }

            QMainWindow {
                background-color: #262626;
            }

            QLabel {
                color: #f2f2f2;
                background-color: transparent;
            }

            QToolTip {
                background-color: #3a3a3a;
                color: #f2f2f2;
                border: 1px solid #555555;
                padding: 4px 6px;
            }

            /* GROUPBOXES ---------------------------------------------- */
            QGroupBox {
                font-weight: 600;
                margin-top: 16px;
                border: 1px solid #444444;
                border-radius: 8px;
                padding: 10px 10px 12px 10px;
                background-color: #303030;
            }

            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                background-color: transparent;
            }

            /* CAMPOS DE TEXTO / INPUTS -------------------------------- */
            QLineEdit,
            QComboBox,
            QSpinBox,
            QTextEdit {
                padding: 4.5px 6px;
                min-height: 30px;
                border: 1px solid #555555;
                border-radius: 4px;
                background-color: #363636;
                selection-background-color: #77a0ff;
                selection-color: #ffffff;
            }

            QLineEdit:focus,
            QComboBox:focus,
            QSpinBox:focus,
            QTextEdit:focus {
                border-color: #77a0ff;
            }

            QLineEdit:disabled,
            QComboBox:disabled,
            QSpinBox:disabled {
                background-color: #2c2c2c;
                color: #888888;
                border-color: #3a3a3a;
            }

            QTextEdit {
                min-height: 150px;
                font-family: "JetBrains Mono", "Fira Code", monospace;
            }

            /* BOTÕES --------------------------------------------------- */
            QPushButton {
                padding: 6px 14px;
                min-height: 30px;
                background-color: #3b3b3b;
                border: 1px solid #555555;
                border-radius: 6px;
                color: #f0f0f0;
            }

            QPushButton:hover {
                background-color: #4a4a4a;
            }

            QPushButton:pressed {
                background-color: #333333;
            }

            QPushButton:disabled {
                background-color: #2a2a2a;
                color: #777777;
                border-color: #333333;
            }

            /* BOTÃO PRINCIPAL ----------------------------------------- */
            QPushButton#primaryButton {
                background-color: #336dff;
                border-color: #4e82ff;
                font-weight: 600;
            }

            QPushButton#primaryButton:hover {
                background-color: #3f7dff;
            }

            QPushButton#primaryButton:pressed {
                background-color: #295fdb;
            }

            QPushButton#primaryButton:disabled {
                background-color: #2a2a2a;
                border-color: #333333;
                color: #777777;
                font-weight: 500;
            }

            /* CHECKBOX / RADIO ---------------------------------------- */
            QCheckBox,
            QRadioButton {
                spacing: 24px;
                min-height: 25px;
            }

            /* STATUSBAR / PROGRESS ------------------------------------ */
            QStatusBar {
                background-color: #262626;
                border-top: 1px solid #3a3a3a;
            }

            QProgressBar {
                border: 1px solid #555555;
                border-radius: 4px;
                background-color: #333333;
                color: #e8e8e8;
                font-weight: 600;
                text-align: center;
                min-height: 30px;
            }

            QProgressBar::chunk {
                border-radius: 3px;
                background-color: #77a0ff;
            }
            """
        )

    def _build_layout(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(16)

        content_layout = QHBoxLayout()
        content_layout.setSpacing(16)

        form_column = QVBoxLayout()
        form_column.setSpacing(14)

    # -------------------------- Grupo: Configuração -------------------------
        
        config_group = QGroupBox("Configurações")
        config_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        config_layout = QVBoxLayout(config_group)
        config_layout.setContentsMargins(18, 14, 18, 14)
        config_layout.setSpacing(16)

        config_form = QFormLayout()
        config_form.setContentsMargins(0, 0, 0, 0)
        config_form.setHorizontalSpacing(16)
        config_form.setVerticalSpacing(12)
        config_form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        config_form.setFormAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["export", "rating", "tagging", "tratamento"])
        self.mode_combo.setToolTip(
            "Define o tipo de operação: atribuir notas, sugerir tags, exportar ou tratamento"
        )

        self.source_combo = QComboBox()
        self.source_combo.addItems(["all", "collection", "path", "tag", ])
        self.source_combo.setToolTip(
            "Escolhe de onde as imagens serão obtidas: todas, por caminho, por tag ou coleção"
        )

        self.min_rating_spin = QSpinBox()
        self.min_rating_spin.setRange(-2, 5)
        self.min_rating_spin.setValue(DEFAULT_MIN_RATING)
        self.min_rating_spin.setToolTip(
            "Nota mínima das imagens que serão consideradas (de -2 a 5)"
        )

        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 2000)
        self.limit_spin.setValue(DEFAULT_LIMIT)
        self.limit_spin.setToolTip(
            "Quantidade máxima de imagens processadas nesta execução"
        )

        config_form.addRow("Modo:", self.mode_combo)
        config_form.addRow("Fonte:", self.source_combo)
        config_form.addRow("Rating mínimo:", self.min_rating_spin)
        config_form.addRow("Limite:", self.limit_spin)

    # -------------------------- Seção: Filtros e opções ---------------------

        self.path_contains_edit = QLineEdit()
        self.tag_edit = QLineEdit()
        self.collection_edit = QLineEdit()
        self.prompt_edit = QLineEdit()
        self.target_edit = QLineEdit()

        self.prompt_edit.setToolTip(
            "Arquivo Markdown opcional com instruções adicionais para o modelo"
        )
        self.target_edit.setToolTip("Diretório onde as exportações serão salvas")

        for w in (
            self.path_contains_edit,
            self.tag_edit,
            self.collection_edit,
            self.prompt_edit,
            self.target_edit,
        ):
            self._style_form_field(w)

        config_form.addRow("Path contém:", self.path_contains_edit)
        config_form.addRow("Tag:", self.tag_edit)
        config_form.addRow("Coleção:", self.collection_edit)

        # Prompt custom + botões
        prompt_row_widget = QWidget()
        prompt_row_layout = QHBoxLayout(prompt_row_widget)
        prompt_row_layout.setContentsMargins(0, 0, 0, 0)
        prompt_row_layout.setSpacing(12)
        prompt_row_layout.addWidget(self.prompt_edit, stretch=1)

        self.prompt_button = QPushButton("Selecionar")
        self._standardize_button(self.prompt_button)
        self.prompt_button.clicked.connect(self._choose_prompt_file)
        prompt_row_layout.addWidget(self.prompt_button)

        self.prompt_generate_button = QPushButton("Gerar modelo")
        self._standardize_button(self.prompt_generate_button)
        self.prompt_generate_button.clicked.connect(self._generate_prompt_template)
        prompt_row_layout.addWidget(self.prompt_generate_button)

        prompt_row_layout.addStretch()

        config_form.addRow("Prompt personalizado:", prompt_row_widget)

        # Dir export + botão
        target_row_widget = QWidget()
        target_row_layout = QHBoxLayout(target_row_widget)
        target_row_layout.setContentsMargins(0, 0, 0, 0)
        target_row_layout.setSpacing(12)
        target_row_layout.addWidget(self.target_edit, stretch=1)

        self.target_button = QPushButton("Selecionar")
        self._standardize_button(self.target_button)
        self.target_button.clicked.connect(self._choose_target_dir)
        self.target_button.setToolTip(
            "Seleciona a pasta onde os arquivos exportados serão gravados"
        )
        target_row_layout.addWidget(self.target_button)
        target_row_layout.addStretch()

        config_form.addRow("Pasta para exportação:", target_row_widget)

        # Checkboxes (Apenas RAW / Dry-run)
        flags_widget = QWidget()
        flags_layout = QHBoxLayout(flags_widget)
        # mesmas margens dos outros rows (prompt/dir export)
        flags_layout.setContentsMargins(0, 0, 0, 0)
        flags_layout.setSpacing(16)

        self.only_raw_check = QCheckBox("Apenas RAW")
        self.dry_run_check = QCheckBox("Dry-run")
        self.dry_run_check.setChecked(True)
        self.only_raw_check.setToolTip(
            "Processa somente arquivos RAW (ignora JPEGs e derivados)"
        )
        self.dry_run_check.setToolTip(
            "Simula a execução sem escrever arquivos ou alterar metadados"
        )

        flags_layout.addWidget(self.only_raw_check)
        flags_layout.addWidget(self.dry_run_check)
        flags_layout.addStretch()

        config_form.addRow("Execução:", flags_widget)

        config_layout.addLayout(config_form)

    # ------------------------------- Seção LLM ------------------------------
        
        llm_group = QWidget()

        llm_layout = QVBoxLayout(llm_group)
        llm_layout.setContentsMargins(0, 0, 0, 0)
        llm_layout.setSpacing(12)

        self.host_group = QButtonGroup(self)
        self.host_ollama = QRadioButton("Ollama")
        self.host_ollama.setChecked(True)
        self.host_lmstudio = QRadioButton("LM Studio")
        self.host_group.addButton(self.host_ollama)
        self.host_group.addButton(self.host_lmstudio)
        self.host_ollama.setToolTip("Usa um servidor Ollama para executar o modelo")
        self.host_lmstudio.setToolTip(
            "Usa um servidor LM Studio para executar o modelo"
        )

        host_widget = QWidget()
        host_layout = QHBoxLayout(host_widget)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(18)
        host_layout.addWidget(self.host_ollama)
        host_layout.addWidget(self.host_lmstudio)
        host_layout.addStretch()

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.url_edit = QLineEdit()
        self.url_edit.setToolTip("URL base do servidor LLM escolhido")
        self.model_combo.setToolTip("Nome do modelo carregado no servidor selecionado")

        self._style_form_field(self.url_edit)
        self._style_form_field(self.model_combo)

        actions_widget = QWidget()
        actions_layout = QHBoxLayout(actions_widget)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(12)
        actions_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        list_button = QPushButton()
        list_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogListView)
        )
        list_button.setToolTip("Listar modelos")
        list_button.setFixedSize(40, 32)
        list_button.clicked.connect(self.list_models)

        check_button = QPushButton()
        check_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
        )
        check_button.setToolTip("Verificar conectividade")
        check_button.setFixedSize(40, 32)
        check_button.clicked.connect(self.check_connectivity)

        actions_layout.addWidget(list_button)
        actions_layout.addWidget(check_button)

        model_row_widget = QWidget()
        model_row_layout = QHBoxLayout(model_row_widget)
        model_row_layout.setContentsMargins(0, 0, 0, 0)
        model_row_layout.setSpacing(12)
        model_row_layout.addWidget(self.model_combo, stretch=1)
        model_row_layout.addWidget(actions_widget)
        model_row_layout.setAlignment(actions_widget, Qt.AlignmentFlag.AlignVCenter)

        llm_form = QFormLayout()
        llm_form.setContentsMargins(0, 0, 0, 0)
        llm_form.setHorizontalSpacing(14)
        llm_form.setVerticalSpacing(10)
        llm_form.setFormAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        llm_form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        llm_form.addRow("Framework:", host_widget)
        llm_form.addRow("URL:", self.url_edit)
        llm_form.addRow("Modelo:", model_row_widget)

        self._sync_form_label_widths(config_form, llm_form)

        llm_layout.addLayout(llm_form)

        config_layout.addWidget(llm_group)

        form_column.addWidget(config_group, stretch=1)

    # ------------------------------------ Log -------------------------------
        
        log_group = QGroupBox("Log")
        log_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(18, 12, 18, 12)
        log_layout.setSpacing(12)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.log_text.setMinimumHeight(120)
        self.log_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.log_text.setToolTip("Logs e progresso serão exibidos aqui...")

        clear_log = QPushButton("Limpar log")
        self._standardize_button(clear_log)
        clear_log.setToolTip("Remove o conteúdo exibido acima")
        clear_log.clicked.connect(self.log_text.clear)

        log_layout.addWidget(self.log_text)
        log_layout.addWidget(clear_log, alignment=Qt.AlignmentFlag.AlignRight)

        right_column = QVBoxLayout()
        right_column.setSpacing(14)
        right_column.addWidget(log_group, stretch=1)

    # ----------------------------- Botão principal --------------------------
        
        self.run_button = QPushButton("Executar host")
        # marcar como botão principal para o stylesheet
        self.run_button.setObjectName("primaryButton")
        # ícone de "play"
        self.run_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        )

        # botão ocupa toda a largura disponível na coluna da direita
        self.run_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.run_button.setMinimumWidth(0)

        self.run_button.setToolTip("Inicia o host com os parâmetros configurados")
        self.run_button.clicked.connect(self.run_host)

        run_row = QHBoxLayout()
        run_row.setContentsMargins(0, 6, 0, 0)
        run_row.setSpacing(12)
        # sem addStretch(): o botão pega toda a linha
        run_row.addWidget(self.run_button)

        right_column.addLayout(run_row)

        content_layout.addLayout(form_column, stretch=2)
        content_layout.addLayout(right_column, stretch=3)

        main_layout.addLayout(content_layout)

        self._build_status_bar()

    # ----------------------------- Barra de Status --------------------------
        
    def _build_status_bar(self) -> None:
        status_bar = QStatusBar()
        status_bar.setSizeGripEnabled(False)
        status_bar.setContentsMargins(0, 0, 0, 0)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress.setFormat("Pronto para configurar a execução.")
        self.progress.setFixedHeight(30)
        self.progress.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        status_bar.addPermanentWidget(self.progress, 1)
        self.setStatusBar(status_bar)

    def _standardize_button(self, button: QPushButton) -> None:
        button.setMinimumWidth(130)
        button.setMinimumHeight(32)
        button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def _section_title(self, text: str) -> QLabel:
        title = QLabel(text)
        title.setStyleSheet("font-weight: 600; margin-top: 4px; margin-bottom: 2px;")
        title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return title

    def _style_form_field(self, widget: QWidget) -> None:
        """Padroniza campos de formulário para largura e altura consistentes."""

        widget.setMinimumWidth(260)
        widget.setMinimumHeight(32)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def _sync_form_label_widths(self, *forms: QFormLayout) -> None:
        """Mantém colunas de rótulos alinhadas entre múltiplos formulários."""

        max_width = 0
        labels = []

        for form in forms:
            for row in range(form.rowCount()):
                label_item = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
                label_widget = label_item.widget() if label_item else None
                if label_widget:
                    labels.append(label_widget)
                    max_width = max(max_width, label_widget.sizeHint().width())

        for label in labels:
            label.setMinimumWidth(max_width)
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    # ----------------------------- Padrões -------------------------------------

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
        if model_line := self.model_combo.lineEdit():
            model_line.setPlaceholderText("Nome do modelo disponível no host")
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

        current_model = self.model_combo.currentText().strip()
        current_url = self.url_edit.text().strip()

        if not current_model or current_model in {OLLAMA_MODEL, LMSTUDIO_MODEL}:
            self.model_combo.setEditText(model_default)
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

    # ----------------------------- Tarefas Assíncronas -------------------------------------

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
        self.progress.setFormat(text)

    @Slot(bool)
    def _toggle_progress(self, running: bool) -> None:
        if running:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 1)
            self.progress.setValue(0)
            self.progress.setFormat("Pronto.")

    @Slot(str)
    def _show_error(self, message: str) -> None:
        QMessageBox.critical(self, "Erro", message)

    # ----------------------------- Conectividade --------------------------------------

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

    # ----------------------------- Modelos -----------------------------------------

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

            self.models_signal.emit(names)

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

    @Slot(list)
    def _populate_model_choices(self, names: List[str]) -> None:
        current_text = self.model_combo.currentText().strip()

        self.model_combo.blockSignals(True)
        self.model_combo.clear()

        unique_names = sorted(dict.fromkeys(names))
        if unique_names:
            self.model_combo.addItems(unique_names)

        if current_text:
            self.model_combo.setEditText(current_text)
        self.model_combo.blockSignals(False)

    # ----------------------------- Execução -------------------------------------------------

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
            model=self.model_combo.currentText().strip() or model_default,
            llm_url=self.url_edit.text().strip() or url_default,
            target_dir=target_dir,
            prompt_file=prompt_file,
            extra_flags=[],
        )

    # ----------------------------- Utilidades -------------------------------------------

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
