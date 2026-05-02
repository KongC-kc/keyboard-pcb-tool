"""
Outline Editor Panel for Keyboard PCB Tool.

Manages board outline and screw holes with dual-source support:
- PCB auto-detection or manual input for board outline
- Manual placement or import for screw holes
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QComboBox,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem,
    QDoubleSpinBox, QHeaderView, QFileDialog, QFrame
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QDoubleValidator
from models.pcb_data import PCBData, BoardOutline, ScrewHole
from parsers.dxf_parser import parse_board_outline_dxf
import math


class OutlineEditor(QWidget):
    """Panel for managing board outline and screw holes."""

    # Signals
    outline_changed = pyqtSignal(list, str)  # vertices, source
    hole_added = pyqtSignal(float, float, float)  # x, y, diameter
    hole_removed = pyqtSignal(int)  # index
    hole_updated = pyqtSignal(int, float, float, float)  # index, x, y, diameter
    draw_outline_requested = pyqtSignal()
    place_hole_requested = pyqtSignal()
    import_dxf_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pcb_data = None
        self.outline_vertices = []
        self.screw_holes = []
        self.current_hole_diameter = 2.5  # Default M2.5 screw

        self._init_ui()

    def _init_ui(self):
        """Initialize the user interface."""
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(12)

        # Section 1: Board Outline
        main_layout.addWidget(self._create_outline_section())

        # Section 2: Screw Holes
        main_layout.addWidget(self._create_screw_hole_section())

        # Add stretch at bottom
        main_layout.addStretch()

        self.setLayout(main_layout)

    def _create_outline_section(self) -> QGroupBox:
        """Create the board outline section."""
        group = QGroupBox("板框")
        layout = QVBoxLayout()
        layout.setSpacing(8)

        # Source selector
        source_layout = QHBoxLayout()
        source_layout.addWidget(QLabel("来源:"))
        self.outline_source_combo = QComboBox()
        self.outline_source_combo.addItems(["从PCB自动识别", "手动绘制", "导入DXF"])
        self.outline_source_combo.currentIndexChanged.connect(
            self._on_outline_source_changed
        )
        source_layout.addWidget(self.outline_source_combo)
        source_layout.addStretch()
        layout.addLayout(source_layout)

        # Auto-detected info (for "From PCB")
        self.auto_outline_info = QLabel("未加载PCB数据")
        self.auto_outline_info.setWordWrap(True)
        self.auto_outline_info.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(self.auto_outline_info)

        # Manual drawing controls
        self.manual_draw_widget = QFrame()
        manual_layout = QVBoxLayout()
        manual_layout.setContentsMargins(0, 0, 0, 0)

        btn_layout = QHBoxLayout()
        self.start_draw_btn = QPushButton("开始绘制")
        self.start_draw_btn.clicked.connect(self._on_start_drawing)
        self.finish_draw_btn = QPushButton("完成")
        self.finish_draw_btn.clicked.connect(self._on_finish_drawing)
        self.finish_draw_btn.setEnabled(False)
        self.clear_outline_btn = QPushButton("清除")
        self.clear_outline_btn.clicked.connect(self._on_clear_outline)
        self.clear_outline_btn.setEnabled(False)

        btn_layout.addWidget(self.start_draw_btn)
        btn_layout.addWidget(self.finish_draw_btn)
        btn_layout.addWidget(self.clear_outline_btn)
        btn_layout.addStretch()
        manual_layout.addLayout(btn_layout)

        # Vertex table
        self.vertex_table = QTableWidget()
        self.vertex_table.setColumnCount(3)
        self.vertex_table.setHorizontalHeaderLabels(["X (mm)", "Y (mm)", ""])
        self.vertex_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.vertex_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.vertex_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.vertex_table.setMaximumHeight(150)
        manual_layout.addWidget(self.vertex_table)

        self.manual_draw_widget.setLayout(manual_layout)
        self.manual_draw_widget.setVisible(False)
        layout.addWidget(self.manual_draw_widget)

        # DXF import controls
        self.dxf_import_widget = QFrame()
        dxf_layout = QHBoxLayout()
        dxf_layout.setContentsMargins(0, 0, 0, 0)

        self.browse_dxf_btn = QPushButton("选择DXF文件")
        self.browse_dxf_btn.clicked.connect(self._on_browse_dxf)
        self.dxf_info_label = QLabel("未选择文件")
        self.dxf_info_label.setStyleSheet("color: gray;")

        dxf_layout.addWidget(self.browse_dxf_btn)
        dxf_layout.addWidget(self.dxf_info_label)
        dxf_layout.addStretch()

        self.dxf_import_widget.setLayout(dxf_layout)
        self.dxf_import_widget.setVisible(False)
        layout.addWidget(self.dxf_import_widget)

        # Common: outline stats
        stats_layout = QHBoxLayout()
        stats_layout.addWidget(QLabel("统计:"))
        self.outline_area_label = QLabel("面积: -- mm²")
        self.outline_dims_label = QLabel("尺寸: --")
        stats_layout.addWidget(self.outline_area_label)
        stats_layout.addWidget(self.outline_dims_label)
        stats_layout.addStretch()
        layout.addLayout(stats_layout)

        group.setLayout(layout)
        return group

    def _create_screw_hole_section(self) -> QGroupBox:
        """Create the screw holes section."""
        group = QGroupBox("螺丝孔")
        layout = QVBoxLayout()
        layout.setSpacing(8)

        # Source selector
        source_layout = QHBoxLayout()
        source_layout.addWidget(QLabel("来源:"))
        self.hole_source_combo = QComboBox()
        self.hole_source_combo.addItems(["从PCB自动识别", "手动放置", "导入"])
        self.hole_source_combo.currentIndexChanged.connect(
            self._on_hole_source_changed
        )
        source_layout.addWidget(self.hole_source_combo)
        source_layout.addStretch()
        layout.addLayout(source_layout)

        # Hole table
        self.hole_table = QTableWidget()
        self.hole_table.setColumnCount(5)
        self.hole_table.setHorizontalHeaderLabels(
            ["X (mm)", "Y (mm)", "直径 (mm)", "来源", ""]
        )
        self.hole_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.hole_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.hole_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.hole_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.hole_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.hole_table.setMaximumHeight(200)
        layout.addWidget(self.hole_table)

        # Controls
        controls_layout = QHBoxLayout()

        # Diameter selector for new holes
        diameter_layout = QHBoxLayout()
        diameter_layout.addWidget(QLabel("新孔直径:"))
        self.hole_diameter_spin = QDoubleSpinBox()
        self.hole_diameter_spin.setRange(1.0, 10.0)
        self.hole_diameter_spin.setSingleStep(0.1)
        self.hole_diameter_spin.setValue(2.5)
        self.hole_diameter_spin.setSuffix(" mm")
        self.hole_diameter_spin.valueChanged.connect(self._on_hole_diameter_changed)
        diameter_layout.addWidget(self.hole_diameter_spin)
        controls_layout.addLayout(diameter_layout)

        self.add_hole_btn = QPushButton("添加孔位")
        self.add_hole_btn.clicked.connect(self._on_add_hole)
        controls_layout.addWidget(self.add_hole_btn)

        self.add_hole_from_pcb_btn = QPushButton("从PCB导入")
        self.add_hole_from_pcb_btn.clicked.connect(self._on_add_holes_from_pcb)
        controls_layout.addWidget(self.add_hole_from_pcb_btn)

        self.clear_holes_btn = QPushButton("全部清除")
        self.clear_holes_btn.clicked.connect(self._on_clear_holes)
        controls_layout.addWidget(self.clear_holes_btn)

        controls_layout.addStretch()
        layout.addLayout(controls_layout)

        group.setLayout(layout)
        return group

    def _on_outline_source_changed(self, index: int):
        """Handle outline source selection change."""
        source = self.outline_source_combo.currentText()

        # Hide all sub-widgets first
        self.auto_outline_info.setVisible(source == "从PCB自动识别")
        self.manual_draw_widget.setVisible(source == "手动绘制")
        self.dxf_import_widget.setVisible(source == "导入DXF")

        # Update button states
        if source == "手动绘制":
            self.start_draw_btn.setEnabled(True)
        else:
            self.start_draw_btn.setEnabled(False)

    def _on_hole_source_changed(self, index: int):
        """Handle screw hole source selection change."""
        source = self.hole_source_combo.currentText()
        # Can add specific behavior per source if needed

    def _on_start_drawing(self):
        """Start outline drawing mode on canvas."""
        self.start_draw_btn.setEnabled(False)
        self.finish_draw_btn.setEnabled(True)
        self.clear_outline_btn.setEnabled(True)
        self.draw_outline_requested.emit()

    def _on_finish_drawing(self):
        """Finish drawing and close the polygon."""
        if len(self.outline_vertices) >= 3:
            self.start_draw_btn.setEnabled(True)
            self.finish_draw_btn.setEnabled(False)
            self.outline_changed.emit(self.outline_vertices, "manual")
            self._update_outline_stats()

    def _on_clear_outline(self):
        """Clear all outline vertices."""
        self.outline_vertices.clear()
        self.vertex_table.setRowCount(0)
        self.start_draw_btn.setEnabled(True)
        self.finish_draw_btn.setEnabled(False)
        self.clear_outline_btn.setEnabled(False)
        self._update_outline_stats()
        self.outline_changed.emit([], "manual")

    def _on_browse_dxf(self):
        """Browse for DXF file to import and parse board outline."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "导入DXF板框", "", "DXF文件 (*.dxf);;所有文件 (*)"
        )
        if not file_path:
            return

        try:
            outline, screw_holes = parse_board_outline_dxf(file_path)
        except Exception as e:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.critical(self, "DXF导入错误", f"解析DXF失败:\n\n{str(e)}")
            return

        if outline and outline.is_valid():
            self.outline_vertices = list(outline.vertices)
            self._update_vertex_table()
            self._update_outline_stats()
            self.outline_changed.emit(self.outline_vertices, "dxf_import")
            self.dxf_info_label.setText(f"{file_path} ({len(outline.vertices)} 个顶点)")
        else:
            self.dxf_info_label.setText(f"{file_path} (未找到板框)")

        # Import screw holes
        if screw_holes:
            for hole in screw_holes:
                self._add_hole_to_table(hole.x, hole.y, hole.diameter, "导入")
                self.screw_holes.append(hole)

        self.import_dxf_requested.emit()

    def _on_add_hole(self):
        """Add a new screw hole (enters placement mode)."""
        self.place_hole_requested.emit()

    def _on_add_holes_from_pcb(self):
        """Add screw holes detected from PCB."""
        if self.pcb_data and self.pcb_data.screw_holes:
            for hole in self.pcb_data.screw_holes:
                self._add_hole_to_table(hole.x, hole.y, hole.diameter, "自动")
                self.screw_holes.append(hole)
            self.hole_added.emit(
                self.pcb_data.screw_holes[0].x,
                self.pcb_data.screw_holes[0].y,
                self.pcb_data.screw_holes[0].diameter
            )

    def _on_clear_holes(self):
        """Clear all screw holes."""
        self.screw_holes.clear()
        self.hole_table.setRowCount(0)

    def _on_hole_diameter_changed(self, value: float):
        """Update default hole diameter."""
        self.current_hole_diameter = value

    def set_pcb_data(self, pcb: PCBData):
        """Load auto-detected PCB data."""
        self.pcb_data = pcb

        # Update outline info
        if pcb.board_outline and pcb.board_outline.vertices:
            vertices = pcb.board_outline.vertices
            perimeter = self._calculate_perimeter(vertices)
            self.auto_outline_info.setText(
                f"已识别: {len(vertices)} 个顶点, 周长: {perimeter:.2f} mm"
            )
            self.outline_vertices = vertices
            self._update_vertex_table()
            self._update_outline_stats()
            self.outline_changed.emit(vertices, "pcb")
        else:
            self.auto_outline_info.setText("PCB中未检测到板框")

        # Update screw holes
        if pcb.screw_holes:
            for hole in pcb.screw_holes:
                self._add_hole_to_table(hole.x, hole.y, hole.diameter, "自动")
                self.screw_holes.append(hole)

    def get_board_outline(self) -> BoardOutline:
        """Return current board outline."""
        return BoardOutline(vertices=self.outline_vertices)

    def get_screw_holes(self) -> list[ScrewHole]:
        """Return current screw holes."""
        return self.screw_holes

    def add_outline_vertex(self, x: float, y: float):
        """Add a vertex from canvas drawing mode."""
        self.outline_vertices.append((x, y))
        self._update_vertex_table()

    def add_hole(self, x: float, y: float):
        """Add a screw hole from canvas placement mode."""
        self._add_hole_to_table(x, y, self.current_hole_diameter, "手动")
        hole = ScrewHole(x=x, y=y, diameter=self.current_hole_diameter)
        self.screw_holes.append(hole)
        self.hole_added.emit(x, y, self.current_hole_diameter)

    def _update_vertex_table(self):
        """Update the vertex table with current vertices."""
        self.vertex_table.setRowCount(len(self.outline_vertices))
        for i, (x, y) in enumerate(self.outline_vertices):
            # X coordinate
            x_spin = QDoubleSpinBox()
            x_spin.setRange(-500.0, 500.0)
            x_spin.setSingleStep(0.1)
            x_spin.setDecimals(2)
            x_spin.setValue(x)
            x_spin.valueChanged.connect(
                lambda val, idx=i: self._on_vertex_changed(idx, val, None)
            )
            self.vertex_table.setCellWidget(i, 0, x_spin)

            # Y coordinate
            y_spin = QDoubleSpinBox()
            y_spin.setRange(-500.0, 500.0)
            y_spin.setSingleStep(0.1)
            y_spin.setDecimals(2)
            y_spin.setValue(y)
            y_spin.valueChanged.connect(
                lambda val, idx=i: self._on_vertex_changed(idx, None, val)
            )
            self.vertex_table.setCellWidget(i, 1, y_spin)

            # Remove button
            remove_btn = QPushButton("删除")
            remove_btn.clicked.connect(lambda checked, idx=i: self._on_remove_vertex(idx))
            self.vertex_table.setCellWidget(i, 2, remove_btn)

    def _on_vertex_changed(self, index: int, x: float = None, y: float = None):
        """Handle vertex coordinate change."""
        if x is not None:
            self.outline_vertices[index] = (x, self.outline_vertices[index][1])
        if y is not None:
            self.outline_vertices[index] = (self.outline_vertices[index][0], y)
        self.outline_changed.emit(self.outline_vertices, "manual")
        self._update_outline_stats()

    def _on_remove_vertex(self, index: int):
        """Remove a vertex."""
        if index < len(self.outline_vertices):
            self.outline_vertices.pop(index)
            self._update_vertex_table()
            self.outline_changed.emit(self.outline_vertices, "manual")
            self._update_outline_stats()

    def _add_hole_to_table(self, x: float, y: float, diameter: float, source: str):
        """Add a screw hole to the table."""
        row = self.hole_table.rowCount()
        self.hole_table.insertRow(row)

        # X coordinate
        x_spin = QDoubleSpinBox()
        x_spin.setRange(-500.0, 500.0)
        x_spin.setSingleStep(0.1)
        x_spin.setDecimals(2)
        x_spin.setValue(x)
        x_spin.valueChanged.connect(
            lambda val, idx=row: self._on_hole_coord_changed(idx, val, None)
        )
        self.hole_table.setCellWidget(row, 0, x_spin)

        # Y coordinate
        y_spin = QDoubleSpinBox()
        y_spin.setRange(-500.0, 500.0)
        y_spin.setSingleStep(0.1)
        y_spin.setDecimals(2)
        y_spin.setValue(y)
        y_spin.valueChanged.connect(
            lambda val, idx=row: self._on_hole_coord_changed(idx, None, val)
        )
        self.hole_table.setCellWidget(row, 1, y_spin)

        # Diameter
        d_spin = QDoubleSpinBox()
        d_spin.setRange(1.0, 10.0)
        d_spin.setSingleStep(0.1)
        d_spin.setDecimals(1)
        d_spin.setValue(diameter)
        d_spin.valueChanged.connect(
            lambda val, idx=row: self._on_hole_diameter_update(idx, val)
        )
        self.hole_table.setCellWidget(row, 2, d_spin)

        # Source
        source_item = QTableWidgetItem(source)
        source_item.setFlags(source_item.flags() & ~Qt.ItemIsEditable)
        self.hole_table.setItem(row, 3, source_item)

        # Remove button
        remove_btn = QPushButton("删除")
        remove_btn.clicked.connect(lambda checked, idx=row: self._on_remove_hole(idx))
        self.hole_table.setCellWidget(row, 4, remove_btn)

    def _on_hole_coord_changed(self, index: int, x: float = None, y: float = None):
        """Handle screw hole coordinate change."""
        if index < len(self.screw_holes):
            hole = self.screw_holes[index]
            if x is not None:
                hole.x = x
            if y is not None:
                hole.y = y
            self.hole_updated.emit(index, hole.x, hole.y, hole.diameter)

    def _on_hole_diameter_update(self, index: int, diameter: float):
        """Handle screw hole diameter change."""
        if index < len(self.screw_holes):
            self.screw_holes[index].diameter = diameter
            hole = self.screw_holes[index]
            self.hole_updated.emit(index, hole.x, hole.y, hole.diameter)

    def _on_remove_hole(self, index: int):
        """Remove a screw hole."""
        if index < len(self.screw_holes):
            self.screw_holes.pop(index)
            self.hole_table.removeRow(index)
            # Update indices for remaining holes
            for i in range(index, self.hole_table.rowCount()):
                for col in range(3):
                    widget = self.hole_table.cellWidget(i, col)
                    if widget and hasattr(widget, 'valueChanged'):
                        # Disconnect and reconnect with new index
                        widget.blockSignals(True)
            self.hole_removed.emit(index)

    def _update_outline_stats(self):
        """Update outline statistics display."""
        if len(self.outline_vertices) >= 3:
            area = self._calculate_area(self.outline_vertices)
            dims = self._calculate_dimensions(self.outline_vertices)
            self.outline_area_label.setText(f"面积: {area:.2f} mm²")
            self.outline_dims_label.setText(
                f"尺寸: {dims[0]:.2f} × {dims[1]:.2f} mm"
            )
        else:
            self.outline_area_label.setText("面积: -- mm²")
            self.outline_dims_label.setText("尺寸: --")

    def _calculate_perimeter(self, vertices: list) -> float:
        """Calculate perimeter of polygon."""
        if len(vertices) < 2:
            return 0.0
        perimeter = 0.0
        for i in range(len(vertices)):
            x1, y1 = vertices[i]
            x2, y2 = vertices[(i + 1) % len(vertices)]
            perimeter += math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
        return perimeter

    def _calculate_area(self, vertices: list) -> float:
        """Calculate area of polygon using shoelace formula."""
        if len(vertices) < 3:
            return 0.0
        area = 0.0
        for i in range(len(vertices)):
            x1, y1 = vertices[i]
            x2, y2 = vertices[(i + 1) % len(vertices)]
            area += x1 * y2 - x2 * y1
        return abs(area) / 2.0

    def _calculate_dimensions(self, vertices: list) -> tuple:
        """Calculate width and height of bounding box."""
        if not vertices:
            return (0.0, 0.0)
        xs = [v[0] for v in vertices]
        ys = [v[1] for v in vertices]
        width = max(xs) - min(xs)
        height = max(ys) - min(ys)
        return (width, height)
