"""
Main Window — Keyboard PCB Tool

Linear wizard workflow:
  Step 1: 导入与解析 (Import & Parse)
  Step 2: 智能避空配置 (Avoidance & Canvas)
  Step 3: 配列与微调 (Layout & Fine-tune)
  Step 4: 一键导出 (Export DXF)
"""
from __future__ import annotations
import os
import json
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QPushButton, QLabel, QFileDialog,
    QMessageBox, QStatusBar, QProgressBar, QGroupBox,
    QCheckBox, QComboBox, QLineEdit, QDoubleSpinBox,
    QGridLayout, QScrollArea, QFrame, QApplication,
)
from PyQt5.QtCore import Qt, pyqtSignal, QSize
from PyQt5.QtGui import QIcon, QFont, QKeySequence, QColor

from models.pcb_data import PCBData, BoardOutline, ScrewHole
from models.footprint_rules import FootprintRuleSet
from models.layout_group import LayoutConfig, LayoutGroup, LayoutOption
from models.layer_config import LayerConfigSet, FoamLayerConfig, DEFAULT_LAYERS
from models.avoidance import AvoidancePolygon

from parsers.altium_parser import AltiumASCIIParser, validate_ascii_pcb
from avoidance.detector import detect_suspected_avoidance
from avoidance.layout_hints import detect_layout_templates, LayoutTemplate

from gui.pcb_canvas import (
    PcbCanvas, MODE_SELECT, MODE_DRAW_RECT, MODE_DRAW_POLYGON,
    MODE_PLACE_HOLE, MODE_DRAW_OUTLINE
)
from gui.avoidance_editor import AvoidanceEditor
from gui.outline_editor import OutlineEditor

from generators.plate_generator import (
    generate_plate, PLATE_VARIANT_ANSI, PLATE_VARIANT_7U_ENTER, PLATE_VARIANT_UNIVERSAL,
)
from generators.foam_generator import generate_foam_layer


# ── Step Names ──────────────────────────────────────────────────────
STEP_NAMES = ["导入与解析", "智能避空配置", "配列与微调", "一键导出"]
STEP_COUNT = len(STEP_NAMES)


