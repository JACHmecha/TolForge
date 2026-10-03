"""Unsaved-change guards and recovery of raw work without evaluating drafts."""

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QLineEdit,
    QMessageBox, QSpinBox, QTableWidgetItem,
)

from tolstack import drafts
from tolstack.domain import new_id
from tolstack.project import Project
from tolstack.persistence import backup_path
from tolstack.workflow import validate_workspace_project

TEXT_WIDGETS = (
    "response_name_input", "study_objective_input", "study_assumptions_input",
    "seed_input", "default_cpk_input", "gdt_default_cpk_input",
    "inspection_drawing_input", "inspection_source_input", "inspection_datum_input",
    "gdt_base_tolerance_input", "gdt_mmc_size_input", "gdt_lmc_size_input",
)
CHOICE_WIDGETS = ("method_combo", "inspection_units_combo", "gdt_modifier_combo", "gdt_feature_kind_combo")
CHECK_WIDGETS = ("study_units_check", "inspection_alignment_check", "inspection_scope_check")
SPIN_WIDGETS = ("iterations_input", "gdt_iterations_input", "range_min_input", "range_max_input")
TABLES = {"stack": "table", "pattern": "pattern_table", "inspection": "inspection_table", "drawing_controls": "characteristic_table"}


class ProjectLifecycleMixin:
    def _project_lifecycle_init(self):
        self._project_dirty = False
        self._project_force_dirty = False
        self._project_change_pause = 0
        self._project_lifecycle_ready = False
        self._project_closing = False
        self._project_preserve_raw_geometry = False
        self._project_pending_raw_geometry = None
        self._project_draft_id = drafts.new_draft_id()
        self._project_auto_draft_path = drafts.draft_directory() / f"{self._project_draft_id}.recovery.json"
        self._project_recovered_auto_paths = []
        self._project_last_valid_snapshot = self.project.to_dict()

    def _project_lifecycle_install(self):
        self._project_draft_timer = QTimer(self)
        self._project_draft_timer.setSingleShot(True)
        self._project_draft_timer.setInterval(600)
        self._project_draft_timer.timeout.connect(self._project_write_auto_draft)
        # Domain/datum assignments also change outside Qt table models. A
        # bounded observer catches those while widget signals update promptly.
        self._project_change_timer = QTimer(self)
        self._project_change_timer.setInterval(1000)
        self._project_change_timer.timeout.connect(self._project_note_change)
        for name in TEXT_WIDGETS:
            getattr(self, name).textChanged.connect(self._project_note_change)
        for name in CHOICE_WIDGETS:
            getattr(self, name).currentTextChanged.connect(self._project_note_change)
        for name in CHECK_WIDGETS:
            getattr(self, name).toggled.connect(self._project_note_change)
        for name in SPIN_WIDGETS:
            widget = getattr(self, name)
            widget.valueChanged.connect(self._project_note_change)
            widget.lineEdit().textChanged.connect(self._project_note_change)
        for name in TABLES.values():
            table = getattr(self, name, None)
            if table is not None:
                table.itemChanged.connect(self._project_note_change)
                table.model().rowsInserted.connect(self._project_note_change)
                table.model().rowsRemoved.connect(self._project_note_change)
                table.model().modelReset.connect(self._project_note_change)
        for name in ("study_objective_input", "study_assumptions_input", "inspection_drawing_input",
                     "inspection_source_input", "inspection_datum_input"):
            getattr(self, name).textChanged.connect(self._project_invalidate_context_reports)
        for name in CHECK_WIDGETS:
            getattr(self, name).toggled.connect(self._project_invalidate_context_reports)
        self.inspection_units_combo.currentTextChanged.connect(self._project_invalidate_context_reports)
        self._project_lifecycle_ready = True
        self._project_mark_clean()
        self._project_change_timer.start()

    @contextmanager
    def _project_suspend_changes(self):
        self._project_change_pause = getattr(self, "_project_change_pause", 0) + 1
        try:
            yield
        finally:
            self._project_change_pause -= 1

    def _project_table_snapshot(self, name):
        table = getattr(self, TABLES[name], None)
        if table is None:
            return []
        rows = []
        roles = (self.LINK_ROLE, self.TOLERANCE_ID_ROLE, self.STACK_TERM_ID_ROLE) if name == "stack" else (
            self.PATTERN_FEATURE_ID_ROLE, self.PATTERN_MEMBER_ID_ROLE, self.PATTERN_SIZE_TOLERANCE_ID_ROLE,
            self.PATTERN_X_TOLERANCE_ID_ROLE, self.PATTERN_Y_TOLERANCE_ID_ROLE,
        ) if name == "pattern" else (
            getattr(self, "INSPECTION_MEASUREMENT_ROLE", Qt.UserRole + 221),
        ) if name == "inspection" else ()
        for row in range(table.rowCount()):
            cells = []
            for column in range(drafts.TABLE_WIDTHS[name]):
                item = table.item(row, column)
                text = item.data(Qt.EditRole) if item is not None else ""
                cell = {"text": "" if text is None else str(text), "roles": {}}
                if column == 0 and item is not None:
                    for role in roles:
                        value = item.data(role)
                        if value is not None:
                            cell["roles"][str(int(role))] = deepcopy(value)
                cells.append(cell)
            rows.append(cells)
        return rows

    def _project_raw_ui(self):
        widgets = {}
        for name in TEXT_WIDGETS:
            widgets[name] = {"kind": "text", "text": getattr(self, name).text()}
        for name in CHOICE_WIDGETS:
            widgets[name] = {"kind": "choice", "text": getattr(self, name).currentText()}
        for name in CHECK_WIDGETS:
            widgets[name] = {"kind": "check", "value": getattr(self, name).isChecked()}
        for name in SPIN_WIDGETS:
            widget = getattr(self, name)
            widgets[name] = {"kind": "spin", "text": widget.lineEdit().text(), "value": widget.value()}
        datums = {}
        for slot, entry in self._datum_slot.items():
            if entry is None:
                datums[slot] = None
            else:
                datums[slot] = {
                    "point": [float(v) for v in entry["point"]], "direction": [float(v) for v in entry["direction"]],
                    "description": entry.get("description", ""), "kind": entry.get("kind", "plane"),
                    "feature_id": entry.get("feature_id"), "datum_ref_id": entry.get("datum_ref_id"),
                }
        return {"widgets": widgets, "tables": {name: self._project_table_snapshot(name) for name in TABLES},
                "datums": datums, "inspection_source_files": deepcopy(getattr(self, "_inspection_source_files", []))}

    def _project_state_snapshot(self):
        domain_error = None
        try:
            project = self.project.to_dict()
            self._project_last_valid_snapshot = deepcopy(project)
        except (ValueError, TypeError, KeyError) as exc:
            project = deepcopy(self._project_last_valid_snapshot)
            domain_error = str(exc)
        context = {"project_path": self._project_path, "recovered_from": self._project_recovered_from,
                   **{name: getattr(self, name) for name in drafts.ACTIVE_IDS}}
        if domain_error:
            context["domain_validation_error"] = domain_error
        return project, self._project_raw_ui(), context

    def _project_fingerprint(self):
        payload = self._project_state_snapshot()
        return hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode("utf-8")).hexdigest()

    def _project_mark_clean(self, *, recovered=False):
        if not getattr(self, "_project_lifecycle_ready", False):
            return
        try:
            self._project_clean_fingerprint = self._project_fingerprint()
        except (ValueError, TypeError, KeyError, RecursionError):
            # A committed engineering file stays successful even if a
            # non-persisted editor decoration cannot be fingerprinted.
            self._project_clean_fingerprint = None
        self._project_observed_fingerprint = self._project_clean_fingerprint
        self._project_force_dirty = recovered
        self._project_dirty = recovered
        self._project_update_title()
        if recovered:
            self._project_draft_timer.start()

    def _project_note_change(self, *args):
        if (not getattr(self, "_project_lifecycle_ready", False) or self._project_change_pause
                or self._project_closing):
            return
        try:
            fingerprint = self._project_fingerprint()
        except (ValueError, TypeError, KeyError):
            self._project_dirty = True
            self._project_update_title()
            return
        changed = fingerprint != self._project_observed_fingerprint
        self._project_observed_fingerprint = fingerprint
        dirty = self._project_force_dirty or fingerprint != self._project_clean_fingerprint
        if dirty != self._project_dirty:
            self._project_dirty = dirty
            self._project_update_title()
        if changed:
            if dirty:
                self._project_draft_timer.start()
            else:
                self._project_clear_auto_draft()

    def _project_is_dirty(self):
        self._project_note_change()
        return getattr(self, "_project_dirty", False)

    def _project_may_replace(self, action):
        self._project_guard_saved = False
        if not self._project_is_dirty():
            return True
        choice = QMessageBox.question(
            self, "Unsaved project changes", f"Save your project changes before {action}?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save,
        )
        if choice == QMessageBox.Save:
            self._project_guard_saved = bool(self.save_project())
            return self._project_guard_saved
        return choice == QMessageBox.Discard

    def _project_invalidate_context_reports(self, *args):
        for name in ("_invalidate_stack_report", "_invalidate_gdt_results"):
            callback = getattr(self, name, None)
            if callback is not None:
                callback()

    def _project_invalidate_all_reports(self):
        self._project_invalidate_context_reports()
        self._invalidate_inspection()

    def _project_capture_raw_geometry_before_load(self):
        self._project_pending_raw_geometry = {
            "datums": deepcopy(self._datum_slot), "pattern": self._project_table_snapshot("pattern"),
        }

    def _project_restore_raw_geometry_after_load(self):
        state = getattr(self, "_project_pending_raw_geometry", None)
        if state is None:
            return
        with self._project_suspend_changes():
            self._project_restore_draft_table("pattern", state["pattern"])
            self._datum_slot = deepcopy(state["datums"])
            # Points/directions are refreshed only for a real, matched feature.
            # Missing links remain visibly selected but cannot form a ready
            # analysis context. No evaluation is run by draft recovery.
            for entry in self._datum_slot.values():
                if entry is None:
                    continue
                info = self._entity_by_feature_id.get(entry.get("feature_id"))
                if info is not None:
                    point, direction, description = self._gdt_extract_datum_geometry(info)
                    if point is not None:
                        entry.update(point=point, direction=direction, description=description)
            self._current_drf = None
            self._update_datum_labels()
            self.drf_status_label.setText("Draft selections retained. Rebuild the datum frame after reviewing matched geometry.")
        self._project_pending_raw_geometry = None

    def _project_clear_auto_draft(self):
        timer = getattr(self, "_project_draft_timer", None)
        if timer is not None:
            timer.stop()
        paths = [self._project_auto_draft_path, *self._project_recovered_auto_paths]
        directory = drafts.draft_directory().resolve()
        for path in paths:
            if Path(path).resolve().parent != directory:
                continue
            for target in (Path(path), backup_path(path)):
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    # An obsolete recovery copy never turns a successful
                    # engineering save into a reported failure.
                    pass
        self._project_recovered_auto_paths = []

    def _project_draft_payload(self):
        project, ui, context = self._project_state_snapshot()
        return drafts.create_draft(project, ui, context, draft_id=self._project_draft_id)

    def _project_write_auto_draft(self):
        if self._project_closing or not self._project_is_dirty():
            return
        try:
            payload = self._project_draft_payload()
            self._project_auto_draft_path.parent.mkdir(parents=True, exist_ok=True)
            drafts.save_draft(self._project_auto_draft_path, payload)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.statusBar().showMessage(f"Recovery draft could not be saved: {exc}", 10000)

    def save_recovery_draft(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save incomplete work as recovery draft", "study.recovery.json",
                                             "TolForge recovery draft (*.recovery.json)")
        if not path:
            return False
        if not path.lower().endswith(".json"):
            path += ".recovery.json"
        try:
            drafts.save_draft(path, self._project_draft_payload())
        except (OSError, ValueError, TypeError, KeyError) as exc:
            QMessageBox.warning(self, "Could not save recovery draft", str(exc))
            return False
        self.statusBar().showMessage(f"Recovery draft saved: {Path(path).name}", 10000)
        return True

    def open_recovery_draft(self):
        path, _ = QFileDialog.getOpenFileName(self, "Recover incomplete work", str(drafts.draft_directory()),
                                             "TolForge recovery drafts (*.recovery.json);;All files (*)")
        return self._project_open_draft_from(path) if path else False

    def _project_restore_draft_table(self, name, rows):
        table = getattr(self, TABLES[name], None)
        if table is None:
            if rows:
                raise ValueError(f"The {name} draft editor is not available.")
            return
        table.setRowCount(0)
        for row, cells in enumerate(rows):
            table.insertRow(row)
            for column, cell in enumerate(cells):
                item = QTableWidgetItem(cell["text"])
                for role, value in cell.get("roles", {}).items():
                    item.setData(int(role), value)
                if name == "inspection" and column == 0:
                    role = self.INSPECTION_MEASUREMENT_ROLE
                    if item.data(role) is None:
                        # Older drafts predate measurement ancestry. Assign an
                        # identity once on restore, without inventing an import.
                        item.setData(role, {"id": new_id(), "units": self.inspection_units_combo.currentText()})
                if name == "drawing_controls" and column == 0:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                table.setItem(row, column, item)

    def _project_open_draft_from(self, path):
        try:
            data = drafts.load_draft(path)
            project = Project.from_dict(data["project_snapshot"])
            validate_workspace_project(project)
            for name, state in data["ui"]["widgets"].items():
                widget = getattr(self, name, None)
                expected = {"text": QLineEdit, "choice": QComboBox, "check": QCheckBox,
                            "spin": (QSpinBox, QDoubleSpinBox)}[state["kind"]]
                if name not in (*TEXT_WIDGETS, *CHOICE_WIDGETS, *CHECK_WIDGETS, *SPIN_WIDGETS) or not isinstance(widget, expected):
                    raise ValueError(f"Unsupported recovery draft widget {name}.")
                if state["kind"] == "choice" and widget.findText(state["text"]) < 0:
                    raise ValueError(f"Unsupported recovery draft choice for {name}.")
            for name, rows in data["ui"]["tables"].items():
                if rows and getattr(self, TABLES[name], None) is None:
                    raise ValueError(f"The {name} draft editor is not available.")
        except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
            QMessageBox.warning(self, "Could not recover draft", str(exc))
            return False
        if not self._project_may_replace("recovering this draft"):
            return False
        if self._project_guard_saved:
            try:
                # Save As may have selected the same target. Recheck its type
                # before replacing live work with an obsolete pre-save read.
                data = drafts.load_draft(path)
                project = Project.from_dict(data["project_snapshot"])
                validate_workspace_project(project)
            except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
                QMessageBox.warning(self, "Could not recover draft", str(exc))
                return False
        self._project_clear_auto_draft()
        with self._project_suspend_changes():
            self._project_preserve_raw_geometry = False
            self._project_pending_raw_geometry = None
            self.clear_step_preview()
            self.project = project
            context, ui = data["context"], data["ui"]
            self._project_path = None
            self._project_recovered_from = context.get("project_path") or context.get("recovered_from")
            for name in drafts.ACTIVE_IDS:
                setattr(self, name, context.get(name))
            self._entity_by_feature_id = {}
            self._step_entity_info = {}
            self._study_restore()
            for name, state in ui["widgets"].items():
                widget = getattr(self, name)
                if state["kind"] == "text":
                    widget.setText(state["text"])
                elif state["kind"] == "choice":
                    widget.setCurrentText(state["text"])
                elif state["kind"] == "check":
                    widget.setChecked(state["value"])
                else:
                    widget.setValue(state["value"])
                    widget.lineEdit().setText(state["text"])
            for name, rows in ui["tables"].items():
                self._project_restore_draft_table(name, rows)
            self._inspection_source_files = deepcopy(ui.get("inspection_source_files", []))
            self._datum_slot = deepcopy(ui["datums"])
            self._current_drf = None
            self._update_datum_labels()
            self._project_preserve_raw_geometry = True
            self._project_invalidate_all_reports()
            self.drf_status_label.setText("Recovered draft datums. Reload source geometry and rebuild the frame before evaluation.")
            self.step_status_label.setText("Recovered incomplete work. Validate inputs and Save As to create an engineering project.")
        if Path(path).resolve().parent == drafts.draft_directory().resolve():
            self._project_recovered_auto_paths.append(Path(path))
        self._project_mark_clean(recovered=True)
        return True

    def _project_offer_startup_recovery(self):
        # Called by main after showing the window, never by constructors.
        try:
            candidates = drafts.available_drafts()
        except OSError:
            return
        if not candidates:
            return
        selected = candidates[0]
        answer = QMessageBox.question(
            self, "Recovery draft available", "Incomplete work from an earlier session is available. Recover the latest draft?\n"
            "You can leave it untouched and use File → Recover Incomplete Work later.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self._project_open_draft_from(selected)

    def _project_prepare_close(self, event):
        if not self._project_closing:
            if not self._project_may_replace("closing"):
                event.ignore()
                return False
            self._project_closing = True
            self._project_change_timer.stop()
            self._project_draft_timer.stop()
            for name in ("_measure_offset_timer", "_stack_preview_timer"):
                timer = getattr(self, name, None)
                if timer is not None:
                    timer.stop()
        thread = getattr(self, "_step_load_thread", None)
        if thread is not None and not self._cancel_step_load_for_shutdown():
            if not getattr(self, "_project_close_waiting", False):
                self._project_close_waiting = True
                thread.finished.connect(self._project_finish_deferred_close, Qt.QueuedConnection)
            self.step_status_label.setText("Closing when the current STEP read finishes. Your project choice has been retained.")
            self.setEnabled(False)
            event.ignore()
            return False
        self._project_clear_auto_draft()
        return True

    def _project_finish_deferred_close(self):
        QTimer.singleShot(0, self.close)
