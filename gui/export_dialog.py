"""Export dialog for generating DXF files of keyboard layers."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QLineEdit, QCheckBox, QGroupBox, QDoubleSpinBox, QFileDialog,
    QProgressBar, QScrollArea, QWidget, QGridLayout, QMessageBox
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

from models.layer_config import LayerConfigSet, FoamLayerConfig, DEFAULT_LAYERS
from models.pcb_data import PCBData
from models.layout_group import LayoutConfig
from models.avoidance import AvoidancePolygon

from generators.plate_generator import generate_plate
from generators.foam_generator import generate_foam_layer


class LayerEditDialog(QDialog):
    """Dialog for editing a single layer's parameters."""

    def __init__(self, layer_config: FoamLayerConfig, parent=None):
        super().__init__(parent)
        self._layer_config = layer_config
        self.setWindowTitle(f"Edit Layer: {layer_config.name_cn}")
        self.setModal(True)
        self.setMinimumWidth(400)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Thickness
        thickness_layout = QHBoxLayout()
        thickness_layout.addWidget(QLabel("Thickness (mm):"))
        self._thickness_spin = QDoubleSpinBox()
        self._thickness_spin.setRange(0.1, 50.0)
        self._thickness_spin.setSingleStep(0.1)
        self._thickness_spin.setDecimals(2)
        self._thickness_spin.setValue(self._layer_config.thickness)
        thickness_layout.addWidget(self._thickness_spin)
        layout.addLayout(thickness_layout)

        # Default avoidance expansion
        expansion_layout = QHBoxLayout()
        expansion_layout.addWidget(QLabel("Avoidance Expansion (mm):"))
        self._expansion_spin = QDoubleSpinBox()
        self._expansion_spin.setRange(0.0, 50.0)
        self._expansion_spin.setSingleStep(0.1)
        self._expansion_spin.setDecimals(2)
        self._expansion_spin.setValue(self._layer_config.default_avoidance_expansion)
        expansion_layout.addWidget(self._expansion_spin)
        layout.addLayout(expansion_layout)

        # Cutout size
        cutout_layout = QHBoxLayout()
        cutout_layout.addWidget(QLabel("Cutout Size (mm):"))
        self._cutout_spin = QDoubleSpinBox()
        self._cutout_spin.setRange(0.0, 100.0)
        self._cutout_spin.setSingleStep(0.5)
        self._cutout_spin.setDecimals(2)
        self._cutout_spin.setValue(self._layer_config.cutout_size)
        cutout_layout.addWidget(self._cutout_spin)
        layout.addLayout(cutout_layout)

        # Note about cutout type
        note_label = QLabel(f"Cutout Type: {self._layer_config.cutout_type}")
        note_label.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(note_label)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def get_updated_config(self) -> FoamLayerConfig:
        """Return a new config with updated values."""
        return FoamLayerConfig(
            name=self._layer_config.name,
            name_cn=self._layer_config.name_cn,
            thickness=self._thickness_spin.value(),
            cutout_type=self._layer_config.cutout_type,
            cutout_size=self._cutout_spin.value(),
            default_avoidance_expansion=self._expansion_spin.value()
        )


