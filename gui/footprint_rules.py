"""
Footprint Rules Configuration Panel

Provides UI for managing switch identification rules.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QLineEdit, QSpinBox,
    QPushButton, QCheckBox, QGroupBox, QTextEdit,
    QMessageBox, QAbstractItemView
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont

from models.footprint_rules import FootprintRule, FootprintRuleSet
from models.pcb_data import PCBData


class FootprintRulesPanel(QWidget):
    """Configuration panel for footprint matching rules."""

    # Signals
    rules_applied = pyqtSignal(object)  # FootprintRuleSet
    rule_set_changed = pyqtSignal(object)  # FootprintRuleSet

    def __init__(self, rule_set=None, parent=None):
        """Initialize the footprint rules panel.

        Args:
            rule_set: Optional FootprintRuleSet (defaults to DEFAULT_RULES)
            parent: Parent widget
        """
        super().__init__(parent)

        self.rule_set = rule_set if rule_set is not None else FootprintRuleSet.DEFAULT_RULES
        self.pcb_data = None
        self.current_item = None

        self._init_ui()
        self._load_rules()

    def _init_ui(self):
        """Initialize the UI components."""
        layout = QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Title
        title = QLabel("Switch Identification Rules")
        title.setFont(QFont("Arial", 12, QFont.Bold))
        layout.addWidget(title)

        # Rule List
        list_group = QGroupBox("Rules (sorted by priority)")
        list_layout = QVBoxLayout()

        self.rule_list = QListWidget()
        self.rule_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.rule_list.itemClicked.connect(self._on_rule_selected)
        list_layout.addWidget(self.rule_list)

        list_group.setLayout(list_layout)
        layout.addWidget(list_group)

        # Rule Editor
        editor_group = QGroupBox("Rule Editor")
        editor_layout = QVBoxLayout()

        # Pattern input
        pattern_layout = QHBoxLayout()
        pattern_layout.addWidget(QLabel("Pattern (regex):"))
        self.pattern_input = QLineEdit()
        self.pattern_input.setPlaceholderText("e.g., .*Switch.* or ^SW[0-9]+")
        self.pattern_input.textChanged.connect(self._on_editor_changed)
        pattern_layout.addWidget(self.pattern_input)
        editor_layout.addLayout(pattern_layout)

        # Label input
        label_layout = QHBoxLayout()
        label_layout.addWidget(QLabel("Label:"))
        self.label_input = QLineEdit()
        self.label_input.setPlaceholderText("e.g., Switch or LED")
        self.label_input.textChanged.connect(self._on_editor_changed)
        label_layout.addWidget(self.label_input)
        editor_layout.addLayout(label_layout)

        # Priority and Enabled
        options_layout = QHBoxLayout()

        priority_layout = QHBoxLayout()
        priority_layout.addWidget(QLabel("Priority:"))
        self.priority_input = QSpinBox()
        self.priority_input.setRange(1, 100)
        self.priority_input.setValue(50)
        self.priority_input.valueChanged.connect(self._on_editor_changed)
        priority_layout.addWidget(self.priority_input)
        priority_layout.addStretch()

        options_layout.addLayout(priority_layout)

        self.enabled_checkbox = QCheckBox("Enabled")
        self.enabled_checkbox.setChecked(True)
        self.enabled_checkbox.stateChanged.connect(self._on_editor_changed)
        options_layout.addWidget(self.enabled_checkbox)
        options_layout.addStretch()

        editor_layout.addLayout(options_layout)

        # Test button
        self.test_button = QPushButton("Test Rule")
        self.test_button.clicked.connect(self._on_test_rule)
        editor_layout.addWidget(self.test_button)

        editor_group.setLayout(editor_layout)
        layout.addWidget(editor_group)

        # Control buttons
        buttons_layout = QHBoxLayout()

        self.add_button = QPushButton("Add Rule")
        self.add_button.clicked.connect(self._on_add_rule)
        buttons_layout.addWidget(self.add_button)

        self.remove_button = QPushButton("Remove Rule")
        self.remove_button.clicked.connect(self._on_remove_rule)
        self.remove_button.setEnabled(False)
        buttons_layout.addWidget(self.remove_button)

        self.move_up_button = QPushButton("Move Up")
        self.move_up_button.clicked.connect(self._on_move_up)
        self.move_up_button.setEnabled(False)
        buttons_layout.addWidget(self.move_up_button)

        self.move_down_button = QPushButton("Move Down")
        self.move_down_button.clicked.connect(self._on_move_down)
        self.move_down_button.setEnabled(False)
        buttons_layout.addWidget(self.move_down_button)

        layout.addLayout(buttons_layout)

        # Apply button
        self.apply_button = QPushButton("Apply Rules")
        self.apply_button.clicked.connect(self._on_apply_rules)
        layout.addWidget(self.apply_button)

        # Results Summary
        results_group = QGroupBox("Results")
        results_layout = QVBoxLayout()

        self.matched_label = QLabel("Matched: 0 switches")
        self.matched_label.setStyleSheet("color: green; font-weight: bold;")
        results_layout.addWidget(self.matched_label)

        self.unmatched_label = QLabel("Unmatched: 0 components")
        self.unmatched_label.setStyleSheet("color: gray;")
        results_layout.addWidget(self.unmatched_label)

        results_layout.addWidget(QLabel("Matched components:"))

        self.matched_components = QTextEdit()
        self.matched_components.setMaximumHeight(80)
        self.matched_components.setReadOnly(True)
        self.matched_components.setPlaceholderText("None")
        results_layout.addWidget(self.matched_components)

        results_group.setLayout(results_layout)
        layout.addWidget(results_group)

        layout.addStretch()
        self.setLayout(layout)

    def set_pcb_data(self, pcb_data: PCBData):
        """Set the PCB data for testing rules.

        Args:
            pcb_data: PCBData instance containing components
        """
        self.pcb_data = pcb_data
        self._update_results()

    def _load_rules(self):
        """Load rules from the rule set into the list widget."""
        self.rule_list.clear()

        # Sort rules by priority (highest first)
        sorted_rules = sorted(
            self.rule_set.rules,
            key=lambda r: r.priority,
            reverse=True
        )

        for rule in sorted_rules:
            item = QListWidgetItem()
            self._update_rule_item(item, rule)
            self.rule_list.addItem(item)

    def _update_rule_item(self, item: QListWidgetItem, rule: FootprintRule):
        """Update a list item with rule data.

        Args:
            item: QListWidgetItem to update
            rule: FootprintRule to display
        """
        status = "✓" if rule.enabled else "✗"
        item.setText(f"[{rule.priority:3d}] {status} {rule.label}: {rule.pattern}")

        # Store rule reference in item data
        item.setData(Qt.UserRole, rule)

        # Gray out disabled rules
        if not rule.enabled:
            item.setForeground(QColor(128, 128, 128))

    def _on_rule_selected(self, item: QListWidgetItem):
        """Handle rule selection from the list.

        Args:
            item: Selected QListWidgetItem
        """
        self.current_item = item
        rule = item.data(Qt.UserRole)

        if rule:
            # Populate editor
            self.pattern_input.setText(rule.pattern)
            self.label_input.setText(rule.label)
            self.priority_input.setValue(rule.priority)
            self.enabled_checkbox.setChecked(rule.enabled)

            # Enable buttons
            self.remove_button.setEnabled(True)
            self.move_up_button.setEnabled(True)
            self.move_down_button.setEnabled(True)

    def _on_editor_changed(self):
        """Handle changes in the rule editor."""
        if self.current_item:
            rule = self.current_item.data(Qt.UserRole)

            # Update rule
            rule.pattern = self.pattern_input.text() or rule.pattern
            rule.label = self.label_input.text() or rule.label
            rule.priority = self.priority_input.value()
            rule.enabled = self.enabled_checkbox.isChecked()

            # Update display
            self._update_rule_item(self.current_item, rule)

            # Re-sort list if priority changed
            self.rule_list.sortItems(Qt.DescendingOrder)

            # Emit change signal
            self.rule_set_changed.emit(self.rule_set)

    def _on_add_rule(self):
        """Add a new rule with default values."""
        new_rule = FootprintRule(
            pattern=".*",
            label="New Rule",
            priority=50,
            enabled=True
        )
        self.rule_set.rules.append(new_rule)

        # Add to list
        item = QListWidgetItem()
        self._update_rule_item(item, new_rule)
        self.rule_list.addItem(item)

        # Select the new item
        self.rule_list.setCurrentItem(item)
        self._on_rule_selected(item)

        # Emit change signal
        self.rule_set_changed.emit(self.rule_set)

    def _on_remove_rule(self):
        """Remove the selected rule."""
        if self.current_item:
            rule = self.current_item.data(Qt.UserRole)

            # Remove from rule set
            if rule in self.rule_set.rules:
                self.rule_set.rules.remove(rule)

            # Remove from list
            row = self.rule_list.row(self.current_item)
            self.rule_list.takeItem(row)

            # Clear editor
            self.current_item = None
            self.pattern_input.clear()
            self.label_input.clear()
            self.priority_input.setValue(50)
            self.enabled_checkbox.setChecked(True)

            # Disable buttons
            self.remove_button.setEnabled(False)
            self.move_up_button.setEnabled(False)
            self.move_down_button.setEnabled(False)

            # Emit change signal
            self.rule_set_changed.emit(self.rule_set)

    def _on_move_up(self):
        """Move the selected rule up in priority."""
        if self.current_item:
            current_row = self.rule_list.row(self.current_item)
            if current_row > 0:
                # Increase priority
                rule = self.current_item.data(Qt.UserRole)
                rule.priority = min(100, rule.priority + 10)

                # Update display and re-sort
                self._update_rule_item(self.current_item, rule)
                self.rule_list.sortItems(Qt.DescendingOrder)

                # Re-select the item
                for i in range(self.rule_list.count()):
                    item = self.rule_list.item(i)
                    if item.data(Qt.UserRole) == rule:
                        self.rule_list.setCurrentItem(item)
                        self.current_item = item
                        break

                # Emit change signal
                self.rule_set_changed.emit(self.rule_set)

    def _on_move_down(self):
        """Move the selected rule down in priority."""
        if self.current_item:
            # Decrease priority
            rule = self.current_item.data(Qt.UserRole)
            rule.priority = max(1, rule.priority - 10)

            # Update display and re-sort
            self._update_rule_item(self.current_item, rule)
            self.rule_list.sortItems(Qt.DescendingOrder)

            # Re-select the item
            for i in range(self.rule_list.count()):
                item = self.rule_list.item(i)
                if item.data(Qt.UserRole) == rule:
                    self.rule_list.setCurrentItem(item)
                    self.current_item = item
                    break

            # Emit change signal
            self.rule_set_changed.emit(self.rule_set)

    def _on_test_rule(self):
        """Test the current rule against PCB data."""
        if not self.pcb_data:
            QMessageBox.warning(
                self,
                "No Data",
                "Please load PCB data first to test rules."
            )
            return

        if self.current_item:
            rule = self.current_item.data(Qt.UserRole)

            # Count matches
            import re
            matches = 0
            matched_refs = []

            for comp in self.pcb_data.components:
                if rule.enabled and re.search(rule.pattern, comp.footprint, re.IGNORECASE):
                    matches += 1
                    matched_refs.append(comp.ref)

            # Show results
            QMessageBox.information(
                self,
                "Rule Test Results",
                f"Rule '{rule.label}' matches {matches} components.\n\n"
                f"Pattern: {rule.pattern}\n"
                f"Matched refs: {', '.join(matched_refs[:20])}"
                + ("..." if len(matched_refs) > 20 else "")
            )

    def _on_apply_rules(self):
        """Apply all rules to classify components."""
        if not self.pcb_data:
            QMessageBox.warning(
                self,
                "No Data",
                "Please load PCB data first to apply rules."
            )
            return

        # Apply rules using the rule set
        switch_count = self.rule_set.apply_to_pcb(self.pcb_data)

        # Update results display
        self._update_results()

        # Emit signal
        self.rules_applied.emit(self.rule_set)

        QMessageBox.information(
            self,
            "Rules Applied",
            f"Successfully classified {switch_count} switches."
        )

    def _update_results(self):
        """Update the results summary display."""
        if self.pcb_data:
            # Count switches
            switch_count = sum(
                1 for comp in self.pcb_data.components
                if comp.is_switch
            )

            # Count unmatched
            unmatched_count = len(self.pcb_data.components) - switch_count

            # Get matched component refs
            matched_refs = [
                comp.ref for comp in self.pcb_data.components
                if comp.is_switch
            ]

            # Update labels
            self.matched_label.setText(f"Matched: {switch_count} switches")
            self.unmatched_label.setText(f"Unmatched: {unmatched_count} components")

            # Update matched components list
            if matched_refs:
                self.matched_components.setText(", ".join(matched_refs))
            else:
                self.matched_components.setText("None")
        else:
            self.matched_label.setText("Matched: 0 switches")
            self.unmatched_label.setText("Unmatched: 0 components")
            self.matched_components.setText("None")

    def get_rule_set(self) -> FootprintRuleSet:
        """Get the current rule set.

        Returns:
            Current FootprintRuleSet
        """
        return self.rule_set

    def set_rule_set(self, rule_set: FootprintRuleSet):
        """Set a new rule set.

        Args:
            rule_set: FootprintRuleSet to use
        """
        self.rule_set = rule_set
        self._load_rules()
        self.rule_set_changed.emit(self.rule_set)