@dataclass
class AppState:
    pcb_data: Optional[PCBData] = None
    rule_set: FootprintRuleSet = field(default_factory=FootprintRuleSet.get_default_rules)
    layout_config: LayoutConfig = field(default_factory=LayoutConfig)
    layer_config: LayerConfigSet = field(default_factory=lambda: LayerConfigSet(layers=list(DEFAULT_LAYERS)))
    avoidance_polygons: list[AvoidancePolygon] = field(default_factory=list)
    project_path: Optional[str] = None
    modified: bool = False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MainWindow
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.state = AppState()
        self._current_step = 0

        # Panels (created lazily per step)
        self._avoidance_panel: Optional[AvoidanceEditor] = None
        self._outline_panel: Optional[OutlineEditor] = None

        self._init_ui()
        self._create_menu_bar()
        self._create_status_bar()
        self._goto_step(0)

    # ── UI scaffold ─────────────────────────────────────────────────
    def _init_ui(self):
        self.setWindowTitle("键盘PCB工具")
        self.resize(1400, 900)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(8)

        # Left: PCB canvas (always visible)
        self.canvas = PcbCanvas(self)
        self.canvas.setMinimumWidth(600)
        main_layout.addWidget(self.canvas, stretch=3)

        # Connect canvas signals
        self.canvas._view.signal_cursor_position.connect(self._on_cursor)
        self.canvas._view.signal_zoom_changed.connect(self._on_zoom)
        self.canvas._view.signal_avoidance_created.connect(self._on_avoidance_created)
        self.canvas._view.signal_hole_placed.connect(self._on_hole_placed)
        self.canvas._view.signal_outline_point_added.connect(self._on_outline_point_added)
        self.canvas.signal_preview_layer_changed.connect(self._on_preview_layer_changed)

        # Right: stacked step panels
        right_layout = QVBoxLayout()
        right_layout.setSpacing(6)

        # Step indicator
        self._step_label = QLabel()
        self._step_label.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        self._step_label.setAlignment(Qt.AlignCenter)
        right_layout.addWidget(self._step_label)

        # Step progress dots
        self._progress_dots = QLabel()
        self._progress_dots.setAlignment(Qt.AlignCenter)
        right_layout.addWidget(self._progress_dots)

        # Stacked panels
        self._stack = QStackedWidget()
        self._stack.addWidget(self._create_step1_import())
        self._stack.addWidget(self._create_step2_avoidance())
        self._stack.addWidget(self._create_step3_layout())
        self._stack.addWidget(self._create_step4_export())
        right_layout.addWidget(self._stack, stretch=1)

        # Navigation buttons
        nav_layout = QHBoxLayout()
        self._btn_prev = QPushButton("上一步")
        self._btn_prev.clicked.connect(self._prev_step)
        self._btn_next = QPushButton("下一步")
        self._btn_next.clicked.connect(self._next_step)
        nav_layout.addWidget(self._btn_prev)
        nav_layout.addStretch()
        nav_layout.addWidget(self._btn_next)
        right_layout.addLayout(nav_layout)

        right_widget = QWidget()
        right_widget.setLayout(right_layout)
        right_widget.setMinimumWidth(380)
        right_widget.setMaximumWidth(480)
        main_layout.addWidget(right_widget, stretch=1)

    # ── Step 1: Import & Parse ──────────────────────────────────────
    def _create_step1_import(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(12)

        # Import button
        import_group = QGroupBox("导入PCB文件")
        ig_layout = QVBoxLayout(import_group)
        self._btn_import = QPushButton("打开 Altium ASCII .PcbDoc 文件")
        self._btn_import.setMinimumHeight(48)
        self._btn_import.setStyleSheet("font-size: 14px;")
        self._btn_import.clicked.connect(self._open_pcb_file)
        ig_layout.addWidget(self._btn_import)
        layout.addWidget(import_group)

        # Classification results
        result_group = QGroupBox("元件识别结果")
        rg_layout = QGridLayout(result_group)
        self._lbl_switches = QLabel("轴体: -")
        self._lbl_leds = QLabel("LED: -")
        self._lbl_ics = QLabel("IC: -")
        self._lbl_mech = QLabel("机械件: -")
        self._lbl_total = QLabel("总计: -")
        for i, lbl in enumerate([self._lbl_switches, self._lbl_leds, self._lbl_ics, self._lbl_mech, self._lbl_total]):
            lbl.setStyleSheet("font-size: 13px; padding: 4px;")
            rg_layout.addWidget(lbl, i // 2, i % 2)
        layout.addWidget(result_group)

        # Board info
        info_group = QGroupBox("板框信息")
        info_layout = QVBoxLayout(info_group)
        self._lbl_outline = QLabel("未检测到板框")
        self._lbl_outline.setStyleSheet("color: gray;")
        info_layout.addWidget(self._lbl_outline)
        layout.addWidget(info_group)

        layout.addStretch()
        return panel

    # ── Step 2: Avoidance & Canvas ──────────────────────────────────
    def _create_step2_avoidance(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(8)

        # Avoidance editor
        self._avoidance_panel = AvoidanceEditor(parent=self)
        self._avoidance_panel.polygon_confirmed.connect(self._on_avoidance_confirmed)
        self._avoidance_panel.polygon_deleted.connect(self._on_avoidance_deleted)
        self._avoidance_panel.polygon_added.connect(self._on_avoidance_added)
        self._avoidance_panel.polygon_updated.connect(self._on_avoidance_updated)
        self._avoidance_panel.draw_mode_requested.connect(self._on_draw_mode_requested)
        layout.addWidget(self._avoidance_panel)

        # Outline editor (compact)
        outline_group = QGroupBox("板框与螺丝孔")
        ol_layout = QVBoxLayout(outline_group)
        self._outline_panel = OutlineEditor(parent=self)
        self._outline_panel.outline_changed.connect(self._on_outline_changed)
        self._outline_panel.hole_added.connect(self._on_hole_added)
        self._outline_panel.hole_removed.connect(self._on_hole_removed)
        self._outline_panel.draw_outline_requested.connect(
            lambda: self.canvas.set_interaction_mode(MODE_DRAW_OUTLINE)        )
        self._outline_panel.place_hole_requested.connect(
            lambda: self.canvas.set_interaction_mode(MODE_PLACE_HOLE)

        )
        ol_layout.addWidget(self._outline_panel)
        layout.addWidget(outline_group)

        return panel

    # ── Step 3: Layout & Fine-tune ──────────────────────────────────
    def _create_step3_layout(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(12)

        # Detected template
        tpl_group = QGroupBox("检测到的配列模板")
        tpl_layout = QVBoxLayout(tpl_group)
        self._lbl_template = QLabel("请先导入PCB并识别轴体")
        self._lbl_template.setStyleSheet("color: gray; font-size: 13px;")
        tpl_layout.addWidget(self._lbl_template)

        # Template selector
        tpl_sel_layout = QHBoxLayout()
        tpl_sel_layout.addWidget(QLabel("选择模板:"))
        self._template_combo = QComboBox()
        self._template_combo.currentIndexChanged.connect(self._on_template_changed)
        tpl_sel_layout.addWidget(self._template_combo)
        tpl_layout.addLayout(tpl_sel_layout)

        layout.addWidget(tpl_group)
        self._detected_templates: list[LayoutTemplate] = []

        # Split options
        split_group = QGroupBox("分裂选项微调")
        self._split_layout = QGridLayout(split_group)
        self._split_layout.setSpacing(8)
        self._split_combos: dict[str, QComboBox] = {}
        self._create_split_option("回车", "enter", ["标准回车", "七字回车 (7U)"])
        self._create_split_option("左Shift", "lshift", ["标准 Shift (2.25U)", "分裂 Shift (1.25U + 1U)"])
        self._create_split_option("右Shift", "rshift", ["标准 Shift (2.75U)", "分裂 Shift (1.75U + 1U)"])
        self._create_split_option("Backspace", "backspace", ["标准 Backspace (2U)", "分裂 Backspace (1.5U + 1U)"])
        self._create_split_option("空格", "spacebar", ["6.25U 空格", "7U 空格", "分裂空格"])
        layout.addWidget(split_group)

        # Apply button
        self._btn_apply_layout = QPushButton("应用配列配置")
        self._btn_apply_layout.clicked.connect(self._apply_layout_config)
        layout.addWidget(self._btn_apply_layout)

        layout.addStretch()
        return panel

    def _create_split_option(self, label: str, key: str, options: list[str]):
        row = self._split_layout.rowCount()
        self._split_layout.addWidget(QLabel(f"{label}:"), row, 0)
        combo = QComboBox()
        combo.addItems(options)
        combo.currentIndexChanged.connect(self._on_split_option_changed)
        self._split_combos[key] = combo
        self._split_layout.addWidget(combo, row, 1)

    # ── Step 4: Export ──────────────────────────────────────────────
    def _create_step4_export(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(12)

        # Layer selection
        layer_group = QGroupBox("选择导出图层")
        layer_layout = QVBoxLayout(layer_group)
        self._layer_checks: dict[str, QCheckBox] = {}
        for layer in DEFAULT_LAYERS:
            cb = QCheckBox(f"{layer.name_cn} ({layer.name}) — {layer.thickness}mm")
            cb.setChecked(layer.name == "plate")  # Default: only plate checked
            self._layer_checks[layer.name] = cb
            layer_layout.addWidget(cb)

        btn_row = QHBoxLayout()
        btn_sel_all = QPushButton("全选")
        btn_sel_all.clicked.connect(lambda: [cb.setChecked(True) for cb in self._layer_checks.values()])
        btn_desel = QPushButton("取消全选")
        btn_desel.clicked.connect(lambda: [cb.setChecked(False) for cb in self._layer_checks.values()])
        btn_row.addWidget(btn_sel_all)
        btn_row.addWidget(btn_desel)
        btn_row.addStretch()
        layer_layout.addLayout(btn_row)
        layout.addWidget(layer_group)

        # Output settings
        out_group = QGroupBox("输出设置")
        out_layout = QGridLayout(out_group)

        out_layout.addWidget(QLabel("输出目录:"), 0, 0)
        self._output_dir = QLineEdit()
        self._output_dir.setPlaceholderText("选择输出目录...")
        out_layout.addWidget(self._output_dir, 0, 1)
        btn_browse = QPushButton("浏览...")
        btn_browse.clicked.connect(self._browse_output_dir)
        out_layout.addWidget(btn_browse, 0, 2)

        out_layout.addWidget(QLabel("项目名称:"), 1, 0)
        self._project_name = QLineEdit("keyboard")
        out_layout.addWidget(self._project_name, 1, 1, 1, 2)

        out_layout.addWidget(QLabel("文件名模板:"), 2, 0)
        self._file_pattern = QLineEdit("{project}_{layer}_{variant}.dxf")
        self._file_pattern.setToolTip("{project}=项目名 {layer}=层名 {variant}=变体")
        out_layout.addWidget(self._file_pattern, 2, 1, 1, 2)

        layout.addWidget(out_group)

        # Export button
        self._btn_export = QPushButton("导出 DXF")
        self._btn_export.setMinimumHeight(48)
        self._btn_export.setStyleSheet("font-size: 14px; font-weight: bold;")
        self._btn_export.clicked.connect(self._export_dxf)
        layout.addWidget(self._btn_export)

        # Progress
        self._export_progress = QProgressBar()
        self._export_progress.setVisible(False)
        layout.addWidget(self._export_progress)

        self._export_status = QLabel()
        self._export_status.setVisible(False)
        layout.addWidget(self._export_status)

        layout.addStretch()
        return panel

    # ── Menu bar ────────────────────────────────────────────────────
    def _create_menu_bar(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("文件(&F)")
        open_act = file_menu.addAction("打开PCB...")
        open_act.setShortcut(QKeySequence.Open)
        open_act.triggered.connect(self._open_pcb_file)

        file_menu.addSeparator()

        save_act = file_menu.addAction("保存项目...")
        save_act.setShortcut(QKeySequence.Save)
        save_act.triggered.connect(self._save_project)

        load_act = file_menu.addAction("加载项目...")
        load_act.triggered.connect(self._load_project)

        file_menu.addSeparator()

        export_act = file_menu.addAction("导出DXF...")
        export_act.triggered.connect(self._export_dxf)

        file_menu.addSeparator()
        file_menu.addAction("退出", self.close)

        view_menu = menubar.addMenu("视图(&V)")
        view_menu.addAction("适应内容", self.canvas.fit_to_content)
        view_menu.addAction("放大", lambda: self.canvas._view.scale(1.15, 1.15))
        view_menu.addAction("缩小", lambda: self.canvas._view.scale(1.0 / 1.15, 1.0 / 1.15))

        help_menu = menubar.addMenu("帮助(&H)")
        help_menu.addAction("关于", self._show_about)

    # ── Status bar ──────────────────────────────────────────────────
    def _create_status_bar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        self._status_mode = QLabel("模式: 选择")
        sb.addWidget(self._status_mode)
        self._status_cursor = QLabel("光标: (0.0, 0.0)mm")
        sb.addWidget(self._status_cursor)
        self._status_switches = QLabel("轴体: 0")
        sb.addWidget(self._status_switches)
        self._status_zoom = QLabel("缩放: 1.0x")
        sb.addPermanentWidget(self._status_zoom)

    # ── Step navigation ─────────────────────────────────────────────
    def _goto_step(self, step: int):
        self._current_step = max(0, min(step, STEP_COUNT - 1))
        self._stack.setCurrentIndex(self._current_step)

        # Update step label
        name = STEP_NAMES[self._current_step]
        self._step_label.setText(f"步骤 {self._current_step + 1}/{STEP_COUNT}: {name}")

        # Update progress dots
        dots = "  ".join(
            f"{'●' if i == self._current_step else '○'}"
            for i in range(STEP_COUNT)
        )
        self._progress_dots.setText(dots)
        self._progress_dots.setStyleSheet("font-size: 16px; color: #4a9eff;")

        # Update nav buttons
        self._btn_prev.setEnabled(self._current_step > 0)
        self._btn_next.setText("完成" if self._current_step == STEP_COUNT - 1 else "下一步")

        # Step-specific setup
        if self._current_step == 2:
            self._update_layout_template_info()
        # Update preview when entering steps 1+
        if self._current_step >= 1:
            self._update_preview()

    def _on_preview_layer_changed(self, layer_key: str):
        """Handle preview layer change from combo box."""
        self._update_preview()

    def _next_step(self):
        if self._current_step == STEP_COUNT - 1:
            self._export_dxf()
        else:
            self._goto_step(self._current_step + 1)

    def _prev_step(self):
        self._goto_step(self._current_step - 1)

    # ── PCB Import ──────────────────────────────────────────────────
    def _open_pcb_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "打开PCB文件", "",
            "Altium PCB文件 (*.PcbDoc *.pcb);;所有文件 (*)"
        )
        if not path:
            return

        is_valid, err = validate_ascii_pcb(path)
        if not is_valid:
            QMessageBox.critical(self, "无效的PCB文件", f"打开失败:\n\n{err}")
            return

        try:
            parser = AltiumASCIIParser()
            pcb = parser.parse(path)
            pcb.source_file = path
        except Exception as e:
            QMessageBox.critical(self, "解析错误", f"解析失败:\n\n{e}")
            return

        # Classify components
        self.state.rule_set.classify_components(pcb.components)
        self.state.pcb_data = pcb
        self.state.modified = True

        # Auto-detect avoidance for ICs
        suspected = detect_suspected_avoidance(pcb.components)
        if suspected:
            self.state.avoidance_polygons.extend(suspected)
            if self._avoidance_panel:
                self._avoidance_panel.set_polygons(self.state.avoidance_polygons)

        # Distribute data
        self.canvas.set_pcb_data(pcb)

        if self._outline_panel:
            self._outline_panel.set_pcb_data(pcb)

        # Update Step 1 results
        self._update_classification_display()

        # Switch to step 1 to show results
        self._goto_step(0)

    def _update_classification_display(self):
        if not self.state.pcb_data:
            return
        comps = self.state.pcb_data.components
        switches = sum(1 for c in comps if c.classification == "switch")
        leds = sum(1 for c in comps if c.classification == "led")
        ics = sum(1 for c in comps if c.classification == "ic")
        mech = sum(1 for c in comps if c.classification == "mechanical")
        total = len(comps)

        self._lbl_switches.setText(f"轴体: {switches}")
        self._lbl_switches.setStyleSheet("color: #64c864; font-size: 13px; font-weight: bold;")
        self._lbl_leds.setText(f"LED: {leds}")
        self._lbl_leds.setStyleSheet("color: #ffa500; font-size: 13px;")
        self._lbl_ics.setText(f"IC: {ics}")
        self._lbl_ics.setStyleSheet("color: #ff6464; font-size: 13px;")
        self._lbl_mech.setText(f"机械件: {mech}")
        self._lbl_mech.setStyleSheet("color: #6496ff; font-size: 13px;")
        self._lbl_total.setText(f"总计: {total}")

        outline = self.state.pcb_data.board_outline
        if outline and outline.is_valid():
            self._lbl_outline.setText(f"板框: {len(outline.vertices)} 个顶点")
            self._lbl_outline.setStyleSheet("color: white;")
        else:
            self._lbl_outline.setText("未检测到板框（可在步骤2手动绘制）")
            self._lbl_outline.setStyleSheet("color: gray;")

        self._status_switches.setText(f"轴体: {switches}")

    # ── Step 3: Layout ──────────────────────────────────────────────
    def _update_layout_template_info(self):
        if not self.state.pcb_data:
            self._lbl_template.setText("请先导入PCB并识别轴体")
            return

        switches = self.state.pcb_data.get_switches()
        count = len(switches)
        if count == 0:
            self._lbl_template.setText("未检测到轴体")
            return

        # Detect templates using layout_hints
        self._detected_templates = detect_layout_templates(switches)
        if not self._detected_templates:
            self._lbl_template.setText(f"检测到 {count} 个轴体，无法识别配列模板")
            return

        # Find recommended template
        recommended = next((t for t in self._detected_templates if t.recommended), self._detected_templates[0])
        self._lbl_template.setText(
            f"检测到 {count} 个轴体，推荐模板: {recommended.name}"
        )
        self._lbl_template.setStyleSheet("color: #4a9eff; font-size: 13px; font-weight: bold;")

        # Populate template combo
        self._template_combo.blockSignals(True)
        self._template_combo.clear()
        for t in self._detected_templates:
            self._template_combo.addItem(f"{t.name} — {t.description}")
        self._template_combo.setCurrentIndex(self._detected_templates.index(recommended))
        self._template_combo.blockSignals(False)

        # Update split options for the recommended template
        self._apply_template_splits(recommended)

    def _on_template_changed(self, index: int):
        """Update split option combos when template selection changes."""
        if 0 <= index < len(self._detected_templates):
            self._apply_template_splits(self._detected_templates[index])
        # Auto-apply layout config and update preview
        self._auto_apply_layout()

    def _on_split_option_changed(self, index: int):
        """Auto-apply layout when a split option changes."""
        self._auto_apply_layout()

    def _auto_apply_layout(self):
        """Apply layout config silently (no dialog) and update preview."""
        if not self._detected_templates or not self.state.pcb_data:
            return
        tpl_idx = self._template_combo.currentIndex()
        if tpl_idx < 0 or tpl_idx >= len(self._detected_templates):
            return
        template = self._detected_templates[tpl_idx]

        from avoidance.layout_hints import find_candidate_split_zones
        switches = self.state.pcb_data.get_switches()
        split_zones = find_candidate_split_zones(switches)

        groups = []
        for opt_idx, split_opt in enumerate(template.split_options):
            combo = self._split_combos.get(split_opt.key)
            if not combo:
                continue
            sel_idx = combo.currentIndex()
            opts = [LayoutOption(f"{split_opt.key}_{i}", name, []) for i, name in enumerate(split_opt.options)]
            if opt_idx < len(split_zones):
                zone = split_zones[opt_idx]
                zone_refs = [sw.ref for sw in zone.switches]
                for i, opt in enumerate(opts):
                    if i < len(zone_refs):
                        opt.switch_refs = [zone_refs[i]]
                    else:
                        opt.switch_refs = zone_refs[:1]
            groups.append(LayoutGroup(
                id=split_opt.key,
                name=split_opt.label,
                description=f"{split_opt.label}配列选择",
                options=opts,
                selected_option_id=opts[sel_idx].id if sel_idx < len(opts) else opts[0].id,
            ))
        self.state.layout_config = LayoutConfig(groups=groups)
        self.state.modified = True
        self._update_preview()

    def _apply_template_splits(self, template: LayoutTemplate):
        """Update split option combos to match the selected template's options."""
        key_map = {"enter": "enter", "lshift": "lshift", "rshift": "rshift",
                   "backspace": "backspace", "spacebar": "spacebar"}
        for opt in template.split_options:
            key = key_map.get(opt.key)
            if key and key in self._split_combos:
                combo = self._split_combos[key]
                combo.blockSignals(True)
                combo.clear()
                combo.addItems(opt.options)
                if opt.recommended < len(opt.options):
                    combo.setCurrentIndex(opt.recommended)
                combo.blockSignals(False)

    def _apply_layout_config(self):
        """Build LayoutConfig from current split option selections."""
        if not self._detected_templates:
            QMessageBox.warning(self, "未检测模板", "请先导入PCB文件。")
            return

        tpl_idx = self._template_combo.currentIndex()
        if tpl_idx < 0 or tpl_idx >= len(self._detected_templates):
            return
        template = self._detected_templates[tpl_idx]

        # Find split zones to map switches to layout options
        from avoidance.layout_hints import find_candidate_split_zones
        switches = self.state.pcb_data.get_switches()
        split_zones = find_candidate_split_zones(switches)

        # Map split zones by their position index for matching with split options
        # Each split zone corresponds to a split option key
        zone_by_idx = {i: z for i, z in enumerate(split_zones)}

        # Build a set of excluded switch refs (switches NOT selected in split zones)
        excluded_refs = set()
        included_refs_per_option = {}  # option_id -> list of switch refs to include

        groups = []
        for opt_idx, split_opt in enumerate(template.split_options):
            combo = self._split_combos.get(split_opt.key)
            if not combo:
                continue
            sel_idx = combo.currentIndex()
            opts = [LayoutOption(f"{split_opt.key}_{i}", name, []) for i, name in enumerate(split_opt.options)]

            # If there's a matching split zone, assign switch refs
            if opt_idx < len(split_zones):
                zone = split_zones[opt_idx]
                zone_refs = [sw.ref for sw in zone.switches]
                # All zone switches are excluded by default
                excluded_refs.update(zone_refs)
                # For each variant, include the corresponding switch
                for i, opt in enumerate(opts):
                    if i < len(zone_refs):
                        opt.switch_refs = [zone_refs[i]]
                    else:
                        # Default: include first switch
                        opt.switch_refs = zone_refs[:1]

            groups.append(LayoutGroup(
                id=split_opt.key,
                name=split_opt.label,
                description=f"{split_opt.label}配列选择",
                options=opts,
                selected_option_id=opts[sel_idx].id if sel_idx < len(opts) else opts[0].id,
            ))

        self.state.layout_config = LayoutConfig(groups=groups)
        self.state.modified = True
        self._update_preview()

        QMessageBox.information(self, "配列配置", f"已应用 {template.name} 配列配置。")

    # ── Step 4: Export ──────────────────────────────────────────────
    def _browse_output_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录", os.path.expanduser("~"))
        if d:
            self._output_dir.setText(d)

    def _export_dxf(self):
        if not self.state.pcb_data:
            QMessageBox.warning(self, "没有数据", "请先导入PCB文件。")
            return

        selected = [name for name, cb in self._layer_checks.items() if cb.isChecked()]
        if not selected:
            QMessageBox.warning(self, "未选择图层", "请至少选择一个导出图层。")
            return

        output_dir = self._output_dir.text().strip()
        if not output_dir or not os.path.isdir(output_dir):
            QMessageBox.warning(self, "无效目录", "请选择有效的输出目录。")
            return

        project_name = self._project_name.text().strip() or "keyboard"
        pattern = self._file_pattern.text().strip()

        # Build variant list for plate
        enter_idx = self._split_combos["enter"].currentIndex() if hasattr(self, '_split_combos') else 0
        if enter_idx == 1:
            plate_variants = [PLATE_VARIANT_7U_ENTER]
        else:
            plate_variants = [PLATE_VARIANT_ANSI]

        tasks: list[tuple[str, str, str]] = []
        for layer_name in selected:
            if layer_name == "plate":
                for v in plate_variants:
                    suffix = {"ansi": "ansi", "7u_enter": "7u", "universal": "universal"}.get(v, v)
                    fname = pattern.replace("{project}", project_name).replace("{layer}", layer_name).replace("{variant}", suffix)
                    tasks.append((layer_name, v, os.path.join(output_dir, fname)))
            else:
                fname = pattern.replace("{project}", project_name).replace("{layer}", layer_name).replace("{variant}", "")
                fname = fname.replace("__", "_")
                tasks.append((layer_name, "", os.path.join(output_dir, fname)))

        # Export
        self._export_progress.setVisible(True)
        self._export_status.setVisible(True)
        self._export_progress.setMaximum(len(tasks))
        success = 0
        failed: list[tuple[str, str]] = []

        for i, (layer_name, variant, out_path) in enumerate(tasks):
            self._export_progress.setValue(i)
            layer_cfg = self.state.layer_config.get(layer_name)
            if not layer_cfg:
                failed.append((layer_name, "配置未找到"))
                continue

            variant_label = f" ({variant})" if variant else ""
            self._export_status.setText(f"正在导出: {layer_cfg.name_cn}{variant_label}")

            try:
                if layer_name == "plate":
                    generate_plate(
                        self.state.pcb_data,
                        self.state.layout_config,
                        layer_cfg,
                        self.state.avoidance_polygons,
                        out_path,
                        plate_type=variant,
                    )
                else:
                    generate_foam_layer(
                        self.state.pcb_data,
                        self.state.layout_config,
                        layer_cfg,
                        self.state.avoidance_polygons,
                        out_path,
                    )
                success += 1
            except Exception as e:
                failed.append((layer_name, str(e)))

        self._export_progress.setValue(len(tasks))
        self._export_status.setText("导出完成")

        if failed:
            msg = f"导出 {success}/{len(tasks)} 成功。\n\n失败:\n" + "\n".join(f"  - {n}: {e}" for n, e in failed)
            QMessageBox.warning(self, "导出完成（有错误）", msg)
        else:
            QMessageBox.information(self, "导出成功", f"成功导出 {success}/{len(tasks)} 个图层到:\n{output_dir}")

        self._export_progress.setVisible(False)
        self._export_status.setVisible(False)

    # ── Canvas signal handlers ──────────────────────────────────────
    def _on_cursor(self, x: float, y: float):
        self._status_cursor.setText(f"光标: ({x:.1f}, {y:.1f})mm")

    def _on_zoom(self, level: float):
        self._status_zoom.setText(f"缩放: {level:.2f}x")

    def _on_avoidance_created(self, vertices: list, source: str):
        if self._avoidance_panel:
            self._avoidance_panel.add_polygon_from_canvas(vertices, source)
        self.state.modified = True

    def _on_hole_placed(self, x: float, y: float):
        if self._outline_panel:
            self._outline_panel.add_hole(x, y)

    def _on_outline_point_added(self, x: float, y: float):
        if self._outline_panel:
            self._outline_panel.add_outline_vertex(x, y)

    def _on_avoidance_confirmed(self, index: int):
        self.state.modified = True
        self._update_preview()

    def _on_avoidance_deleted(self, index: int):
        # Editor already removed from the shared list — just mark modified
        self.state.modified = True
        self._update_preview()

    def _on_avoidance_added(self, vertices: list, source: str):
        self.state.modified = True
        self._update_preview()

    def _on_avoidance_updated(self, index: int, poly):
        self.state.modified = True
        self._update_preview()

    def _update_preview(self):
        """Refresh the canvas preview to reflect current editor state."""
        if not self.state.pcb_data:
            return
        outline = None
        if self._outline_panel:
            outline = self._outline_panel.get_board_outline()
        holes = None
        if self._outline_panel:
            holes = self._outline_panel.get_screw_holes()
        avoidance = self.state.avoidance_polygons

        # Compute excluded switch refs from layout config
        excluded_refs = set()
        cfg = self.state.layout_config
        if cfg and cfg.groups:
            # Collect all refs mentioned in any option
            all_zone_refs = set()
            for g in cfg.groups:
                for opt in g.options:
                    all_zone_refs.update(opt.switch_refs)
            # Collect refs from selected options
            selected_refs = cfg.get_active_switch_refs()
            # Exclude zone refs that are NOT selected
            excluded_refs = all_zone_refs - selected_refs

        self.canvas.update_preview(
            board_outline=outline,
            screw_holes=holes,
            avoidance_polygons=avoidance,
            layout_config=self.state.layout_config,
            excluded_switch_refs=excluded_refs,
        )

    def _on_draw_mode_requested(self, mode: str):
        if mode == "rect":
            self.canvas._view.set_interaction_mode(MODE_DRAW_RECT)
        elif mode == "polygon":
            self.canvas._view.set_interaction_mode(MODE_DRAW_POLYGON)
        elif mode == "edit":
            self.canvas._view.set_interaction_mode(MODE_SELECT)

    def _on_outline_changed(self, vertices: list, source: str):
        if self.state.pcb_data:
            self.state.pcb_data.board_outline = BoardOutline(vertices=vertices, source=source)
        self.state.modified = True
        self._update_preview()

    def _on_hole_added(self, x: float, y: float, diameter: float):
        if self.state.pcb_data:
            hole = ScrewHole(x=x, y=y, diameter=diameter, source="manual")
            self.state.pcb_data.screw_holes.append(hole)
        self.state.modified = True
        self._update_preview()

    def _on_hole_removed(self, index: int):
        if self.state.pcb_data and 0 <= index < len(self.state.pcb_data.screw_holes):
            self.state.pcb_data.screw_holes.pop(index)
        self.state.modified = True
        self._update_preview()
        self.state.modified = True

    # ── Project save/load ───────────────────────────────────────────
    def _save_project(self):
        if not self.state.pcb_data:
            QMessageBox.warning(self, "没有数据", "请先打开PCB文件。")
            return
        path, _ = QFileDialog.getSaveFileName(self, "保存项目", "", "项目文件 (*.json);;所有文件 (*)")
        if not path:
            return
        try:
            data = {
                "pcb_source_file": self.state.pcb_data.source_file,
                "rule_set": self.state.rule_set.to_dict(),
                "layout_config": self.state.layout_config.to_dict(),
                "layer_config": self.state.layer_config.to_dict(),
                "avoidance_polygons": [p.to_dict() for p in self.state.avoidance_polygons],
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self.state.project_path = path
            self.state.modified = False
            QMessageBox.information(self, "已保存", f"项目已保存到:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))

    def _load_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "加载项目", "", "项目文件 (*.json);;所有文件 (*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.state.project_path = path
            QMessageBox.information(self, "已加载", f"项目已从:\n{path}\n\n加载成功（完整反序列化待实现）")
        except Exception as e:
            QMessageBox.critical(self, "加载失败", str(e))

    # ── About ───────────────────────────────────────────────────────
    def _show_about(self):
        QMessageBox.about(
            self,
            "关于键盘PCB工具",
            "<h3>键盘PCB工具</h3>"
            "<p>版本 2.0</p>"
            "<p>从PCB文件生成键盘定位板和泡沫层的工具。</p>"
            "<p>功能:</p>"
            "<ul>"
            "<li>解析Altium ASCII PCB文件</li>"
            "<li>自动识别轴体、LED、IC</li>"
            "<li>智能避空区域配置</li>"
            "<li>配列模板检测与微调</li>"
            "<li>一键导出DXF用于CNC制造</li>"
            "</ul>"
        )

    def closeEvent(self, event):
        if self.state.modified:
            reply = QMessageBox.question(
                self, "未保存的更改",
                "您有未保存的更改。是否退出？",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            )
            if reply == QMessageBox.Save:
                self._save_project()
                if self.state.modified:
                    event.ignore()
                    return
            elif reply == QMessageBox.Cancel:
                event.ignore()
                return
        event.accept()