class ExportDialog(QDialog):
    """Dialog for exporting keyboard layers as DXF files."""

    # Signals
    export_progress = pyqtSignal(str, int, int)  # layer_name, current, total

    def __init__(
        self,
        pcb_data: PCBData,
        layout_config: LayoutConfig,
        avoidance_polygons: list[AvoidancePolygon],
        layer_config_set: Optional[LayerConfigSet] = None,
        parent=None
    ):
        super().__init__(parent)
        self._pcb_data = pcb_data
        self._layout_config = layout_config
        self._avoidance_polygons = avoidance_polygons
        self._layer_config_set = layer_config_set or LayerConfigSet()
        self._layer_configs: dict[str, FoamLayerConfig] = {}
        self._is_exporting = False

        # Build config lookup
        for layer in self._layer_config_set.layers:
            self._layer_configs[layer.name] = layer

        self.setWindowTitle("Export Layers as DXF")
        self.setMinimumSize(600, 500)
        self._init_ui()

    def _init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Layer selection group
        layer_group = self._create_layer_selection_group()
        layout.addWidget(layer_group)

        # Output settings group
        output_group = self._create_output_settings_group()
        layout.addWidget(output_group)

        # Progress section (hidden initially)
        self._progress_widget = self._create_progress_widget()
        self._progress_widget.setVisible(False)
        layout.addWidget(self._progress_widget)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._export_btn = QPushButton("Export")
        self._export_btn.setMinimumWidth(100)
        self._export_btn.clicked.connect(self._on_export_clicked)
        btn_layout.addWidget(self._export_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

    def _create_layer_selection_group(self) -> QGroupBox:
        """Create the layer selection group box."""
        group = QGroupBox("Select Layers to Export")
        layout = QVBoxLayout(group)

        # Scroll area for layers
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(250)

        scroll_widget = QWidget()
        scroll_layout = QGridLayout(scroll_widget)
        scroll_layout.setSpacing(8)

        self._layer_checkboxes: dict[str, QCheckBox] = {}
        self._layer_edit_buttons: dict[str, QPushButton] = {}

        # Create rows for each layer
        for row, layer in enumerate(DEFAULT_LAYERS):
            # Checkbox
            checkbox = QCheckBox(f"{layer.name_cn} ({layer.name}) — {layer.thickness}mm")
            checkbox.setChecked(False)  # Default: ALL UNCHECKED
            scroll_layout.addWidget(checkbox, row, 0)
            self._layer_checkboxes[layer.name] = checkbox

            # Edit button
            edit_btn = QPushButton("Edit")
            edit_btn.setMaximumWidth(80)
            edit_btn.clicked.connect(lambda checked, l=layer: self._on_edit_layer(l))
            scroll_layout.addWidget(edit_btn, row, 1)
            self._layer_edit_buttons[layer.name] = edit_btn

        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

        # Select/Deselect all buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self._on_select_all)
        btn_layout.addWidget(select_all_btn)

        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.clicked.connect(self._on_deselect_all)
        btn_layout.addWidget(deselect_all_btn)

        layout.addLayout(btn_layout)

        return group

    def _create_output_settings_group(self) -> QGroupBox:
        """Create the output settings group box."""
        group = QGroupBox("Output Settings")
        layout = QGridLayout(group)
        layout.setSpacing(8)

        # Output directory
        layout.addWidget(QLabel("Output Directory:"), 0, 0)
        dir_layout = QHBoxLayout()

        self._output_dir_edit = QLineEdit()
        self._output_dir_edit.setPlaceholderText("Select output directory...")
        dir_layout.addWidget(self._output_dir_edit)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._on_browse_directory)
        dir_layout.addWidget(browse_btn)

        layout.addLayout(dir_layout, 0, 1)

        # File naming pattern
        layout.addWidget(QLabel("File Name Pattern:"), 1, 0)
        self._naming_pattern_edit = QLineEdit("{project}_{layer}.dxf")
        self._naming_pattern_edit.setToolTip(
            "Use {project} for project name, {layer} for layer name\n"
            "Example: mykb_plate.dxf, mykb_foam.dxf"
        )
        layout.addWidget(self._naming_pattern_edit, 1, 1)

        # Project name
        layout.addWidget(QLabel("Project Name:"), 2, 0)
        self._project_name_edit = QLineEdit("keyboard")
        layout.addWidget(self._project_name_edit, 2, 1)

        return group

    def _create_progress_widget(self) -> QWidget:
        """Create the progress display widget."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Progress bar
        self._progress_bar = QProgressBar()
        self._progress_bar.setMinimum(0)
        self._progress_bar.setMaximum(100)
        layout.addWidget(self._progress_bar)

        # Current layer label
        self._current_layer_label = QLabel()
        self._current_layer_label.setAlignment(Qt.AlignCenter)
        font = self._current_layer_label.font()
        font.setBold(True)
        self._current_layer_label.setFont(font)
        layout.addWidget(self._current_layer_label)

        # Cancel export button
        self._cancel_export_btn = QPushButton("Cancel Export")
        self._cancel_export_btn.clicked.connect(self._on_cancel_export)
        layout.addWidget(self._cancel_export_btn)

        return widget

    def _on_select_all(self):
        """Select all layer checkboxes."""
        for checkbox in self._layer_checkboxes.values():
            checkbox.setChecked(True)

    def _on_deselect_all(self):
        """Deselect all layer checkboxes."""
        for checkbox in self._layer_checkboxes.values():
            checkbox.setChecked(False)

    def _on_edit_layer(self, layer: FoamLayerConfig):
        """Handle edit button click for a layer."""
        dialog = LayerEditDialog(layer, self)
        if dialog.exec_() == QDialog.Accepted:
            updated_config = dialog.get_updated_config()
            self._layer_configs[updated_config.name] = updated_config

            # Update checkbox text with new thickness
            checkbox = self._layer_checkboxes[layer.name]
            checkbox.setText(
                f"{updated_config.name_cn} ({updated_config.name}) — {updated_config.thickness}mm"
            )

    def _on_browse_directory(self):
        """Handle browse button click."""
        current_dir = self._output_dir_edit.text()
        if not current_dir or not os.path.exists(current_dir):
            current_dir = os.path.expanduser("~")

        directory = QFileDialog.getExistingDirectory(
            self, "Select Output Directory", current_dir
        )

        if directory:
            self._output_dir_edit.setText(directory)

    def _on_export_clicked(self):
        """Handle export button click."""
        # Validation
        selected_layers = self.get_selected_layers()
        if not selected_layers:
            QMessageBox.warning(self, "No Layers Selected", "Please select at least one layer to export.")
            return

        output_dir = self._output_dir_edit.text()
        if not output_dir or not os.path.isdir(output_dir):
            QMessageBox.warning(self, "Invalid Directory", "Please select a valid output directory.")
            return

        project_name = self._project_name_edit.text().strip()
        if not project_name:
            QMessageBox.warning(self, "Missing Project Name", "Please enter a project name.")
            return

        # Start export
        self._start_export(selected_layers, output_dir, project_name)

    def _start_export(self, layer_names: list[str], output_dir: str, project_name: str):
        """Start the export process."""
        self._is_exporting = True

        # Show progress widget, hide export button
        self._progress_widget.setVisible(True)
        self._export_btn.setEnabled(False)

        # Process each layer
        total = len(layer_names)
        success_count = 0
        failed_layers = []

        for i, layer_name in enumerate(layer_names):
            if not self._is_exporting:
                break

            # Update progress
            progress = int((i / total) * 100)
            self._progress_bar.setValue(progress)

            layer_config = self._layer_configs.get(layer_name)
            if not layer_config:
                failed_layers.append((layer_name, "Layer config not found"))
                continue

            self._current_layer_label.setText(f"Exporting: {layer_config.name_cn}")

            # Generate filename
            pattern = self._naming_pattern_edit.text()
            filename = pattern.replace("{project}", project_name).replace("{layer}", layer_name)
            output_path = os.path.join(output_dir, filename)

            # Generate the appropriate file
            try:
                if layer_name == "plate":
                    generate_plate(
                        self._pcb_data,
                        self._layout_config,
                        layer_config,
                        self._avoidance_polygons,
                        output_path
                    )
                else:
                    generate_foam_layer(
                        self._pcb_data,
                        self._layout_config,
                        layer_config,
                        self._avoidance_polygons,
                        output_path
                    )
                success_count += 1
            except Exception as e:
                failed_layers.append((layer_name, str(e)))

        # Complete
        self._progress_bar.setValue(100)
        self._is_exporting = False

        # Show summary
        if failed_layers:
            error_msg = "Exported {}/{} layers successfully.\n\nFailed layers:\n{}".format(
                success_count,
                total,
                "\n".join(f"  - {name}: {err}" for name, err in failed_layers)
            )
            QMessageBox.warning(self, "Export Completed with Errors", error_msg)
        else:
            QMessageBox.information(
                self,
                "Export Successful",
                f"Exported {success_count}/{total} layers successfully."
            )

        # Reset UI
        self._progress_widget.setVisible(False)
        self._export_btn.setEnabled(True)

        # Close dialog on success
        if not failed_layers:
            self.accept()

    def _on_cancel_export(self):
        """Handle cancel export button click."""
        self._is_exporting = False
        self._current_layer_label.setText("Cancelling...")
        self._cancel_export_btn.setEnabled(False)

    def get_selected_layers(self) -> list[str]:
        """Get list of selected layer names."""
        selected = []
        for layer_name, checkbox in self._layer_checkboxes.items():
            if checkbox.isChecked():
                selected.append(layer_name)
        return selected

    def set_output_dir(self, path: str):
        """Set the output directory."""
        self._output_dir_edit.setText(path)
