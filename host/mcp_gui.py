#!/usr/bin/env python3
"""GUI para orquestrar os hosts MCP (Ollama ou LM Studio).

A interface reúne em uma única janela todos os parâmetros necessários
para executar os hosts mostrando o progresso das atividades.
"""
from __future__ import annotations

import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

import requests

from PySide6.QtCore import Qt, Signal, Slot, QSize
from PySide6.QtGui import QIcon, QPixmap, QResizeEvent, QShortcut, QKeySequence
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
    QStyle,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QSpinBox,
)

from common import probe_darktable_state
from interactive_cli import DEFAULT_LIMIT, DEFAULT_MIN_RATING, RunConfig
from mcp_host_ollama import (
    APP_VERSION as HOST_APP_VERSION,
    OLLAMA_MODEL,
    OLLAMA_URL,
    PROTOCOL_VERSION as MCP_PROTOCOL_VERSION,
    load_prompt as load_ollama_prompt,
)
from mcp_host_lmstudio import LMSTUDIO_MODEL, LMSTUDIO_URL

GUI_CLIENT_INFO = {"name": "darktable-mcp-gui", "version": HOST_APP_VERSION}


class MCPGui(QMainWindow):
    log_signal = Signal(str)
    status_signal = Signal(str)
    progress_signal = Signal(bool)
    error_signal = Signal(str)
    models_signal = Signal(list)
    collections_signal = Signal(list)
    progress_update_signal = Signal(int, int, str)  # (current, total, message)

    def __init__(
        self,
        mcp_client_factory=None,
        llm_provider_factory=None,
    ) -> None:
        super().__init__()

        self.setWindowTitle("Darktable MCP")
        self.resize(1280, 880)
        self.setMinimumSize(940, 680)
        self._apply_window_icon()
        self._current_thread: Optional[threading.Thread] = None
        self._stop_requested = False
        self._current_image_path: Optional[Path] = None
        self._current_pixmap: Optional[QPixmap] = None
        self._image_path_pattern = re.compile(
            r"([A-Za-z]:\\[^\n]+?\.(?:jpe?g|png|tiff?|bmp|webp)|/[^\n]+?\.(?:jpe?g|png|tiff?|bmp|webp))",
            re.IGNORECASE,
        )

        # Fábricas para injeção de dependências (testes/mocks)
        from common import McpClient, DT_SERVER_CMD
        from mcp_host_ollama import OLLAMA_MODEL, OLLAMA_URL, PROTOCOL_VERSION as MCP_PROTOCOL_VERSION
        self._mcp_client_factory = mcp_client_factory or (
            lambda: McpClient(
                DT_SERVER_CMD,
                MCP_PROTOCOL_VERSION,
                GUI_CLIENT_INFO,
            )
        )
        # LLMProvider será injetado em patch posterior
        self._llm_provider_factory = llm_provider_factory

        self.log_signal.connect(self._append_log_ui)
        self.status_signal.connect(self._set_status_ui)
        self.progress_signal.connect(self._toggle_progress)
        self.error_signal.connect(self._show_error)
        self.models_signal.connect(self._update_model_options)
        self.collections_signal.connect(self._populate_collections)
        self.progress_update_signal.connect(self._update_progress)

        self._apply_global_style()
        self._build_menu_bar()
        self._build_layout()
        self._apply_defaults()
        self._connect_dynamic_behaviors()
        self._setup_keyboard_shortcuts()
        self._setup_tab_order()

    # ----------------------------- UI --------------------------------------------

    def _apply_window_icon(self) -> None:
        """Define o ícone da janela e da aplicação (barra de título e tarefas)."""

        icon_path = Path(__file__).parent / "assets" / "darktable_like_icon.svg"
        if not icon_path.exists():
            return

        icon = QIcon(str(icon_path))
        QApplication.setWindowIcon(icon)
        self.setWindowIcon(icon)

    def _build_menu_bar(self) -> None:
        """Cria a barra de menus com opções futuras."""
        from PySide6.QtGui import QAction
        
        menubar = self.menuBar()
        
        # Menu Arquivo
        file_menu = menubar.addMenu("&Arquivo")
        
        open_config_action = QAction("&Abrir Configuração...", self)
        open_config_action.setShortcut("Ctrl+O")
        open_config_action.setEnabled(False)  # Placeholder
        file_menu.addAction(open_config_action)
        
        save_config_action = QAction("&Salvar Configuração...", self)
        save_config_action.setShortcut("Ctrl+S")
        save_config_action.setEnabled(False)  # Placeholder
        file_menu.addAction(save_config_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("&Sair", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Menu Editar
        edit_menu = menubar.addMenu("&Editar")
        
        preferences_action = QAction("&Preferências...", self)
        preferences_action.setShortcut("Ctrl+,")
        preferences_action.setEnabled(False)  # Placeholder
        edit_menu.addAction(preferences_action)
        
        # Menu Ferramentas
        tools_menu = menubar.addMenu("Ferramen&tas")
        
        check_dt_action = QAction("Verificar &Darktable", self)
        check_dt_action.triggered.connect(self._probe_darktable_connection)
        tools_menu.addAction(check_dt_action)
        
        check_llm_action = QAction("Verificar &LLM", self)
        check_llm_action.triggered.connect(self._check_connection_and_fetch_models)
        tools_menu.addAction(check_llm_action)
        
        tools_menu.addSeparator()
        
        clear_logs_action = QAction("Limpar &Logs", self)
        clear_logs_action.triggered.connect(lambda: self.log_text.clear())
        tools_menu.addAction(clear_logs_action)
        
        # Menu Ajuda  
        help_menu = menubar.addMenu("Aj&uda")
        
        docs_action = QAction("&Documentação", self)
        docs_action.setEnabled(False)  # Placeholder
        help_menu.addAction(docs_action)
        
        about_action = QAction("&Sobre", self)
        about_action.setEnabled(False)  # Placeholder
        help_menu.addAction(about_action)


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
                color: #999999;
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

            /* BOTÃO DE PARAR ------------------------------------------ */
            QPushButton#stopButton {
                background-color: #cc3333;
                border-color: #ff4444;
                font-weight: 600;
                min-width: 50px;
            }

            QPushButton#stopButton:hover {
                background-color: #dd4444;
            }

            QPushButton#stopButton:pressed {
                background-color: #bb2222;
            }

            QPushButton#stopButton:disabled {
                background-color: #2a2a2a;
                border-color: #333333;
                color: #777777;
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

            /* PREVIEW DE IMAGEM ------------------------------------ */
            QLabel#imagePreview {
                background-color: #3b2a1c;
                border: 2px solid #2da86f;
                border-radius: 10px;
                color: #d9d9d9;
                padding: 10px;
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

        # -------------------------- Campos principais ---------------------------

        # -------------------------- Campos principais ---------------------------

        # Modo de operação (Radio Buttons)
        self.mode_group = QButtonGroup(self)
        self.mode_rating = QRadioButton("Rating")
        self.mode_tagging = QRadioButton("Tagging")
        self.mode_export = QRadioButton("Export")
        self.mode_treatment = QRadioButton("Tratamento")
        self.mode_completo = QRadioButton("Completo")

        # Configura tooltips
        self.mode_rating.setToolTip("Atribuir notas às imagens.")
        self.mode_tagging.setToolTip("Sugerir e aplicar tags.")
        self.mode_export.setToolTip("Exportar imagens selecionadas.")
        self.mode_treatment.setToolTip("Aplicar tratamento de imagem.")
        self.mode_completo.setToolTip("Fluxo completo: Rating -> Tagging -> Tratamento -> Export.")

        # Adiciona ao grupo (para exclusão mútua)
        self.mode_group.addButton(self.mode_rating)
        self.mode_group.addButton(self.mode_tagging)
        self.mode_group.addButton(self.mode_export)
        self.mode_group.addButton(self.mode_treatment)
        self.mode_group.addButton(self.mode_completo)

        # Layout horizontal para os modos
        mode_widget = QWidget()
        mode_layout = QHBoxLayout(mode_widget)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(12)
        mode_layout.addWidget(self.mode_rating)
        mode_layout.addWidget(self.mode_tagging)
        mode_layout.addWidget(self.mode_export)
        mode_layout.addWidget(self.mode_treatment)
        mode_layout.addWidget(self.mode_completo)
        mode_layout.addStretch()

        # Define padrão
        self.mode_rating.setChecked(True)

        self.source_combo = QComboBox()
        self.source_combo.addItems(["all", "collection", "path", "tag"])
        self.source_combo.setToolTip(
            "Escolhe de onde as imagens serão obtidas: todas, por caminho, por tag ou coleção."
        )
        self.source_combo.setAccessibleName("Fonte das imagens")
        self.source_combo.setAccessibleDescription(
            "Escolher de onde as imagens serão obtidas: todas, por coleção, por caminho ou por tag"
        )

        self.min_rating_spin = QSpinBox()
        self.min_rating_spin.setRange(-2, 5)
        self.min_rating_spin.setValue(DEFAULT_MIN_RATING)
        self.min_rating_spin.setToolTip(
            "Nota mínima das imagens que serão consideradas (de -2 a 5)."
        )
        self.min_rating_spin.setAccessibleName("Rating mínimo")
        self.min_rating_spin.setAccessibleDescription(
            "Nota mínima das imagens a processar, de menos 2 a 5"
        )

        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 100000)
        self.limit_spin.setValue(DEFAULT_LIMIT)
        self.limit_spin.setToolTip(
            "Quantidade máxima de imagens processadas nesta execução."
        )
        self.limit_spin.setAccessibleName("Limite de imagens")
        self.limit_spin.setAccessibleDescription(
            "Número máximo de imagens a processar nesta execução"
        )

        config_form.addRow("Modo:", mode_widget)
        config_form.addRow("Fonte:", self.source_combo)
        config_form.addRow("Rating mínimo:", self.min_rating_spin)
        config_form.addRow("Limite:", self.limit_spin)

        # Timeout para LLM
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(10, 600)
        self.timeout_spin.setValue(60)
        self.timeout_spin.setSuffix(" s")
        self.timeout_spin.setToolTip(
            "Tempo máximo de espera pela resposta do modelo LLM (10-600 segundos)."
        )
        self.timeout_spin.setAccessibleName("Timeout do modelo")
        self.timeout_spin.setAccessibleDescription(
            "Tempo máximo de espera pela resposta do modelo LLM em segundos"
        )
        self._style_form_field(self.timeout_spin)
        config_form.addRow("Timeout do modelo:", self.timeout_spin)

        # -------------------------- Filtros e opções ---------------------------

        self.path_contains_edit = QLineEdit()
        self.path_contains_edit.setAccessibleName("Filtro de caminho")
        self.path_contains_edit.setAccessibleDescription(
            "Filtrar imagens por trecho do caminho de arquivo"
        )
        
        self.tag_edit = QLineEdit()
        self.tag_edit.setAccessibleName("Tag do Darktable")
        self.tag_edit.setAccessibleDescription("Tag existente para filtrar imagens")
        
        self.collection_combo = QComboBox()
        self.collection_combo.setEditable(True)
        self.collection_combo.setAccessibleName("Coleção do Darktable")
        self.collection_combo.setAccessibleDescription(
            "Selecione a coleção (filme) de onde as imagens serão obtidas"
        )
        
        self.prompt_edit = QLineEdit()
        self.prompt_edit.setAccessibleName("Arquivo de prompt personalizado")
        self.prompt_edit.setAccessibleDescription(
            "Caminho para arquivo Markdown com instruções customizadas ao modelo"
        )
        
        self.target_edit = QLineEdit()
        self.target_edit.setAccessibleName("Diretório de exportação")
        self.target_edit.setAccessibleDescription(
            "Pasta onde os arquivos exportados serão salvos"
        )

        self.prompt_edit.setToolTip(
            "Arquivo Markdown opcional com instruções adicionais para o modelo."
        )
        self.target_edit.setToolTip("Diretório onde as exportações serão salvas.")

        self.collection_combo.setToolTip(
            "Selecione ou digite o caminho da coleção do Darktable."
        )

        for w in (
            self.path_contains_edit,
            self.tag_edit,
            self.collection_combo,
            self.prompt_edit,
            self.target_edit,
        ):
            self._style_form_field(w)
        
        # Extra width for path fields to show full paths
        self.prompt_edit.setMinimumWidth(400)
        self.target_edit.setMinimumWidth(400)

        config_form.addRow("Path contém:", self.path_contains_edit)
        config_form.addRow("Tag:", self.tag_edit)

        self.darktable_probe_button = QPushButton()
        self.darktable_probe_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
        )
        self.darktable_probe_button.setIconSize(QSize(18, 18))
        self.darktable_probe_button.setToolTip(
            "Testa a conexão com o darktable, lista coleções e mostra uma amostra das fotos encontradas."
        )
        self.darktable_probe_button.clicked.connect(self._probe_darktable_connection)
        self._standardize_button(self.darktable_probe_button, width=42)
        
        # Refresh collections button
        self.refresh_collections_button = QPushButton()
        self.refresh_collections_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        self.refresh_collections_button.setIconSize(QSize(18, 18))
        self.refresh_collections_button.setToolTip("Atualizar lista de coleções")
        self.refresh_collections_button.clicked.connect(lambda: self._fetch_and_populate_collections(force_refresh=True))
        self._standardize_button(self.refresh_collections_button, width=42)

        collection_row_widget = QWidget()
        collection_row_layout = QHBoxLayout(collection_row_widget)
        collection_row_layout.setContentsMargins(0, 0, 0, 0)
        collection_row_layout.setSpacing(10)
        collection_row_layout.addWidget(self.collection_combo, stretch=1)
        collection_row_layout.addStretch()
        collection_row_layout.addWidget(self.refresh_collections_button)
        collection_row_layout.addWidget(self.darktable_probe_button)

        config_form.addRow("Coleção:", collection_row_widget)

        # Prompt custom + botões
        prompt_row_widget = QWidget()
        prompt_row_layout = QHBoxLayout(prompt_row_widget)
        prompt_row_layout.setContentsMargins(0, 0, 0, 0)
        prompt_row_layout.setSpacing(12)
        prompt_row_layout.addWidget(self.prompt_edit, stretch=1)

        self.prompt_button = QPushButton()
        self.prompt_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton)
        )
        self.prompt_button.setIconSize(QSize(18, 18))
        self._standardize_button(self.prompt_button, width=42)
        self.prompt_button.clicked.connect(self._choose_prompt_file)
        self.prompt_button.setToolTip("Seleciona um arquivo de prompt em Markdown.")
        prompt_row_layout.addWidget(self.prompt_button)

        self.prompt_generate_button = QPushButton()
        self.prompt_generate_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder)
        )
        self.prompt_generate_button.setIconSize(QSize(18, 18))
        self._standardize_button(self.prompt_generate_button, width=42)
        self.prompt_generate_button.clicked.connect(self._generate_prompt_template)
        self.prompt_generate_button.setToolTip("Gera um modelo de prompt padrão.")
        prompt_row_layout.addWidget(self.prompt_generate_button)

        prompt_row_layout.addStretch()
        config_form.addRow("Prompt personalizado:", prompt_row_widget)

        # Dir export + botão
        target_row_widget = QWidget()
        target_row_layout = QHBoxLayout(target_row_widget)
        target_row_layout.setContentsMargins(0, 0, 0, 0)
        target_row_layout.setSpacing(12)
        target_row_layout.addWidget(self.target_edit, stretch=1)

        self.target_button = QPushButton()
        self.target_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        )
        self.target_button.setIconSize(QSize(18, 18))
        self._standardize_button(self.target_button, width=42)
        self.target_button.clicked.connect(self._choose_target_dir)
        self.target_button.setToolTip(
            "Seleciona a pasta onde os arquivos exportados serão gravados."
        )
        target_row_layout.addWidget(self.target_button)
        target_row_layout.addStretch()

        config_form.addRow("Pasta para exportação:", target_row_widget)

        # Checkboxes (Apenas RAW / Dry-run / Imagens)
        flags_widget = QWidget()
        flags_layout = QHBoxLayout(flags_widget)
        flags_layout.setContentsMargins(0, 0, 0, 0)
        flags_layout.setSpacing(16)

        self.only_raw_check = QCheckBox("Apenas RAW")
        self.only_raw_check.setAccessibleName("Apenas arquivos RAW")
        self.only_raw_check.setAccessibleDescription(
            "Processar somente arquivos RAW, ignorando JPEG e derivados"
        )
        
        self.dry_run_check = QCheckBox("Dry-run")
        self.dry_run_check.setChecked(True)
        self.dry_run_check.setAccessibleName("Modo dry-run")
        self.dry_run_check.setAccessibleDescription(
            "Simular execução sem alterar arquivos ou metadados"
        )
        
        self.attach_images_check = QCheckBox("Enviar imagens ao modelo (multimodal)")
        self.attach_images_check.setChecked(True)
        self.attach_images_check.setAccessibleName("Enviar imagens ao modelo")
        self.attach_images_check.setAccessibleDescription(
            "Anexar arquivos de imagem junto aos metadados para modelos multimodais"
        )
        
        self.generate_styles_check = QCheckBox("Gerar estilos")
        self.generate_styles_check.setChecked(True)
        self.generate_styles_check.setAccessibleName("Gerar estilos automaticamente")
        self.generate_styles_check.setAccessibleDescription(
            "Gerar arquivos de estilo XMP para Darktable"
        )

        self.only_raw_check.setToolTip(
            "Processa somente arquivos RAW (ignora JPEGs e derivados)."
        )
        self.dry_run_check.setToolTip(
            "Simula a execução sem escrever arquivos ou alterar metadados."
        )
        self.attach_images_check.setToolTip(
            "Quando desmarcado, o host enviará apenas metadados e texto ao modelo, sem anexar arquivos de imagem."
        )
        self.generate_styles_check.setToolTip(
            "Quando ativado, o sistema gera arquivos de estilo .xmp para Darktable."
        )

        flags_layout.addWidget(self.only_raw_check)
        flags_layout.addWidget(self.dry_run_check)
        flags_layout.addWidget(self.attach_images_check)
        flags_layout.addWidget(self.generate_styles_check)
        flags_layout.addStretch()

        config_form.addRow("Execução:", flags_widget)

        # Remove "Imagens:" row
        # config_form.addRow("Imagens:", self.attach_images_check)

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setAccessibleName("Modelo LLM")
        self.model_combo.setAccessibleDescription(
            "Nome do modelo de linguagem carregado no servidor"
        )
        
        self.url_edit = QLineEdit()
        self.url_edit.setToolTip("URL base do servidor LLM escolhido.")
        self.url_edit.setAccessibleName("URL do servidor LLM")
        self.url_edit.setAccessibleDescription("Endereço base do servidor Ollama ou LM Studio")
        
        self.model_combo.setToolTip("Nome do modelo carregado no servidor selecionado.")
        self.check_models_button = QPushButton()
        self.check_models_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        self.check_models_button.setIconSize(QSize(18, 18))
        self.check_models_button.setToolTip(
            "Verifica a conectividade com o servidor selecionado e lista modelos disponíveis."
        )
        self.check_models_button.clicked.connect(
            self._check_connection_and_fetch_models
        )

        self._style_form_field(self.url_edit)
        self._style_form_field(self.model_combo)
        self._standardize_button(self.check_models_button, width=42)

        # Nível de prompt (básico/avançado)
        self.prompt_variant_combo = QComboBox()
        self.prompt_variant_combo.addItems(["Básico", "Avançado"])
        self.prompt_variant_combo.setToolTip(
            "Define a complexidade do prompt padrão utilizado quando não há arquivo .md personalizado."
        )
        self._style_form_field(self.prompt_variant_combo)

        model_row_widget = QWidget()
        model_row_layout = QHBoxLayout(model_row_widget)
        model_row_layout.setContentsMargins(0, 0, 0, 0)
        model_row_layout.setSpacing(12)

        url_row_widget = QWidget()
        url_row_layout = QHBoxLayout(url_row_widget)
        url_row_layout.setContentsMargins(0, 0, 0, 0)
        url_row_layout.setSpacing(8)
        url_row_layout.addWidget(self.url_edit, 1)
        url_row_layout.addWidget(self.check_models_button)

        # combo ocupa o espaço, mas alinhado verticalmente ao centro
        model_row_layout.addWidget(
            self.model_combo,
            1,
            Qt.AlignmentFlag.AlignVCenter,
        )
        model_row_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # LLM na mesma coluna do restante
        # config_form.addRow("Framework:", host_widget)  -- Removed
        config_form.addRow("URL:", url_row_widget)
        config_form.addRow("Modelo:", model_row_widget)
        config_form.addRow("Nível de prompt:", self.prompt_variant_combo)

        # Ajusta largura de todos os rótulos desse formulário
        self._sync_form_label_widths(config_form)

        # Adiciona o form completo ao grupo
        config_layout.addLayout(config_form)
        form_column.addWidget(config_group, stretch=1)

        # ------------------------------------ Visualização da imagem atual -------
        current_image_group = self._build_current_image_group()

        # ------------------------------------ Log -------------------------------
        log_group = QGroupBox("Log")
        log_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        log_group.setMaximumHeight(360)

        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(18, 12, 18, 12)
        log_layout.setSpacing(12)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.log_text.setMinimumHeight(110)
        self.log_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.log_text.setToolTip("Logs e progresso serão exibidos aqui...")

        clear_log = QPushButton("Limpar log")
        self._standardize_button(clear_log)
        clear_log.setToolTip("Remove o conteúdo exibido acima.")
        clear_log.clicked.connect(self.log_text.clear)

        log_layout.addWidget(self.log_text)
        log_layout.addWidget(clear_log, alignment=Qt.AlignmentFlag.AlignRight)

        right_column = QVBoxLayout()
        right_column.setSpacing(14)
        right_column.addWidget(current_image_group, stretch=3)
        right_column.addWidget(log_group, stretch=2)

        # ----------------------------- Botão principal --------------------------
        self.run_button = QPushButton("Executar host")
        self.run_button.setObjectName("primaryButton")
        self.run_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        )
        self.run_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.run_button.setMinimumWidth(0)
        self.run_button.setToolTip("Inicia o host com os parâmetros configurados.")
        self.run_button.setAccessibleName("Executar host")
        self.run_button.setAccessibleDescription(
            "Iniciar processamento com os parâmetros configurados"
        )
        self.run_button.clicked.connect(self.run_host)

        self.stop_button = QPushButton()
        self.stop_button.setObjectName("stopButton")
        self.stop_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserStop)
        )
        self.stop_button.setIconSize(QSize(18, 18))
        self.stop_button.setToolTip("Encerrar processamento")
        self.stop_button.setAccessibleName("Parar execução")
        self.stop_button.setAccessibleDescription("Interromper o processamento em andamento")
        self.stop_button.setEnabled(False)  # Initially disabled
        self.stop_button.clicked.connect(self._stop_processing)
        self.stop_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.stop_button.setMinimumWidth(50)
        self.stop_button.setMinimumHeight(32)

        run_row = QHBoxLayout()
        run_row.setContentsMargins(0, 6, 0, 0)
        run_row.setSpacing(12)
        run_row.addWidget(self.run_button)
        run_row.addWidget(self.stop_button)

        right_column.addLayout(run_row)

        content_layout.addLayout(form_column, stretch=3)
        content_layout.addLayout(right_column, stretch=2)

        main_layout.addLayout(content_layout)

        self._reset_image_preview()
        self._build_status_bar()

    def _build_current_image_group(self) -> QGroupBox:
        group = QGroupBox("Imagem em tratamento")
        group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout = QVBoxLayout(group)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(10)

        self.image_preview = QLabel("Pré-visualização da imagem em execução")
        self.image_preview.setObjectName("imagePreview")
        self.image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_preview.setMinimumHeight(320)
        self.image_preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.image_preview.setWordWrap(True)

        layout.addWidget(self.image_preview)

        meta_layout = QVBoxLayout()
        meta_layout.setSpacing(4)

        self.image_title_label = QLabel("Nenhuma imagem em tratamento")
        self.image_title_label.setStyleSheet("font-weight: 600;")
        self.image_title_label.setWordWrap(True)

        self.image_path_label = QLabel("Inicie a execução para visualizar o arquivo atual.")
        self.image_path_label.setStyleSheet("color: #c9c9c9;")
        self.image_path_label.setWordWrap(True)

        meta_layout.addWidget(self.image_title_label)
        meta_layout.addWidget(self.image_path_label)

        layout.addLayout(meta_layout)
        return group

    # ----------------------------- Barra de Status --------------------------

    def _build_status_bar(self) -> None:
        status_bar = QStatusBar()
        status_bar.setSizeGripEnabled(False)
        status_bar.setContentsMargins(0, 0, 0, 0)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)  # Determinate mode for percentage
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress.setFormat("Pronto para configurar a execução.")
        self.progress.setFixedHeight(30)
        self.progress.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        status_bar.addPermanentWidget(self.progress, 1)
        self.setStatusBar(status_bar)

    def _reset_image_preview(self, message: str | None = None) -> None:
        self._current_image_path = None
        self._current_pixmap = None
        self.image_preview.setPixmap(QPixmap())
        self.image_preview.setText(
            message
            or "Nenhuma imagem está em tratamento no momento. Aguardando execução..."
        )
        self.image_title_label.setText("Nenhuma imagem em tratamento")
        self.image_path_label.setText("Inicie a execução para visualizar a imagem atual.")

    def _set_current_image_preview(self, path: Path) -> None:
        expanded = path.expanduser()
        self._current_image_path = expanded
        self.image_title_label.setText(expanded.name)
        self.image_path_label.setText(str(expanded))

        pixmap = QPixmap(str(expanded))
        if pixmap.isNull():
            self._current_pixmap = None
            self.image_preview.setPixmap(QPixmap())
            self.image_preview.setText("Pré-visualização indisponível para este arquivo.")
            return

        self._current_pixmap = pixmap
        self.image_preview.setText("")
        self._refresh_image_preview()

    def _refresh_image_preview(self) -> None:
        if not self._current_pixmap:
            return

        target_size = self.image_preview.size()
        if target_size.width() <= 2 or target_size.height() <= 2:
            return

        scaled = self._current_pixmap.scaled(
            target_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_preview.setPixmap(scaled)

    def _maybe_update_image_preview(self, text: str) -> None:
        if not text:
            return

        for line in text.splitlines():
            match = self._image_path_pattern.search(line)
            if not match:
                continue

            cleaned = match.group(0).strip(" ' \"")
            candidate = Path(cleaned)
            if candidate.exists():
                self._set_current_image_preview(candidate)
                return

    def _standardize_button(self, button: QPushButton, *, width: int = 130) -> None:
        button.setMinimumWidth(width)
        button.setMinimumHeight(32)
        button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def _section_title(self, text: str) -> QLabel:
        title = QLabel(text)
        title.setStyleSheet("font-weight: 600; margin-top: 4px; margin-bottom: 2px;")
        title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return title

    def _style_form_field(self, widget: QWidget) -> None:
        """Padroniza campos de formulário para largura e altura consistentes."""

        widget.setMinimumWidth(320)  # Increased from 260 to prevent cutoff
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
        mode = self._get_selected_mode()
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
        self.target_edit.setPlaceholderText("Diretório para exportação")
        if model_line := self.model_combo.lineEdit():
            model_line.setPlaceholderText("Nome do modelo disponível no host")
        self.url_edit.setPlaceholderText("http://localhost:11434 ou http://localhost:1234/v1")
        self.log_text.setPlaceholderText("Logs e progresso serão exibidos aqui...")

        # padrões de novo comportamento
        self.attach_images_check.setChecked(True)
        self.prompt_variant_combo.setCurrentIndex(0)

        self._apply_host_defaults()
        self._update_source_fields(self.source_combo.currentText())
        self._update_source_fields(self.source_combo.currentText())
        self._update_mode_fields(self._get_selected_mode())

    def _connect_dynamic_behaviors(self) -> None:
        # self.host_ollama.toggled.connect(...) removed
        # self.host_lmstudio.toggled.connect(...) removed
        self.source_combo.currentTextChanged.connect(self._update_source_fields)
        self.source_combo.currentTextChanged.connect(self._on_source_changed)
        
        # Connect button group signal
        self.mode_group.buttonToggled.connect(
            lambda: self._update_mode_fields(self._get_selected_mode())
        )
    
    def _setup_keyboard_shortcuts(self) -> None:
        """Configure keyboard shortcuts for common actions."""
        # Ctrl+R / F5: Run host
        run_shortcut = QShortcut(QKeySequence("Ctrl+R"), self)
        run_shortcut.activated.connect(self.run_host)
        run_f5 = QShortcut(QKeySequence("F5"), self)
        run_f5.activated.connect(self.run_host)
        
        # Ctrl+E / Escape: Stop execution
        stop_shortcut = QShortcut(QKeySequence("Ctrl+E"), self)
        stop_shortcut.activated.connect(self._stop_processing)
        esc_shortcut = QShortcut(QKeySequence("Escape"), self)
        esc_shortcut.activated.connect(self._stop_processing)
        
        # Ctrl+L: Clear log
        clear_log_shortcut = QShortcut(QKeySequence("Ctrl+L"), self)
        clear_log_shortcut.activated.connect(self.log_text.clear)
        
        # Ctrl+T: Test Darktable connection
        probe_shortcut = QShortcut(QKeySequence("Ctrl+T"), self)
        probe_shortcut.activated.connect(self._probe_darktable_connection)
        
        # Ctrl+M: Check models
        models_shortcut = QShortcut(QKeySequence("Ctrl+M"), self)
        models_shortcut.activated.connect(self._check_connection_and_fetch_models)
        
        # Ctrl+O: Open prompt file
        prompt_shortcut = QShortcut(QKeySequence("Ctrl+O"), self)
        prompt_shortcut.activated.connect(self._choose_prompt_file)
        
        # F1: Show help/shortcuts
        help_shortcut = QShortcut(QKeySequence("F1"), self)
        help_shortcut.activated.connect(self._show_keyboard_shortcuts)
    
    def _setup_tab_order(self) -> None:
        """Configure logical tab order for keyboard navigation."""
        self.setTabOrder(self.source_combo, self.path_contains_edit)
        self.setTabOrder(self.path_contains_edit, self.tag_edit)
        self.setTabOrder(self.tag_edit, self.collection_combo)
        self.setTabOrder(self.collection_combo, self.min_rating_spin)
        self.setTabOrder(self.min_rating_spin, self.limit_spin)
        self.setTabOrder(self.limit_spin, self.timeout_spin)
        self.setTabOrder(self.timeout_spin, self.prompt_edit)
        self.setTabOrder(self.prompt_edit, self.prompt_button)
        self.setTabOrder(self.prompt_button, self.target_edit)
        self.setTabOrder(self.target_edit, self.target_button)
        self.setTabOrder(self.target_button, self.only_raw_check)
        self.setTabOrder(self.only_raw_check, self.dry_run_check)
        self.setTabOrder(self.dry_run_check, self.attach_images_check)
        self.setTabOrder(self.attach_images_check, self.generate_styles_check)
        self.setTabOrder(self.generate_styles_check, self.model_combo)
        self.setTabOrder(self.model_combo, self.url_edit)
        self.setTabOrder(self.url_edit, self.check_models_button)
        self.setTabOrder(self.check_models_button, self.prompt_variant_combo)
        self.setTabOrder(self.prompt_variant_combo, self.run_button)
        self.setTabOrder(self.run_button, self.stop_button)
    
    def _show_keyboard_shortcuts(self) -> None:
        """Display keyboard shortcuts help dialog."""
        shortcuts_text = """
<h3>Atalhos de Teclado</h3>
<table>
<tr><td><b>Ctrl+R / F5</b></td><td>Executar host</td></tr>
<tr><td><b>Ctrl+E / ESC</b></td><td>Parar execução</td></tr>
<tr><td><b>Ctrl+L</b></td><td>Limpar log</td></tr>
<tr><td><b>Ctrl+T</b></td><td>Testar conexão Darktable</td></tr>
<tr><td><b>Ctrl+M</b></td><td>Verificar modelos disponíveis</td></tr>
<tr><td><b>Ctrl+O</b></td><td>Abrir arquivo de prompt</td></tr>
<tr><td><b>F1</b></td><td>Mostrar este help</td></tr>
<tr><td><b>Tab</b></td><td>Navegar entre campos</td></tr>
</table>
"""
        QMessageBox.information(self, "Atalhos de Teclado", shortcuts_text)

    def _apply_host_defaults(self) -> None:
        host = "ollama"
        model_default = OLLAMA_MODEL
        url_default = OLLAMA_URL

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
        self.collection_combo.setEnabled(is_collection)

        self.path_contains_edit.setToolTip(
            "Filtrar apenas por caminho contendo este trecho."
            if is_path
            else "Disponível somente quando a fonte for 'path'."
        )
        self.tag_edit.setToolTip(
            "Tag existente no darktable."
            if is_tag
            else "Disponível somente quando a fonte for 'tag'."
        )
        self.collection_combo.setToolTip(
            "Especifica a coleção Darktable (filme) de onde as imagens serão obtidas."
            if is_collection
            else "Disponível somente quando a fonte for 'collection'."
        )

    def _update_mode_fields(self, mode: str) -> None:
        is_export = mode in {"export", "completo"}

        self.target_edit.setEnabled(is_export)
        self.target_button.setEnabled(is_export)

        tooltip = (
            "Necessário para export ou modo completo."
            if is_export
            else "Habilite ao selecionar modo export ou completo."
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
        
        # Reset stop flag and enable stop button
        self._stop_requested = False
        self.stop_button.setEnabled(True)
        self.run_button.setEnabled(False)

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
            # Re-enable run button and disable stop button when task completes
            self.stop_button.setEnabled(False)
            self.run_button.setEnabled(True)

    def _stop_processing(self) -> None:
        """Request graceful stop of current processing."""
        if not self._stop_requested:
            self._stop_requested = True
            self._append_log("[sistema] Interrupção solicitada. Aguardando conclusão da operação atual...")
            self.status_signal.emit("Interrupção solicitada...")

    def _append_log(self, text: str) -> None:
        self.log_signal.emit(text)

    @Slot(str)
    def _append_log_ui(self, text: str) -> None:
        self.log_text.append(text)
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )
        self._maybe_update_image_preview(text)

    @Slot(str)
    def _set_status_ui(self, text: str) -> None:
        self.progress.setFormat(text)

    def _set_controls_enabled(self, enabled: bool) -> None:
        """Ativa/desativa os controles principais durante tarefas assíncronas."""
        # Botões principais
        self.run_button.setEnabled(enabled)
        self.check_models_button.setEnabled(enabled)
        self.darktable_probe_button.setEnabled(enabled)

        # Campos de configuração
        for widget in (
            self.mode_rating,
            self.mode_tagging,
            self.mode_export,
            self.mode_treatment,
            self.mode_completo,
            self.source_combo,
            self.path_contains_edit,
            self.tag_edit,
            self.collection_combo,
            self.prompt_edit,
            self.prompt_button,
            self.prompt_generate_button,
            self.target_edit,
            self.target_button,
            self.min_rating_spin,
            self.limit_spin,
            self.timeout_spin,
            self.only_raw_check,
            self.dry_run_check,
            self.attach_images_check,
            self.generate_styles_check,
            # self.host_ollama,   -- Removed
            # self.host_lmstudio, -- Removed
            self.model_combo,
            self.url_edit,
            self.prompt_variant_combo,
        ):
            widget.setEnabled(enabled)

    @Slot(bool)
    def _toggle_progress(self, running: bool) -> None:
        # Travar/destravar UI
        self._set_controls_enabled(not running)

        if not running:
            # Reset to 0% when stopping
            self.progress.setValue(0)
            self.progress.setFormat("Pronto.")

    @Slot(int, int, str)
    def _update_progress(self, current: int, total: int, message: str) -> None:
        """Update progress bar with current status."""
        if total > 0:
            percentage = int((current / total) * 100)
            self.progress.setValue(percentage)
            self.progress.setFormat(f"{message} ({current}/{total}) - {percentage}%")
        else:
            # Indeterminate - just show message
            self.progress.setValue(0)
            self.progress.setFormat(message)


    def resizeEvent(self, event: QResizeEvent) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._refresh_image_preview()

    @Slot(str)
    def _show_error(self, message: str) -> None:
        QMessageBox.critical(self, "Erro", message)

    # ----------------------------- Execução -------------------------------------------------

    def run_host(self) -> None:
        try:
            config = self._build_config()
        except ValueError as exc:
            QMessageBox.critical(self, "Parâmetros inválidos", str(exc))
            return

        self._reset_image_preview("Aguardando detecção da imagem em processamento...")

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
        mode = self._get_selected_mode()
        source = self.source_combo.currentText()

        path_contains = self.path_contains_edit.text().strip() or None
        tag = self.tag_edit.text().strip() or None
        
        # Get full path from UserRole data (falls back to text if manually entered)
        collection = self.collection_combo.currentData(Qt.ItemDataRole.UserRole)
        if not collection:
            # Fallback to text if no data (manual entry case)
            collection = self.collection_combo.currentText().strip() or None

        prompt_file_input = self.prompt_edit.text().strip() or None
        prompt_file = Path(prompt_file_input).expanduser() if prompt_file_input else None

        target_dir = self.target_edit.text().strip() or None

        if source == "path" and not path_contains:
            raise ValueError("'Path contains' é obrigatório quando a fonte é 'path'.")
        if source == "tag" and not tag:
            raise ValueError("Tag é obrigatória quando a fonte é 'tag'.")
        if source == "collection" and not collection:
            raise ValueError("Coleção é obrigatória quando a fonte é 'collection'.")
        if mode in {"export", "completo"} and not target_dir:
            raise ValueError("Diretório de export é obrigatório em modo export ou completo.")

        # validações adicionais
        if prompt_file and not prompt_file.is_file():
            raise ValueError(f"Arquivo de prompt não encontrado: {prompt_file}")

        if target_dir:
            export_dir = Path(target_dir).expanduser()
            if not export_dir.is_dir():
                raise ValueError(f"Diretório de export inválido: {export_dir}")

        model_default = OLLAMA_MODEL
        url_default = OLLAMA_URL

        # mapeia nível de prompt (básico/avançado)
        prompt_variant_text = ""
        if hasattr(self, "prompt_variant_combo"):
            prompt_variant_text = self.prompt_variant_combo.currentText().strip().lower()
        prompt_variant = "avancado" if prompt_variant_text.startswith("av") else "basico"

        # multimodal vs apenas texto
        text_only = not bool(self.attach_images_check.isChecked())

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
            target_dir=target_dir,
            model=self.model_combo.currentText().strip() or model_default,
            llm_url=self.url_edit.text().strip() or url_default,
            prompt_file=str(prompt_file) if prompt_file else None,
            timeout=float(self.timeout_spin.value()),
            download_model=None,
            prompt_variant=self.prompt_variant_combo.currentText().lower(),
            generate_styles=bool(self.generate_styles_check.isChecked()),
            text_only=text_only,
            extra_flags=[],
        )

    # ----------------------------- Utilidades -------------------------------------------

    def _check_connection_and_fetch_models(self) -> None:
        host = "ollama"

        def task() -> None:
            base_url = self.url_edit.text().strip() or OLLAMA_URL
            models = self._fetch_available_models(host, base_url)

            readable = "Ollama"
            self._append_log(
                f"[ok] {readable} acessível em {base_url}. {len(models)} modelo(s) encontrado(s)."
            )
            if models:
                self._append_log("Modelos disponíveis: " + ", ".join(models))
            else:
                self._append_log("Nenhum modelo retornado pelo servidor.")

            self.status_signal.emit(f"{len(models)} modelo(s) disponível(is).")
            self.models_signal.emit(models)

        self._run_async("Verificando servidor LLM...", task)

    def _probe_darktable_connection(self) -> None:
        min_rating = int(self.min_rating_spin.value())
        only_raw = bool(self.only_raw_check.isChecked())
        sample_limit = min(int(self.limit_spin.value()), 50)

        def task() -> None:
            self._append_log("[dt] Verificando conexão com o darktable...")
            probe = probe_darktable_state(
                MCP_PROTOCOL_VERSION,
                GUI_CLIENT_INFO,
                min_rating=min_rating,
                only_raw=only_raw,
                sample_limit=sample_limit,
            )

            deps = probe.get("dependencies", {})
            missing = probe.get("missing_dependencies", [])
            for name, location in deps.items():
                status = f"OK ({location})" if location else "NÃO encontrado"
                self._append_log(f"[deps] {name}: {status}")

            cli_cmd = deps.get("darktable-cli") or ""
            if cli_cmd.startswith("flatpak run"):
                self._append_log(
                    "[flatpak] darktable-cli disponível via Flatpak. Ajuste DARKTABLE_FLATPAK_PREFIX "
                    "ou DARKTABLE_CLI_CMD se usar um prefixo diferente."
                )

            if missing:
                self._append_log(
                    "[dt] Dependências ausentes; instale-as e tente novamente."
                )
                self.status_signal.emit("Dependências do darktable ausentes.")
                return

            if probe.get("error"):
                self._append_log(f"[dt] Erro ao consultar darktable: {probe['error']}")
                self.status_signal.emit("Falha ao conectar ao darktable.")
                return

            tools = probe.get("tools") or []
            self._append_log(
                f"[dt] MCP inicializado. Ferramentas: {', '.join(tools) if tools else 'nenhuma'}"
            )

            collections = probe.get("collections") or []
            self._append_log(f"[dt] Coleções detectadas ({len(collections)}):")
            for entry in collections[:10]:
                film = entry.get("film_roll")
                suffix = f" [filme: {film}]" if film else ""
                self._append_log(
                    f"  - {entry.get('path')} ({entry.get('image_count', 0)} fotos){suffix}"
                )
            if len(collections) > 10:
                self._append_log(f"  ... +{len(collections) - 10} coleções")

            total = probe.get("image_total", 0)
            sample = probe.get("sample_images") or []
            self._append_log(f"[dt] Imagens disponíveis: {total} (amostra de {len(sample)})")
            for item in sample[:10]:
                path = Path(item.get("path", "")) / str(item.get("filename", ""))
                labels = ",".join(item.get("colorlabels", []))
                self._append_log(
                    f"  - id={item.get('id')} rating={item.get('rating')} raw={item.get('is_raw')} "
                    f"labels={labels} {path}"
                )

            self.status_signal.emit("Darktable acessível e catálogo listado.")

        self._run_async("Consultando darktable...", task)

    def _fetch_available_models(self, host: str, url: str) -> list[str]:
        """Consulta modelos disponíveis usando a interface ILLMProvider."""
        if not self._llm_provider_factory:
            raise RuntimeError("Fábrica de LLMProvider não configurada na GUI.")
        provider = self._llm_provider_factory(url=url, model="", timeout=10)
        # Assume que provider tem método list_models()
        if hasattr(provider, "list_models"):
            return provider.list_models()
        # Fallback: tenta método compatível
        if hasattr(provider, "fetch_models"):
            return provider.fetch_models()
        raise NotImplementedError("O provider LLM não implementa list_models/fetch_models.")

    @Slot(list)
    def _update_model_options(self, models: list[str]) -> None:
        current = self.model_combo.currentText().strip()

        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for model in models:
            self.model_combo.addItem(model)

        if current and current not in models:
            self.model_combo.insertItem(0, current)
            self.model_combo.setCurrentText(current)
        elif models:
            self.model_combo.setCurrentText(models[0])
        self.model_combo.blockSignals(False)

    def _on_source_changed(self, source: str) -> None:
        """Auto-fetch collections when source is set to 'collection'."""
        if source == "collection":
            self._fetch_and_populate_collections()

    def _fetch_and_populate_collections(self, force_refresh: bool = False) -> None:
        """Fetch collections from Darktable in a background thread, with caching."""
        import time
        
        # Check cache if not forcing refresh
        if not force_refresh and self._collections_cache is not None:
            cached_time, cached_collections = self._collections_cache
            age = time.time() - cached_time
            if age < self._collections_cache_ttl:
                self._append_log(f"[cache] Usando coleções em cache ({age:.1f}s de idade)")
                self.collections_signal.emit(cached_collections)
                return
        
        def task() -> None:
            import time
            from common import list_available_collections, _find_appimage

            self._append_log("[dt] Buscando coleções do Darktable...")

            def task():
                try:
                    appimage = _find_appimage()
                    # Usa a fábrica injetada para criar o client (pode ser mock)
                    with self._mcp_client_factory() as client:
                        client.initialize()
                        collections_data = list_available_collections(client)

                    collections = [c.get("path", "") for c in collections_data if c.get("path")]
                    self._append_log(f"[dt] {len(collections)} coleção(ões) encontrada(s).")

                    # Update cache
                    self._collections_cache = (time.time(), collections)

                    self.status_signal.emit(f"{len(collections)} coleção(ões) disponível(is).")
                    self.collections_signal.emit(collections)

                except Exception as e:
                    self._append_log(f"[erro] Falha ao buscar coleções: {e}")
                    self.status_signal.emit("Erro ao buscar coleções.")
                    self.collections_signal.emit([])

            self._run_async("Buscando coleções...", task)

    @Slot(list)
    def _populate_collections(self, collections: list[str]) -> None:
        """Populate collection combo with fetched collections."""
        from pathlib import Path
        
        # Get current selection (could be full path or basename)
        current_data = self.collection_combo.currentData(Qt.ItemDataRole.UserRole)
        current_text = self.collection_combo.currentText().strip()
        
        self.collection_combo.blockSignals(True)
        self.collection_combo.clear()
        
        for collection in collections:
            # Extract basename for display
            basename = Path(collection).name
            
            # Add item with basename as display text
            self.collection_combo.addItem(basename)
            
            # Store full path as UserRole data for retrieval
            idx = self.collection_combo.count() - 1
            self.collection_combo.setItemData(idx, collection, Qt.ItemDataRole.UserRole)
            
            # Set tooltip to show full path on hover
            self.collection_combo.setItemData(idx, collection, Qt.ItemDataRole.ToolTipRole)
        
        # Restore previous selection if it exists
        if current_data:
            # Try to find by full path
            for i in range(self.collection_combo.count()):
                if self.collection_combo.itemData(i, Qt.ItemDataRole.UserRole) == current_data:
                    self.collection_combo.setCurrentIndex(i)
                    break
        elif current_text and not collections:
            # If manually entered and no collections loaded, preserve the text
            self.collection_combo.addItem(current_text)
            self.collection_combo.setItemData(0, current_text, Qt.ItemDataRole.UserRole)
            self.collection_combo.setCurrentIndex(0)
        elif collections:
            # Default to first collection
            self.collection_combo.setCurrentIndex(0)
            
        self.collection_combo.blockSignals(False)


    def _selected_host(self) -> str:
        return "ollama"

    def _get_selected_mode(self) -> str:
        """Helper to get text from the selected radio button."""
        if self.mode_rating.isChecked():
            return "rating"
        if self.mode_tagging.isChecked():
            return "tagging"
        if self.mode_export.isChecked():
            return "export"
        if self.mode_treatment.isChecked():
            return "tratamento"
        if self.mode_completo.isChecked():
            return "completo"
        return "rating"  # fallback

def main() -> None:
    qt_app = QApplication(sys.argv)
    qt_app.setStyle("Fusion")
    window = MCPGui()
    window.show()
    qt_app.exec()


if __name__ == "__main__":
    main()
