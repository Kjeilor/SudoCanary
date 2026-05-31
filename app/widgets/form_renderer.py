"""
app/widgets/form_renderer.py

Pure UI component — knows nothing about sensors, rooms, or the database.
Takes a JSON Schema dict, renders the appropriate PySide6 widgets, and
exposes collect() / is_valid() for the parent screen to drive submission.

Field type mapping:
  string (no format)       → QLineEdit
  string format=date       → QDateEdit
  string format=textarea   → QTextEdit
  string enum              → QComboBox
  number                   → QDoubleSpinBox
  integer                  → QSpinBox
  boolean                  → QCheckBox

Constraints applied: minimum, maximum, enum values, required (blocks collect).
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class FormRenderer(QWidget):
    """
    Reads a JSON Schema dict and renders a form. Stateless between calls to
    reset(). The parent screen owns the Submit button and calls:
        ok, msg = renderer.is_valid()
        payload = renderer.collect()
    """

    def __init__(self, schema: Dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self._schema = schema
        self._fields: Dict[str, QWidget] = {}
        self._required: set[str] = set(schema.get("required", []))
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        from PySide6.QtWidgets import QFrame
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        form = QFormLayout(container)
        form.setSpacing(10)
        form.setContentsMargins(0, 0, 8, 0)

        properties: Dict[str, Any] = self._schema.get("properties", {})
        for field_name, field_def in properties.items():
            widget = self._make_widget(field_def)
            label_text = field_def.get("title", field_name.replace("_", " ").title())
            if field_name in self._required:
                label_text += " *"
            label = QLabel(label_text)
            self._fields[field_name] = widget
            form.addRow(label, widget)

        if not properties:
            form.addRow(QLabel("This sensor has no fields defined."))

        scroll.setWidget(container)
        outer.addWidget(scroll)

    # ── Public API ────────────────────────────────────────────────────────────

    def is_valid(self) -> Tuple[bool, str]:
        """
        Check required fields are non-empty.
        Returns (True, "") or (False, human-readable message).
        """
        for name in self._required:
            widget = self._fields.get(name)
            if widget is None:
                continue
            if isinstance(widget, QLineEdit) and not widget.text().strip():
                label = name.replace("_", " ").title()
                return False, f"{label} is required."
            if isinstance(widget, QTextEdit) and not widget.toPlainText().strip():
                label = name.replace("_", " ").title()
                return False, f"{label} is required."
        return True, ""

    def collect(self) -> Dict[str, Any]:
        """Return a dict mapping field names to their current widget values."""
        result: Dict[str, Any] = {}
        for name, widget in self._fields.items():
            result[name] = self._read_widget(widget)
        return result

    def reset(self) -> None:
        """Clear all field values back to defaults."""
        for widget in self._fields.values():
            self._clear_widget(widget)

    # ── Widget factory ────────────────────────────────────────────────────────

    def _make_widget(self, field_def: Dict[str, Any]) -> QWidget:
        ftype = field_def.get("type", "string")
        fmt   = field_def.get("format", "")
        enum  = field_def.get("enum")

        if enum is not None:
            w = QComboBox()
            w.addItems([str(v) for v in enum])
            return w

        if ftype == "boolean":
            return QCheckBox()

        if ftype == "integer":
            w = QSpinBox()
            w.setMinimum(int(field_def.get("minimum", 0)))
            w.setMaximum(int(field_def.get("maximum", 2_147_483_647)))
            return w

        if ftype == "number":
            w = QDoubleSpinBox()
            w.setDecimals(2)
            w.setMinimum(float(field_def.get("minimum", 0.0)))
            w.setMaximum(float(field_def.get("maximum", 1_000_000.0)))
            return w

        if fmt == "date":
            from PySide6.QtCore import QDate
            w = QDateEdit()
            w.setCalendarPopup(True)
            w.setDate(QDate.currentDate())
            w.setDisplayFormat("yyyy-MM-dd")
            return w

        if fmt == "textarea":
            w = QTextEdit()
            w.setFixedHeight(90)
            if "description" in field_def:
                w.setPlaceholderText(field_def["description"])
            return w

        # Default: plain string
        w = QLineEdit()
        if "description" in field_def:
            w.setPlaceholderText(field_def["description"])
        if "maxLength" in field_def:
            w.setMaxLength(int(field_def["maxLength"]))
        return w

    # ── Value helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _read_widget(widget: QWidget) -> Any:
        if isinstance(widget, QComboBox):
            return widget.currentText()
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        if isinstance(widget, QSpinBox):
            return widget.value()
        if isinstance(widget, QDoubleSpinBox):
            return widget.value()
        if isinstance(widget, QDateEdit):
            return widget.date().toString("yyyy-MM-dd")
        if isinstance(widget, QTextEdit):
            return widget.toPlainText()
        if isinstance(widget, QLineEdit):
            return widget.text()
        return None

    @staticmethod
    def _clear_widget(widget: QWidget) -> None:
        if isinstance(widget, QComboBox):
            widget.setCurrentIndex(0)
        elif isinstance(widget, QCheckBox):
            widget.setChecked(False)
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            widget.setValue(widget.minimum())
        elif isinstance(widget, QDateEdit):
            from PySide6.QtCore import QDate
            widget.setDate(QDate.currentDate())
        elif isinstance(widget, QTextEdit):
            widget.clear()
        elif isinstance(widget, QLineEdit):
            widget.clear()