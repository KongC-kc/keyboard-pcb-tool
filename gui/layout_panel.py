"""Panel for managing layout groups and switch configuration options."""
from __future__ import annotations

from typing import Optional, List
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QPushButton,
    QLabel, QLineEdit, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QSplitter, QGroupBox, QAbstractItemView,
    QListWidgetItem, QFrame, QRadioButton, QButtonGroup, QCheckBox
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QIcon, QColor

from models.layout_group import LayoutGroup, LayoutOption, LayoutConfig
from models.pcb_data import Component
from avoidance.layout_hints import CandidateZone, find_candidate_split_zones


class LayoutPanel(QWidget):
    """Panel for managing layout grouping of switches."""

    # Signals
    layout_changed = pyqtSignal(object)  # LayoutConfig
    assign_mode_changed = pyqtSignal(bool)  # active: bool
    switches_assigned = pyqtSignal(str, str, list)  # group_id, option_id, refs

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._switches: List[Component] = []
        self._candidates: List[CandidateZone] = []
        self._groups: List[LayoutGroup] = []
        self._selected_group_index: Optional[int] = None
        self._selected_option_index: Optional[int] = None
        self._assign_mode_active = False

        self._init_ui()

    def _init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # Main splitter for resizable panels
        splitter = QSplitter(Qt.Vertical)
        layout.addWidget(splitter)

        # Top: Candidate Split Zones
        candidates_panel = self._create_candidates_panel()
        splitter.addWidget(candidates_panel)

        # Middle: Layout Groups
        groups_panel = self._create_groups_panel()
        splitter.addWidget(groups_panel)

        # Bottom: Group Editor
        editor_panel = self._create_editor_panel()
        splitter.addWidget(editor_panel)

        # Set initial splitter sizes (20% candidates, 35% groups, 45% editor)
        splitter.setSizes([150, 250, 320])

    def _create_candidates_panel(self) -> QWidget:
        """Create the candidate split zones panel."""
        panel = QGroupBox("Candidate Split Zones")
        layout = QVBoxLayout(panel)
        layout.setSpacing(6)

        # List widget
        self._candidates_list = QListWidget()
        self._candidates_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._candidates_list.itemDoubleClicked.connect(self._on_candidate_activated)
        layout.addWidget(self._candidates_list)

        # Action buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(4)

        self._btn_create_group = QPushButton("Create Group")
        self._btn_create_group.clicked.connect(self._on_create_group_from_candidate)
        btn_layout.addWidget(self._btn_create_group)

        self._btn_ignore_candidate = QPushButton("Ignore")
        self._btn_ignore_candidate.clicked.connect(self._on_ignore_candidate)
        btn_layout.addWidget(self._btn_ignore_candidate)

        self._btn_detect_candidates = QPushButton("Detect Candidates")
        self._btn_detect_candidates.clicked.connect(self._on_detect_candidates)
        btn_layout.addWidget(self._btn_detect_candidates)

        layout.addLayout(btn_layout)
        return panel

    def _create_groups_panel(self) -> QWidget:
        """Create the layout groups panel."""
        panel = QGroupBox("Layout Groups")
        layout = QVBoxLayout(panel)
        layout.setSpacing(6)

        # List widget with tree-like structure
        self._groups_list = QListWidget()
        self._groups_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._groups_list.itemClicked.connect(self._on_group_selected)
        layout.addWidget(self._groups_list)

        # Action buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(4)

        self._btn_add_group = QPushButton("Add Group")
        self._btn_add_group.clicked.connect(self._on_add_group)
        btn_layout.addWidget(self._btn_add_group)

        self._btn_remove_group = QPushButton("Remove Group")
        self._btn_remove_group.clicked.connect(self._on_remove_group)
        btn_layout.addWidget(self._btn_remove_group)

        layout.addLayout(btn_layout)
        return panel

    def _create_editor_panel(self) -> QWidget:
        """Create the group editor panel."""
        panel = QGroupBox("Group Editor")
        layout = QVBoxLayout(panel)
        layout.setSpacing(6)

        # Group name
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Name:"))
        self._group_name_edit = QLineEdit()
        self._group_name_edit.editingFinished.connect(self._on_group_properties_changed)
        name_layout.addWidget(self._group_name_edit)
        layout.addLayout(name_layout)

        # Group description
        desc_layout = QHBoxLayout()
        desc_layout.addWidget(QLabel("Description:"))
        self._group_desc_edit = QLineEdit()
        self._group_desc_edit.editingFinished.connect(self._on_group_properties_changed)
        desc_layout.addWidget(self._group_desc_edit)
        layout.addLayout(desc_layout)

        # Options section
        layout.addWidget(QLabel("Options:"))
        self._options_table = QTableWidget()
        self._options_table.setColumnCount(3)
        self._options_table.setHorizontalHeaderLabels(["", "Name", "Switches"])
        self._options_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._options_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._options_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._options_table.verticalHeader().setVisible(False)
        self._options_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._options_table.itemClicked.connect(self._on_option_selected)
        self._options_table.itemChanged.connect(self._on_option_name_changed)
        layout.addWidget(self._options_table)

        # Option buttons
        opt_btn_layout = QHBoxLayout()
        opt_btn_layout.setSpacing(4)

        self._btn_add_option = QPushButton("Add Option")
        self._btn_add_option.clicked.connect(self._on_add_option)
        opt_btn_layout.addWidget(self._btn_add_option)

        self._btn_remove_option = QPushButton("Remove Option")
        self._btn_remove_option.clicked.connect(self._on_remove_option)
        opt_btn_layout.addWidget(self._btn_remove_option)

        layout.addLayout(opt_btn_layout)

        # Switch assignment mode
        assign_layout = QHBoxLayout()
        self._assign_mode_check = QCheckBox("Assign Switches Mode")
        self._assign_mode_check.toggled.connect(self._on_assign_mode_toggled)
        assign_layout.addWidget(self._assign_mode_check)
        assign_layout.addStretch()
        layout.addLayout(assign_layout)

        # Initially disable editor
        self._set_editor_enabled(False)

        return panel

    def _set_editor_enabled(self, enabled: bool):
        """Enable or disable all editor widgets."""
        self._group_name_edit.setEnabled(enabled)
        self._group_desc_edit.setEnabled(enabled)
        self._options_table.setEnabled(enabled)
        self._btn_add_option.setEnabled(enabled)
        self._btn_remove_option.setEnabled(enabled)
        self._assign_mode_check.setEnabled(enabled)

    def _refresh_candidates_list(self):
        """Refresh the candidates list display."""
        self._candidates_list.clear()
        for zone in self._candidates:
            item = QListWidgetItem()
            text = f"{zone.description} at ({zone.center_x:.1f}, {zone.center_y:.1f})"
            item.setText(text)
            item.setData(Qt.UserRole, zone)
            self._candidates_list.addItem(item)

    def _refresh_groups_list(self):
        """Refresh the groups list display."""
        self._groups_list.clear()
        for i, group in enumerate(self._groups):
            # Add group item
            group_item = QListWidgetItem()
            selected_opt = group.selected_option()
            selected_name = selected_opt.name if selected_opt else "None"
            text = f"{group.name}: {selected_name} ({len(group.options)} options)"
            group_item.setText(text)
            group_item.setData(Qt.UserRole, i)
            self._groups_list.addItem(group_item)

    def _refresh_editor(self):
        """Refresh the editor panel for the selected group."""
        if self._selected_group_index is None or self._selected_group_index >= len(self._groups):
            self._set_editor_enabled(False)
            self._group_name_edit.clear()
            self._group_desc_edit.clear()
            self._options_table.setRowCount(0)
            return

        group = self._groups[self._selected_group_index]
        self._set_editor_enabled(True)

        # Block signals during refresh
        self._group_name_edit.blockSignals(True)
        self._group_desc_edit.blockSignals(True)
        self._options_table.blockSignals(True)

        try:
            # Group properties
            self._group_name_edit.setText(group.name)
            self._group_desc_edit.setText(group.description)

            # Options table
            self._options_table.setRowCount(len(group.options))
            self._radio_button_group = QButtonGroup(self)

            for row, option in enumerate(group.options):
                # Radio button for selection
                radio_widget = QWidget()
                radio_layout = QHBoxLayout(radio_widget)
                radio_layout.setContentsMargins(0, 0, 0, 0)
                radio_layout.setAlignment(Qt.AlignCenter)
                radio = QRadioButton()
                radio.setChecked(option.id == group.selected_option_id)
                radio.toggled.connect(lambda checked, oid=option.id: self._on_option_radio_toggled(oid, checked))
                self._radio_button_group.addButton(radio, row)
                radio_layout.addWidget(radio)
                self._options_table.setCellWidget(row, 0, radio_widget)

                # Option name
                name_item = QTableWidgetItem(option.name)
                name_item.setData(Qt.UserRole, option.id)
                name_item.setFlags(name_item.flags() | Qt.ItemIsEditable)
                self._options_table.setItem(row, 1, name_item)

                # Switch refs
                refs_text = ", ".join(option.switch_refs) if option.switch_refs else "None"
                refs_item = QTableWidgetItem(refs_text)
                refs_item.setFlags(refs_item.flags() & ~Qt.ItemIsEditable)
                refs_item.setData(Qt.UserRole, option.switch_refs)
                self._options_table.setItem(row, 2, refs_item)

        finally:
            self._group_name_edit.blockSignals(False)
            self._group_desc_edit.blockSignals(False)
            self._options_table.blockSignals(False)

    def _on_candidate_activated(self, item: QListWidgetItem):
        """Handle double-click on candidate."""
        self._on_create_group_from_candidate()

    def _on_create_group_from_candidate(self):
        """Create a layout group from selected candidate."""
        current_item = self._candidates_list.currentItem()
        if not current_item:
            return

        zone = current_item.data(Qt.UserRole)
        if not zone:
            return

        # Create unique group ID
        group_id = f"group_{len(self._groups) + 1}"

        # Create options from switches in the zone
        options = []
        for i, switch in enumerate(zone.switches):
            option_id = f"{group_id}_opt_{i + 1}"
            option_name = f"Option {i + 1}"
            options.append(LayoutOption(id=option_id, name=option_name, switch_refs=[switch.ref]))

        # Create group
        group = LayoutGroup(
            id=group_id,
            name=f"Zone ({zone.grid_col}, {zone.grid_row})",
            description=f"Candidate zone with {len(zone.switches)} switches",
            options=options,
            selected_option_id=options[0].id if options else None
        )

        self._groups.append(group)
        self._refresh_groups_list()
        self._emit_layout_changed()

        # Remove candidate from list
        self._candidates.remove(zone)
        self._refresh_candidates_list()

    def _on_ignore_candidate(self):
        """Ignore (remove) the selected candidate."""
        current_item = self._candidates_list.currentItem()
        if not current_item:
            return

        zone = current_item.data(Qt.UserRole)
        if zone and zone in self._candidates:
            self._candidates.remove(zone)
            self._refresh_candidates_list()

    def _on_detect_candidates(self):
        """Re-run candidate detection on current switches."""
        if not self._switches:
            return

        self._candidates = find_candidate_split_zones(self._switches)
        self._refresh_candidates_list()

    def _on_group_selected(self, item: QListWidgetItem):
        """Handle group selection."""
        self._selected_group_index = item.data(Qt.UserRole)
        self._selected_option_index = None
        self._refresh_editor()

    def _on_add_group(self):
        """Add a new empty group."""
        group_id = f"group_{len(self._groups) + 1}"
        group = LayoutGroup(
            id=group_id,
            name=f"Group {len(self._groups) + 1}",
            description="",
            options=[],
            selected_option_id=None
        )
        self._groups.append(group)
        self._refresh_groups_list()
        self._emit_layout_changed()

    def _on_remove_group(self):
        """Remove the selected group."""
        if self._selected_group_index is None or self._selected_group_index >= len(self._groups):
            return

        del self._groups[self._selected_group_index]
        self._selected_group_index = None
        self._selected_option_index = None
        self._refresh_groups_list()
        self._refresh_editor()
        self._emit_layout_changed()

    def _on_group_properties_changed(self):
        """Handle changes to group name or description."""
        if self._selected_group_index is None or self._selected_group_index >= len(self._groups):
            return

        group = self._groups[self._selected_group_index]
        group.name = self._group_name_edit.text()
        group.description = self._group_desc_edit.text()

        self._refresh_groups_list()
        self._emit_layout_changed()

    def _on_option_selected(self, item: QTableWidgetItem):
        """Handle option selection in table."""
        self._selected_option_index = item.row()

    def _on_option_name_changed(self, item: QTableWidgetItem):
        """Handle option name change."""
        if self._selected_group_index is None or self._selected_group_index >= len(self._groups):
            return

        if item.column() != 1:  # Only name column
            return

        group = self._groups[self._selected_group_index]
        row = item.row()

        if row < 0 or row >= len(group.options):
            return

        option = group.options[row]
        new_name = item.text()

        if new_name and new_name != option.name:
            option.name = new_name
            self._refresh_groups_list()
            self._emit_layout_changed()

    def _on_option_radio_toggled(self, option_id: str, checked: bool):
        """Handle radio button toggle for option selection."""
        if not checked:
            return

        if self._selected_group_index is None or self._selected_group_index >= len(self._groups):
            return

        group = self._groups[self._selected_group_index]
        group.selected_option_id = option_id

        self._refresh_groups_list()
        self._emit_layout_changed()

    def _on_add_option(self):
        """Add a new option to the current group."""
        if self._selected_group_index is None or self._selected_group_index >= len(self._groups):
            return

        group = self._groups[self._selected_group_index]
        option_id = f"{group.id}_opt_{len(group.options) + 1}"
        option = LayoutOption(id=option_id, name=f"Option {len(group.options) + 1}", switch_refs=[])

        group.options.append(option)

        # If this is the first option, select it
        if len(group.options) == 1:
            group.selected_option_id = option_id

        self._refresh_editor()
        self._refresh_groups_list()
        self._emit_layout_changed()

    def _on_remove_option(self):
        """Remove the selected option."""
        if self._selected_group_index is None or self._selected_group_index >= len(self._groups):
            return

        group = self._groups[self._selected_group_index]
        if self._selected_option_index is None or self._selected_option_index >= len(group.options):
            return

        # Check if this was the selected option
        removed_option = group.options[self._selected_option_index]
        if removed_option.id == group.selected_option_id:
            # Select another option if available
            if len(group.options) > 1:
                new_index = 0 if self._selected_option_index == 0 else self._selected_option_index - 1
                group.selected_option_id = group.options[new_index].id
            else:
                group.selected_option_id = None

        del group.options[self._selected_option_index]
        self._selected_option_index = None

        self._refresh_editor()
        self._refresh_groups_list()
        self._emit_layout_changed()

    def _on_assign_mode_toggled(self, checked: bool):
        """Handle assign mode checkbox toggle."""
        self._assign_mode_active = checked
        self.assign_mode_changed.emit(checked)

    def _emit_layout_changed(self):
        """Emit layout changed signal with current config."""
        config = self.get_layout_config()
        self.layout_changed.emit(config)

    def set_switches(self, switches: List[Component]):
        """Set available switches and run candidate detection."""
        self._switches = switches
        self._candidates = find_candidate_split_zones(switches)
        self._refresh_candidates_list()

    def get_layout_config(self) -> LayoutConfig:
        """Return current layout configuration."""
        return LayoutConfig(groups=list(self._groups))

    def set_layout_config(self, config: LayoutConfig):
        """Restore a saved configuration."""
        self._groups = list(config.groups)
        self._selected_group_index = None
        self._selected_option_index = None
        self._refresh_groups_list()
        self._refresh_editor()

    def add_switch_to_option(self, group_id: str, option_id: str, ref: str):
        """Programmatically add a switch to an option."""
        # Find group
        group = None
        group_index = None
        for i, g in enumerate(self._groups):
            if g.id == group_id:
                group = g
                group_index = i
                break

        if not group:
            return

        # Find option
        option = None
        for opt in group.options:
            if opt.id == option_id:
                option = opt
                break

        if not option:
            return

        # Add switch ref if not already present
        if ref not in option.switch_refs:
            option.switch_refs.append(ref)

            # Refresh if this group is selected
            if self._selected_group_index == group_index:
                self._refresh_editor()

            self._emit_layout_changed()
            self.switches_assigned.emit(group_id, option_id, option.switch_refs)

    def get_selected_group_and_option(self) -> tuple[Optional[str], Optional[str]]:
        """Get the currently selected group and option IDs."""
        if self._selected_group_index is None or self._selected_group_index >= len(self._groups):
            return None, None

        group = self._groups[self._selected_group_index]

        if self._selected_option_index is None or self._selected_option_index >= len(group.options):
            return group.id, None

        option = group.options[self._selected_option_index]
        return group.id, option.id

    def is_assign_mode_active(self) -> bool:
        """Check if switch assignment mode is active."""
        return self._assign_mode_active
