"""
Main Window for Keyboard PCB Tool Application.

This is the central QMainWindow that integrates all GUI panels with a tabbed
workflow on the right dock, a PCB canvas in the center, and toolbar/menu controls.
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QDockWidget, QTabWidget, QAction, QToolBar,
    QFileDialog, QMessageBox, QStatusBar, QLabel,
    QApplication, QToolButton, QButtonGroup
)
from PyQt5.QtCore import Qt, pyqtSignal, QSize
from PyQt5.QtGui import QIcon, QFont, QKeySequence

from models.pcb_data import PCBData
from models.footprint_rules import FootprintRuleSet
from models.layout_group import LayoutConfig
from models.layer_config import LayerConfigSet, DEFAULT_LAYERS
from models.avoidance import AvoidancePolygon

from parsers.altium_parser import AltiumASCIIParser, validate_ascii_pcb
from avoidance.detector import detect_suspected_avoidance

from gui.pcb_canvas import (
    PcbCanvas, MODE_SELECT, MODE_DRAW_RECT, MODE_DRAW_POLYGON,
    MODE_PLACE_HOLE, MODE_DRAW_OUTLINE
)
from gui.footprint_rules import FootprintRulesPanel
from gui.avoidance_editor import AvoidanceEditor
from gui.layout_panel import LayoutPanel
from gui.outline_editor import OutlineEditor
from gui.export_dialog import ExportDialog


@dataclass
class AppState:
    """Application state for save/load."""
    pcb_data: Optional[PCBData] = None
    rule_set: FootprintRuleSet = field(default_factory=FootprintRuleSet)
    layout_config: Optional[LayoutConfig] = None
    layer_config: LayerConfigSet = field(default_factory=lambda: LayerConfigSet(layers=DEFAULT_LAYERS))
    avoidance_polygons: list[AvoidancePolygon] = field(default_factory=list)
    project_path: Optional[str] = None
    modified: bool = False


class MainWindow(QMainWindow):
    """Main application window for Keyboard PCB Tool."""

    def __init__(self):
        super().__init__()

        # App state
        self.state = AppState()

        # Main components
        self.canvas: Optional[PcbCanvas] = None
        self.footprint_panel: Optional[FootprintRulesPanel] = None
        self.avoidance_panel: Optional[AvoidanceEditor] = None
        self.layout_panel: Optional[LayoutPanel] = None
        self.outline_panel: Optional[OutlineEditor] = None
        self.export_dialog: Optional[ExportDialog] = None

        # Toolbar mode button group
        self.mode_button_group: Optional[QButtonGroup] = None

        # Status bar labels
        self.status_mode: Optional[QLabel] = None
        self.status_cursor: Optional[QLabel] = None
        self.status_switches: Optional[QLabel] = None
        self.status_zoom: Optional[QLabel] = None

        self._init_ui()
        self._create_menu_bar()
        self._create_toolbar()
        self._create_status_bar()

    def _init_ui(self):
        """Initialize the main window UI layout."""
        self.setWindowTitle("Keyboard PCB Tool")
        self.resize(1400, 900)

        # Central widget: PCB canvas
        self.canvas = PcbCanvas(self)
        self.setCentralWidget(self.canvas)

        # Connect canvas signals
        self.canvas.signal_component_clicked.connect(self._on_component_clicked)
        self.canvas.signal_cursor_position.connect(self._on_cursor_position_changed)
        self.canvas.signal_zoom_changed.connect(self._on_zoom_changed)
        self.canvas.signal_avoidance_created.connect(self._on_avoidance_created)
        self.canvas.signal_hole_placed.connect(self._on_hole_placed)
        self.canvas.signal_outline_point_added.connect(self._on_outline_point_added)

        # Right dock with tabbed panels
        self._create_right_dock()

    def _create_right_dock(self):
        """Create the right dock widget with tabbed panels."""
        dock = QDockWidget("Panels", self)
        dock.setFeatures(QDockWidget.NoDockWidgetFeatures)  # Fixed position

        # Tab widget
        tab_widget = QTabWidget()
        tab_widget.setTabPosition(QTabWidget.North)
        tab_widget.setDocumentMode(True)

        # Tab 1: Footprint Rules
        self.footprint_panel = FootprintRulesPanel(parent=self)
        self.footprint_panel.rules_applied.connect(self._on_rules_applied)
        tab_widget.addTab(self.footprint_panel, "Footprint Rules")

        # Tab 2: Avoidance Editor
        self.avoidance_panel = AvoidanceEditor(parent=self)
        self.avoidance_panel.polygon_confirmed.connect(self._on_avoidance_confirmed)
        self.avoidance_panel.polygon_deleted.connect(self._on_avoidance_deleted)
        self.avoidance_panel.draw_mode_requested.connect(self._on_draw_mode_requested)
        tab_widget.addTab(self.avoidance_panel, "Avoidance")

        # Tab 3: Layout Groups
        self.layout_panel = LayoutPanel(parent=self)
        self.layout_panel.layout_changed.connect(self._on_layout_changed)
        tab_widget.addTab(self.layout_panel, "Layout")

        # Tab 4: Outline & Holes
        self.outline_panel = OutlineEditor(parent=self)
        self.outline_panel.outline_changed.connect(self._on_outline_changed)
        self.outline_panel.hole_added.connect(self._on_hole_added)
        self.outline_panel.hole_removed.connect(self._on_hole_removed)
        self.outline_panel.draw_outline_requested.connect(
            lambda: self.canvas.set_interaction_mode(MODE_DRAW_OUTLINE)
        )
        self.outline_panel.place_hole_requested.connect(
            lambda: self.canvas.set_interaction_mode(MODE_PLACE_HOLE)
        )
        tab_widget.addTab(self.outline_panel, "Outline")

        # Tab 5: Export
        export_tab = QWidget()
        export_layout = QVBoxLayout(export_tab)
        export_label = QLabel("Export functionality available via File → Export DXF")
        export_label.setWordWrap(True)
        export_label.setStyleSheet("color: gray; padding: 20px;")
        export_layout.addWidget(export_label)
        tab_widget.addTab(export_tab, "Export")

        # Track tab changes for mode switching
        tab_widget.currentChanged.connect(self._on_tab_changed)

        dock.setWidget(tab_widget)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

    def _create_menu_bar(self):
        """Create the menu bar."""
        menubar = self.menuBar()

        # File Menu
        file_menu = menubar.addMenu("&File")

        open_pcb_action = QAction("Open PCB...", self)
        open_pcb_action.setShortcut(QKeySequence.Open)
        open_pcb_action.setStatusTip("Open an Altium ASCII .PcbDoc file")
        open_pcb_action.triggered.connect(self.open_pcb_file)
        file_menu.addAction(open_pcb_action)

        file_menu.addSeparator()

        save_project_action = QAction("Save Project...", self)
        save_project_action.setShortcut(QKeySequence.Save)
        save_project_action.setStatusTip("Save project state to JSON")
        save_project_action.triggered.connect(self.save_project)
        file_menu.addAction(save_project_action)

        load_project_action = QAction("Load Project...", self)
        load_project_action.setStatusTip("Load project state from JSON")
        load_project_action.triggered.connect(self.load_project)
        file_menu.addAction(load_project_action)

        file_menu.addSeparator()

        export_dxf_action = QAction("Export DXF...", self)
        export_dxf_action.setStatusTip("Export layers as DXF files")
        export_dxf_action.triggered.connect(self.export_layers)
        file_menu.addAction(export_dxf_action)

        file_menu.addSeparator()

        exit_action = QAction("Exit", self)
        exit_action.setShortcut(QKeySequence.Quit)
        exit_action.setStatusTip("Exit application")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Edit Menu
        edit_menu = menubar.addMenu("&Edit")

        undo_action = QAction("Undo", self)
        undo_action.setShortcut(QKeySequence.Undo)
        undo_action.setEnabled(False)  # TODO: Implement undo/redo
        edit_menu.addAction(undo_action)

        redo_action = QAction("Redo", self)
        redo_action.setShortcut(QKeySequence.Redo)
        redo_action.setEnabled(False)  # TODO: Implement undo/redo
        edit_menu.addAction(redo_action)

        edit_menu.addSeparator()

        prefs_action = QAction("Preferences...", self)
        prefs_action.setStatusTip("Open application preferences")
        prefs_action.setEnabled(False)  # TODO: Implement preferences
        edit_menu.addAction(prefs_action)

        # View Menu
        view_menu = menubar.addMenu("&View")

        zoom_in_action = QAction("Zoom In", self)
        zoom_in_action.setShortcut(QKeySequence.ZoomIn)
        zoom_in_action.triggered.connect(self.canvas.fit_to_content)
        view_menu.addAction(zoom_in_action)

        zoom_out_action = QAction("Zoom Out", self)
        zoom_out_action.setShortcut(QKeySequence.ZoomOut)
        zoom_out_action.triggered.connect(self._zoom_out)
        view_menu.addAction(zoom_out_action)

        fit_action = QAction("Fit to Content", self)
        fit_action.setShortcut(QKeySequence("Ctrl+F"))
        fit_action.triggered.connect(self.canvas.fit_to_content)
        view_menu.addAction(fit_action)

        view_menu.addSeparator()

        toggle_grid_action = QAction("Toggle Grid", self)
        toggle_grid_action.setShortcut(QKeySequence("Ctrl+G"))
        toggle_grid_action.setEnabled(False)  # TODO: Implement grid toggle
        view_menu.addAction(toggle_grid_action)

        # Help Menu
        help_menu = menubar.addMenu("&Help")

        about_action = QAction("About", self)
        about_action.setStatusTip("About this application")
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _create_toolbar(self):
        """Create the main toolbar."""
        toolbar = QToolBar("Main Toolbar", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        # File actions
        open_action = QAction("Open", self)
        open_action.setStatusTip("Open PCB file")
        open_action.triggered.connect(self.open_pcb_file)
        toolbar.addAction(open_action)

        save_action = QAction("Save", self)
        save_action.setStatusTip("Save project")
        save_action.triggered.connect(self.save_project)
        toolbar.addAction(save_action)

        toolbar.addSeparator()

        # Mode selection (radio-button style)
        self.mode_button_group = QButtonGroup(self)

        select_btn = QToolButton(self)
        select_btn.setText("Select")
        select_btn.setCheckable(True)
        select_btn.setChecked(True)
        select_btn.setToolTip("Select components (default)")
        select_btn.clicked.connect(lambda: self.canvas.set_interaction_mode(MODE_SELECT))
        self.mode_button_group.addButton(select_btn, 0)
        toolbar.addWidget(select_btn)

        draw_rect_btn = QToolButton(self)
        draw_rect_btn.setText("DrawRect")
        draw_rect_btn.setCheckable(True)
        draw_rect_btn.setToolTip("Draw rectangular avoidance zone")
        draw_rect_btn.clicked.connect(lambda: self.canvas.set_interaction_mode(MODE_DRAW_RECT))
        self.mode_button_group.addButton(draw_rect_btn, 1)
        toolbar.addWidget(draw_rect_btn)

        draw_poly_btn = QToolButton(self)
        draw_poly_btn.setText("DrawPoly")
        draw_poly_btn.setCheckable(True)
        draw_poly_btn.setToolTip("Draw polygon avoidance zone")
        draw_poly_btn.clicked.connect(lambda: self.canvas.set_interaction_mode(MODE_DRAW_POLYGON))
        self.mode_button_group.addButton(draw_poly_btn, 2)
        toolbar.addWidget(draw_poly_btn)

        place_hole_btn = QToolButton(self)
        place_hole_btn.setText("PlaceHole")
        place_hole_btn.setCheckable(True)
        place_hole_btn.setToolTip("Place screw hole")
        place_hole_btn.clicked.connect(lambda: self.canvas.set_interaction_mode(MODE_PLACE_HOLE))
        self.mode_button_group.addButton(place_hole_btn, 3)
        toolbar.addWidget(place_hole_btn)

        draw_outline_btn = QToolButton(self)
        draw_outline_btn.setText("DrawOutline")
        draw_outline_btn.setCheckable(True)
        draw_outline_btn.setToolTip("Draw board outline")
        draw_outline_btn.clicked.connect(lambda: self.canvas.set_interaction_mode(MODE_DRAW_OUTLINE))
        self.mode_button_group.addButton(draw_outline_btn, 4)
        toolbar.addWidget(draw_outline_btn)

        toolbar.addSeparator()

        # View actions
        fit_action = QAction("Fit", self)
        fit_action.setStatusTip("Fit view to content")
        fit_action.triggered.connect(self.canvas.fit_to_content)
        toolbar.addAction(fit_action)

        zoom_in_action = QAction("ZoomIn", self)
        zoom_in_action.setStatusTip("Zoom in")
        zoom_in_action.triggered.connect(lambda: self.canvas._zoom(1.15))
        toolbar.addAction(zoom_in_action)

        zoom_out_action = QAction("ZoomOut", self)
        zoom_out_action.setStatusTip("Zoom out")
        zoom_out_action.triggered.connect(lambda: self.canvas._zoom(1.0/1.15))
        toolbar.addAction(zoom_out_action)

    def _create_status_bar(self):
        """Create the status bar."""
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)

        # Mode indicator
        self.status_mode = QLabel("Mode: Select")
        status_bar.addWidget(self.status_mode)

        # Cursor position
        self.status_cursor = QLabel("Cursor: (0.0, 0.0)mm")
        status_bar.addWidget(self.status_cursor)

        # Switch count
        self.status_switches = QLabel("Switches: 0/0")
        status_bar.addWidget(self.status_switches)

        # Zoom level
        self.status_zoom = QLabel("Zoom: 1.0x")
        status_bar.addPermanentWidget(self.status_zoom)

    # File operations

    def open_pcb_file(self):
        """Open a PCB file through file dialog."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open PCB File",
            "",
            "Altium PCB Files (*.PcbDoc *.pcb);;All Files (*)"
        )

        if not file_path:
            return

        # Validate ASCII format
        is_valid, error_msg = validate_ascii_pcb(file_path)
        if not is_valid:
            QMessageBox.critical(
                self,
                "Invalid PCB File",
                f"Failed to open PCB file:\n\n{error_msg}"
            )
            return

        # Parse PCB file
        try:
            parser = AltiumASCIIParser()
            pcb = parser.parse(file_path)
            pcb.source_file = file_path
        except Exception as e:
            QMessageBox.critical(
                self,
                "Parse Error",
                f"Failed to parse PCB file:\n\n{str(e)}"
            )
            return

        # Update state
        self.state.pcb_data = pcb
        self.state.modified = True

        # Distribute data to panels
        self._on_pcb_loaded(pcb)

    def save_project(self):
        """Save project state to JSON file."""
        if not self.state.pcb_data:
            QMessageBox.warning(
                self,
                "No Data",
                "No PCB data loaded. Please open a PCB file first."
            )
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Project",
            self.state.project_path or "",
            "Project Files (*.json);;All Files (*)"
        )

        if not file_path:
            return

        try:
            # Prepare save data
            save_data = {
                "pcb_source_file": self.state.pcb_data.source_file,
                "rule_set": self.state.rule_set.to_dict() if hasattr(self.state.rule_set, 'to_dict') else {},
                "layout_config": self.state.layout_config.to_dict() if self.state.layout_config else None,
                "layer_config": self.state.layer_config.to_dict() if hasattr(self.state.layer_config, 'to_dict') else {},
                "avoidance_polygons": [p.to_dict() for p in self.state.avoidance_polygons if hasattr(p, 'to_dict')],
                "manual_outline": self.state.pcb_data.board_outline.to_dict() if self.state.pcb_data.board_outline else None,
                "manual_holes": [h.to_dict() for h in self.state.pcb_data.screw_holes if hasattr(h, 'to_dict')]
            }

            # Write to file
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, indent=2, ensure_ascii=False)

            self.state.project_path = file_path
            self.state.modified = False

            QMessageBox.information(
                self,
                "Project Saved",
                f"Project saved successfully to:\n{file_path}"
            )

        except Exception as e:
            QMessageBox.critical(
                self,
                "Save Failed",
                f"Failed to save project:\n\n{str(e)}"
            )

    def load_project(self):
        """Load project state from JSON file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Project",
            "",
            "Project Files (*.json);;All Files (*)"
        )

        if not file_path:
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Restore state
            self.state.project_path = file_path

            # Note: Full implementation would deserialize all state objects
            # For now, just show a message
            QMessageBox.information(
                self,
                "Project Loaded",
                f"Project loaded from:\n{file_path}\n\n(Note: Full deserialization not yet implemented)"
            )

        except Exception as e:
            QMessageBox.critical(
                self,
                "Load Failed",
                f"Failed to load project:\n\n{str(e)}"
            )

    def export_layers(self):
        """Open export dialog for DXF export."""
        if not self.state.pcb_data:
            QMessageBox.warning(
                self,
                "No Data",
                "No PCB data loaded. Please open a PCB file first."
            )
            return

        # Create export dialog
        dialog = ExportDialog(
            pcb_data=self.state.pcb_data,
            layout_config=self.state.layout_config,
            layer_config=self.state.layer_config,
            avoidance_polygons=self.state.avoidance_polygons,
            parent=self
        )

        dialog.exec_()

    # Panel signal handlers

    def _on_pcb_loaded(self, pcb: PCBData):
        """Distribute loaded PCB data to all panels."""
        # Update canvas
        self.canvas.set_pcb_data(pcb)

        # Update footprint rules panel
        if self.footprint_panel:
            self.footprint_panel.set_pcb_data(pcb)

        # Update outline panel
        if self.outline_panel:
            self.outline_panel.set_pcb_data(pcb)

        # Update status bar
        self._update_status_bar()

    def _on_rules_applied(self, rule_set: FootprintRuleSet):
        """Handle rules applied event."""
        self.state.rule_set = rule_set

        # Re-render canvas with new classifications
        if self.state.pcb_data:
            self.canvas.set_pcb_data(self.state.pcb_data)

        # Auto-detect suspected ICs for avoidance
        if self.state.pcb_data:
            suspected = detect_suspected_avoidance(self.state.pcb_data.components)
            if suspected and self.avoidance_panel:
                for poly in suspected:
                    self.avoidance_panel.add_polygon(poly)

        # Update layout panel with classified switches
        if self.layout_panel and self.state.pcb_data:
            switches = self.state.pcb_data.get_switches()
            self.layout_panel.set_switches(switches)

        self._update_status_bar()

    def _on_avoidance_confirmed(self, index: int):
        """Handle avoidance polygon confirmed."""
        self.state.modified = True

    def _on_avoidance_deleted(self, index: int):
        """Handle avoidance polygon deleted."""
        self.state.modified = True

    def _on_avoidance_created(self, vertices: list, source: str):
        """Handle avoidance polygon created via canvas."""
        if self.avoidance_panel:
            self.avoidance_panel.add_polygon_from_canvas(vertices, source)
        self.state.modified = True

    def _on_draw_mode_requested(self, mode: str):
        """Handle draw mode requested from avoidance panel."""
        if mode == "rect":
            self.canvas.set_interaction_mode(MODE_DRAW_RECT)
        elif mode == "polygon":
            self.canvas.set_interaction_mode(MODE_DRAW_POLYGON)

    def _on_layout_changed(self, layout_config: LayoutConfig):
        """Handle layout configuration changed."""
        self.state.layout_config = layout_config
        self.state.modified = True

    def _on_outline_changed(self, vertices: list, source: str):
        """Handle board outline changed."""
        if self.state.pcb_data:
            from models.pcb_data import BoardOutline
            self.state.pcb_data.board_outline = BoardOutline(vertices=vertices, source=source)
            self.canvas.set_pcb_data(self.state.pcb_data)
        self.state.modified = True

    def _on_hole_added(self, x: float, y: float, diameter: float):
        """Handle screw hole added."""
        if self.state.pcb_data:
            from models.pcb_data import ScrewHole
            hole = ScrewHole(x=x, y=y, diameter=diameter, source="manual")
            self.state.pcb_data.screw_holes.append(hole)
            self.canvas.set_pcb_data(self.state.pcb_data)
        self.state.modified = True

    def _on_hole_removed(self, index: int):
        """Handle screw hole removed."""
        if self.state.pcb_data and 0 <= index < len(self.state.pcb_data.screw_holes):
            self.state.pcb_data.screw_holes.pop(index)
            self.canvas.set_pcb_data(self.state.pcb_data)
        self.state.modified = True

    def _on_hole_placed(self, x: float, y: float):
        """Handle hole placed via canvas."""
        if self.outline_panel:
            self.outline_panel.add_hole(x, y)

    def _on_outline_point_added(self, x: float, y: float):
        """Handle outline point added via canvas."""
        if self.outline_panel:
            self.outline_panel.add_outline_vertex(x, y)

    def _on_tab_changed(self, index: int):
        """Handle tab change event."""
        # Auto-switch canvas mode based on tab
        if index == 1:  # Avoidance tab
            # Keep current mode or default to select
            pass
        elif index == 3:  # Outline tab
            # Could auto-switch to draw outline mode
            pass
        else:
            # Reset to select mode
            if self.mode_button_group:
                self.mode_button_group.button(0).setChecked(True)
            self.canvas.set_interaction_mode(MODE_SELECT)

    # Canvas signal handlers

    def _on_component_clicked(self, ref: str):
        """Handle component clicked on canvas."""
        # Could show component details or highlight in panels
        pass

    def _on_cursor_position_changed(self, x: float, y: float):
        """Handle cursor position changed."""
        if self.status_cursor:
            self.status_cursor.setText(f"Cursor: ({x:.1f}, {y:.1f})mm")

    def _on_zoom_changed(self, zoom_level: float):
        """Handle zoom level changed."""
        if self.status_zoom:
            self.status_zoom.setText(f"Zoom: {zoom_level:.2f}x")

    # Helper methods

    def _update_status_bar(self):
        """Update status bar information."""
        if self.status_switches and self.state.pcb_data:
            switches = self.state.pcb_data.get_switches()
            total = len(self.state.pcb_data.components)
            self.status_switches.setText(f"Switches: {len(switches)}/{total}")

    def _zoom_out(self):
        """Zoom out the canvas."""
        if self.canvas:
            self.canvas._zoom(1.0 / 1.15)

    def _show_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self,
            "About Keyboard PCB Tool",
            "<h3>Keyboard PCB Tool</h3>"
            "<p>Version 1.0</p>"
            "<p>A tool for generating keyboard plate and foam layers from PCB files.</p>"
            "<p>Features:</p>"
            "<ul>"
            "<li>Parse Altium ASCII PCB files</li>"
            "<li>Auto-detect switches and IC positions</li>"
            "<li>Configure avoidance zones</li>"
            "<li>Export DXF layers for fabrication</li>"
            "</ul>"
        )

    def closeEvent(self, event):
        """Handle window close event."""
        if self.state.modified:
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "You have unsaved changes. Do you want to save before exiting?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel
            )

            if reply == QMessageBox.Save:
                self.save_project()
                if self.state.modified:  # Save was cancelled or failed
                    event.ignore()
                    return
            elif reply == QMessageBox.Cancel:
                event.ignore()
                return

        event.accept()
