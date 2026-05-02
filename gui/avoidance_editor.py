from __future__ import annotations
from typing import List, Optional
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QPushButton,
    QLabel, QLineEdit, QComboBox, QTableWidget, QTableWidgetItem,
    QDoubleSpinBox, QHeaderView, QSplitter, QGroupBox, QAbstractItemView,
    QListWidgetItem, QFrame
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QIcon, QColor

from models.avoidance import AvoidancePolygon
from models.layer_config import LayerConfigSet, DEFAULT_LAYERS


class AvoidanceEditor(QWidget):
    """Panel for managing IC/component avoidance polygons."""

    # Signals
    polygon_confirmed = pyqtSignal(int)  # index
    polygon_deleted = pyqtSignal(int)  # index
    polygon_added = pyqtSignal(list, str)  # vertices, source
    polygon_updated = pyqtSignal(int, object)  # index, AvoidancePolygon
    draw_mode_requested = pyqtSignal(str)  # "rect" or "polygon"

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._polygons: List[AvoidancePolygon] = []
        self._selected_index: Optional[int] = None
        self._layer_configs = LayerConfigSet()

        self._init_ui()

    def _init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # Main splitter for resizable panels
        splitter = QSplitter(Qt.Vertical)
        layout.addWidget(splitter)

        # Top: List + Actions
        top_panel = self._create_list_panel()
        splitter.addWidget(top_panel)

        # Bottom: Properties
        bottom_panel = self._create_properties_panel()
        splitter.addWidget(bottom_panel)

        # Set initial splitter sizes (60% list, 40% properties)
        splitter.setSizes([300, 200])

    def _create_list_panel(self) -> QWidget:
        """Create the avoidance list and action buttons panel."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Label
        label = QLabel("避空区域")
        label.setStyleSheet("font-weight: bold;")
        layout.addWidget(label)

        # List widget
        self._list_widget = QListWidget()
        self._list_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list_widget.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list_widget)

        # Action buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(4)

        self._btn_confirm = QPushButton("确认")
        self._btn_confirm.clicked.connect(self._on_confirm_clicked)
        btn_layout.addWidget(self._btn_confirm)

        self._btn_delete = QPushButton("删除")
        self._btn_delete.clicked.connect(self._on_delete_clicked)
        btn_layout.addWidget(self._btn_delete)

        self._btn_add_rect = QPushButton("添加矩形")
        self._btn_add_rect.clicked.connect(lambda: self.draw_mode_requested.emit("rect"))
        btn_layout.addWidget(self._btn_add_rect)

        self._btn_add_poly = QPushButton("添加多边形")
        self._btn_add_poly.clicked.connect(lambda: self.draw_mode_requested.emit("polygon"))
        btn_layout.addWidget(self._btn_add_poly)

        self._btn_edit = QPushButton("编辑")
        self._btn_edit.clicked.connect(self._on_edit_clicked)
        btn_layout.addWidget(self._btn_edit)

        layout.addLayout(btn_layout)
        return panel

    def _create_properties_panel(self) -> QWidget:
        """Create the properties panel for selected polygon."""
        panel = QGroupBox("属性")
        layout = QVBoxLayout(panel)
        layout.setSpacing(6)

        # Label field
        label_layout = QHBoxLayout()
        label_layout.addWidget(QLabel("标签:"))
        self._label_edit = QLineEdit()
        self._label_edit.editingFinished.connect(self._on_properties_changed)
        label_layout.addWidget(self._label_edit)
        layout.addLayout(label_layout)

        # Confidence field
        conf_layout = QHBoxLayout()
        conf_layout.addWidget(QLabel("置信度:"))
        self._confidence_combo = QComboBox()
        self._confidence_combo.addItem("疑似", "suspected")
        self._confidence_combo.addItem("已确认", "confirmed")
        self._confidence_combo.currentTextChanged.connect(self._on_properties_changed)
        conf_layout.addWidget(self._confidence_combo)
        layout.addLayout(conf_layout)

        # Layer expansion table
        layout.addWidget(QLabel("图层扩展 (mm):"))
        self._expansion_table = QTableWidget()
        self._expansion_table.setColumnCount(2)
        self._expansion_table.setHorizontalHeaderLabels(["图层", "扩展值"])
        self._expansion_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._expansion_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._expansion_table.verticalHeader().setVisible(False)
        self._expansion_table.itemChanged.connect(self._on_expansion_changed)
        layout.addWidget(self._expansion_table)

        # Vertices table
        layout.addWidget(QLabel("顶点:"))
        self._vertices_table = QTableWidget()
        self._vertices_table.setColumnCount(2)
        self._vertices_table.setHorizontalHeaderLabels(["X (mm)", "Y (mm)"])
        self._vertices_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._vertices_table.verticalHeader().setVisible(False)
        self._vertices_table.itemChanged.connect(self._on_vertex_changed)
        layout.addWidget(self._vertices_table)

        # Initialize expansion table rows
        self._init_expansion_table()

        # Initially disable properties
        self._set_properties_enabled(False)

        return panel

    def _init_expansion_table(self):
        """Initialize the layer expansion table with default layers."""
        self._expansion_table.setRowCount(len(DEFAULT_LAYERS))
        for row, layer in enumerate(DEFAULT_LAYERS):
            # Layer name (read-only)
            name_item = QTableWidgetItem(f"{layer.name_cn} ({layer.name})")
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            self._expansion_table.setItem(row, 0, name_item)

            # Expansion value (editable)
            spin_box = QDoubleSpinBox()
            spin_box.setRange(0.0, 50.0)
            spin_box.setSingleStep(0.1)
            spin_box.setDecimals(2)
            spin_box.setValue(layer.default_avoidance_expansion)
            spin_box.setSpecialValueText("默认")
            self._expansion_table.setCellWidget(row, 1, spin_box)

    def _set_properties_enabled(self, enabled: bool):
        """Enable or disable all properties widgets."""
        self._label_edit.setEnabled(enabled)
        self._confidence_combo.setEnabled(enabled)
        self._expansion_table.setEnabled(enabled)
        self._vertices_table.setEnabled(enabled)

    def _refresh_list(self):
        """Refresh the avoidance list display."""
        self._list_widget.clear()
        for i, poly in enumerate(self._polygons):
            item = QListWidgetItem()
            conf_display = "已确认" if poly.confidence == "confirmed" else "疑似"
            text = f"{poly.label or '未命名'} [{conf_display}] ({poly.source})"
            item.setText(text)

            # Color-coded icon based on confidence
            if poly.confidence == "confirmed":
                icon_color = QColor(0, 180, 0)  # Green
            else:
                icon_color = QColor(220, 180, 0)  # Yellow

            # Create a simple colored pixmap as icon
            pixmap = QIcon().pixmap(16, 16)
            pixmap.fill(icon_color)
            item.setIcon(QIcon(pixmap))

            self._list_widget.addItem(item)

    def _refresh_properties(self):
        """Refresh the properties panel for the selected polygon."""
        if self._selected_index is None or self._selected_index >= len(self._polygons):
            self._set_properties_enabled(False)
            self._label_edit.clear()
            self._confidence_combo.setCurrentIndex(0)
            return

        poly = self._polygons[self._selected_index]
        self._set_properties_enabled(True)

        # Block signals during refresh
        self._label_edit.blockSignals(True)
        self._confidence_combo.blockSignals(True)
        self._expansion_table.blockSignals(True)
        self._vertices_table.blockSignals(True)

        try:
            # Label
            self._label_edit.setText(poly.label)

            # Confidence
            for i in range(self._confidence_combo.count()):
                if self._confidence_combo.itemData(i) == poly.confidence:
                    self._confidence_combo.setCurrentIndex(i)
                    break

            # Layer expansions
            for row, layer in enumerate(DEFAULT_LAYERS):
                spin_box = self._expansion_table.cellWidget(row, 1)
                if spin_box:
                    spin_box.blockSignals(True)
                    expansion = poly.layer_expansions.get(layer.name, layer.default_avoidance_expansion)
                    spin_box.setValue(expansion)
                    spin_box.blockSignals(False)

            # Vertices
            self._vertices_table.setRowCount(len(poly.vertices))
            for row, (x, y) in enumerate(poly.vertices):
                x_item = QTableWidgetItem(f"{x:.3f}")
                y_item = QTableWidgetItem(f"{y:.3f}")
                x_item.setData(Qt.UserRole, x)  # Store raw value
                y_item.setData(Qt.UserRole, y)
                self._vertices_table.setItem(row, 0, x_item)
                self._vertices_table.setItem(row, 1, y_item)

        finally:
            self._label_edit.blockSignals(False)
            self._confidence_combo.blockSignals(False)
            self._expansion_table.blockSignals(False)
            self._vertices_table.blockSignals(False)

    def _on_item_clicked(self, item: QListWidgetItem):
        """Handle item click in the list."""
        self._selected_index = self._list_widget.row(item)
        self._refresh_properties()
        # Emit signal to highlight on canvas (handled by parent)
        # Could add a signal here if needed

    def _on_confirm_clicked(self):
        """Handle confirm button click."""
        if self._selected_index is not None and self._selected_index < len(self._polygons):
            poly = self._polygons[self._selected_index]
            poly.confidence = "confirmed"
            self._refresh_list()
            self._refresh_properties()
            self.polygon_confirmed.emit(self._selected_index)

    def _on_delete_clicked(self):
        """Handle delete button click."""
        if self._selected_index is not None and self._selected_index < len(self._polygons):
            self.polygon_deleted.emit(self._selected_index)
            # Remove from list
            del self._polygons[self._selected_index]
            self._selected_index = None
            self._refresh_list()
            self._refresh_properties()

    def _on_edit_clicked(self):
        """Handle edit button click - enable vertex editing mode."""
        # This would signal the canvas to enable dragging mode
        # For now, just emit a generic edit signal
        if self._selected_index is not None:
            self.draw_mode_requested.emit("edit")

    def _on_properties_changed(self):
        """Handle changes to label or confidence."""
        if self._selected_index is None or self._selected_index >= len(self._polygons):
            return

        poly = self._polygons[self._selected_index]
        poly.label = self._label_edit.text()
        poly.confidence = self._confidence_combo.currentData() or self._confidence_combo.currentText()

        self._refresh_list()
        self.polygon_updated.emit(self._selected_index, poly)

    def _on_expansion_changed(self, item: QTableWidgetItem):
        """Handle changes to layer expansion values."""
        if self._selected_index is None or self._selected_index >= len(self._polygons):
            return

        row = item.row()
        if row < 0 or row >= len(DEFAULT_LAYERS):
            return

        layer = DEFAULT_LAYERS[row]
        spin_box = self._expansion_table.cellWidget(row, 1)
        if spin_box:
            value = spin_box.value()
            poly = self._polygons[self._selected_index]
            poly.layer_expansions[layer.name] = value
            self.polygon_updated.emit(self._selected_index, poly)

    def _on_vertex_changed(self, item: QTableWidgetItem):
        """Handle changes to vertex coordinates."""
        if self._selected_index is None or self._selected_index >= len(self._polygons):
            return

        row = item.row()
        col = item.column()
        poly = self._polygons[self._selected_index]

        if row < 0 or row >= len(poly.vertices):
            return

        try:
            value = float(item.text())
            x, y = poly.vertices[row]
            if col == 0:
                x = value
            else:
                y = value
            poly.vertices[row] = (x, y)
            item.setData(Qt.UserRole, value)
            self.polygon_updated.emit(self._selected_index, poly)
        except ValueError:
            # Invalid input, revert to stored value
            item.setText(f"{poly.vertices[row][col]:.3f}")

    def set_polygons(self, polygons: List[AvoidancePolygon]):
        """Set the list of avoidance polygons."""
        self._polygons = polygons
        self._selected_index = None
        self._refresh_list()
        self._refresh_properties()

    def get_polygons(self) -> List[AvoidancePolygon]:
        """Get the current list of avoidance polygons."""
        return self._polygons

    def add_polygon_from_canvas(self, vertices: List[tuple[float, float]], source: str = "manual"):
        """Add a new polygon from canvas drawing."""
        poly = AvoidancePolygon(
            vertices=vertices,
            confidence="suspected" if source == "auto" else "confirmed",
            source=source,
            label=f"多边形 {len(self._polygons) + 1}"
        )
        self._polygons.append(poly)
        self._refresh_list()
        self.polygon_added.emit(vertices, source)

    def select_polygon(self, index: int):
        """Select a polygon by index."""
        if 0 <= index < len(self._polygons):
            self._list_widget.setCurrentRow(index)
            self._selected_index = index
            self._refresh_properties()

    def get_selected_index(self) -> Optional[int]:
        """Get the currently selected polygon index."""
        return self._selected_index
