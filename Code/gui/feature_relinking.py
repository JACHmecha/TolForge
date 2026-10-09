"""Guided saved-feature relinking without replacing engineering definitions."""

from datetime import datetime, timezone

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from tolstack.features import signature_from_points
from tolstack.relinking import plan_relinking, validate_manual_assignment
from gui.table_presentation import configure_table, fit_table_columns


class FeatureRelinkingDialog(QDialog):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.setWindowTitle("Reconnect saved CAD features")
        self.resize(1040, 680)
        layout = QVBoxLayout(self)
        self.source_label = QLabel()
        self.source_label.setWordWrap(True)
        layout.addWidget(self.source_label)
        actions = QHBoxLayout()
        locate = QPushButton("Locate / reload CAD source…")
        locate.clicked.connect(host.locate_project_source)
        actions.addWidget(locate)
        self.accept_revision = QPushButton("Accept loaded CAD revision")
        self.accept_revision.clicked.connect(self._accept_revision)
        actions.addWidget(self.accept_revision)
        refresh = QPushButton("Refresh matches")
        refresh.clicked.connect(self.refresh)
        actions.addWidget(refresh)
        layout.addLayout(actions)
        self.features = QTableWidget(0, 6)
        self.features.setHorizontalHeaderLabels(["Saved feature", "Stable ID", "Kind", "State", "Best score", "Reason"])
        configure_table(self.features, numeric_columns=(4,), text_columns=(0, 1, 2, 3, 5))
        self.features.setSelectionBehavior(QTableWidget.SelectRows)
        self.features.setSelectionMode(QTableWidget.SingleSelection)
        self.features.setEditTriggers(QTableWidget.NoEditTriggers)
        self.features.itemSelectionChanged.connect(self._show_candidates)
        layout.addWidget(self.features)
        hint = QLabel("Select a saved feature, review the geometry and score below, then assign explicitly. "
                      "Scores describe geometric proximity; they do not prove topological identity.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.candidates = QTableWidget(0, 4)
        self.candidates.setHorizontalHeaderLabels(["Loaded entity", "Score", "Availability", "Comparison"])
        configure_table(self.candidates, numeric_columns=(1,), text_columns=(0, 2, 3))
        self.candidates.setSelectionBehavior(QTableWidget.SelectRows)
        self.candidates.setSelectionMode(QTableWidget.SingleSelection)
        self.candidates.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.candidates)
        buttons = QHBoxLayout()
        assign = QPushButton("Assign selected candidate")
        assign.clicked.connect(self._assign)
        buttons.addWidget(assign)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self):
        self.host._project_refresh_relink_diagnostics()
        status = getattr(self.host, "_project_source_status", "unverified")
        pending = getattr(self.host, "_project_revision_pending", False)
        part = self.host.project.parts.get(self.host._active_part_id)
        loaded = getattr(self.host, "_project_loaded_source_evidence", {}).get(self.host._active_part_id, {})
        saved_hash = loaded.get("comparison_sha256", part.source_sha256 if part else None)
        loaded_hash = loaded.get("loaded_sha256") if loaded.get("loaded_hash_status") == "verified" else None
        self.source_label.setText(f"CAD revision: {status}. " + (
            "Saved links are held until you explicitly accept the loaded revision."
            if pending else "Missing definitions remain saved. Rebuild the datum frame after reconnecting geometry."
        ) + f"\nLoaded source: {loaded.get('path') or 'not loaded'}"
          + f"\nSaved SHA-256 at load: {saved_hash or 'not recorded'}"
          + f"\nLoaded SHA-256: {loaded_hash or 'unverified'}")
        self.source_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.accept_revision.setEnabled(pending)
        self.features.setRowCount(0)
        for row, diagnostic in enumerate(self.host._project_relink_diagnostics):
            self.features.insertRow(row)
            values = [diagnostic.name, diagnostic.feature_id, diagnostic.kind,
                      "revision pending" if pending else diagnostic.status,
                      "—" if diagnostic.best_score is None else f"{diagnostic.best_score:.6g}", diagnostic.reason]
            for column, value in enumerate(values):
                self.features.setItem(row, column, QTableWidgetItem(value))
        fit_table_columns(self.features)
        self.candidates.setRowCount(0)

    def _show_candidates(self):
        self.candidates.setRowCount(0)
        row = self.features.currentRow()
        if row < 0:
            return
        feature_id = self.features.item(row, 1).text()
        diagnostic = next((item for item in self.host._project_relink_diagnostics if item.feature_id == feature_id), None)
        if diagnostic is None:
            return
        self._candidate_scene = tuple(id(info) for info in self.host._project_relink_infos)
        for row, candidate in enumerate(diagnostic.candidates):
            info = self.host._project_relink_infos[candidate.entity_index]
            self.candidates.insertRow(row)
            values = [f"{info['type']} #{info['index']}", "—" if candidate.score is None else f"{candidate.score:.6g}",
                      "available" if candidate.occupied_by is None else f"assigned to {candidate.occupied_by}",
                      "; ".join(candidate.reasons)]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, candidate.entity_index)
                self.candidates.setItem(row, column, item)
        fit_table_columns(self.candidates)

    def _assign(self):
        feature_row, candidate_row = self.features.currentRow(), self.candidates.currentRow()
        if feature_row < 0 or candidate_row < 0:
            return
        if self._candidate_scene != tuple(id(info) for info in self.host._project_relink_infos):
            self.refresh()
            QMessageBox.warning(self, "CAD scene changed", "Review the refreshed candidates before assigning a feature.")
            return
        feature_id = self.features.item(feature_row, 1).text()
        entity_index = self.candidates.item(candidate_row, 0).data(Qt.UserRole)
        try:
            self.host._project_manual_relink(feature_id, entity_index)
        except ValueError as exc:
            QMessageBox.warning(self, "Could not reconnect feature", str(exc))
            return
        self.refresh()

    def _accept_revision(self):
        answer = QMessageBox.question(
            self, "Use this CAD revision?",
            "The loaded CAD revision is changed or unverified. Accept this revision for reviewing and "
            "reconnecting the existing engineering definitions? Review every feature before evaluation.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.host._project_accept_loaded_revision()
            self.refresh()


class FeatureRelinkingMixin:
    def show_feature_relinking(self):
        dialog = FeatureRelinkingDialog(self)
        self._project_relink_dialog = dialog
        return dialog.exec()

    def _project_clear_loaded_source_evidence(self):
        self._project_loaded_source_evidence = {}
        self._project_source_status = "unverified"
        self._project_revision_pending = False
        self._project_relink_infos = []
        self._project_relink_candidates = {}
        self._project_relink_diagnostics = ()

    def _project_build_relink_candidates(self):
        self._project_relink_infos = list(self._step_entity_info.values())
        candidates = {}
        for index, info in enumerate(self._project_relink_infos):
            signatures = {}
            surface = info.get("surface")
            if info["type"] in ("face", "edge"):
                self._measure_ensure_circle_fit(info)
            try:
                basic = signature_from_points(info["type"], info["points"], surface=surface)
                if basic is not None and not (basic.kind == "plane" and surface and surface.get("kind") != "plane"):
                    signatures[basic.kind] = basic
                circle = info.get("circle")
                if circle is not None and info["type"] in ("face", "edge"):
                    circular = signature_from_points(info["type"], info["points"], circle_fit=circle)
                    signatures["circle"] = circular
            except (ValueError, KeyError, TypeError):
                pass  # Invalid loaded geometry cannot qualify an assignment.
            candidates[index] = signatures
        self._project_relink_candidates = candidates

    def _project_relink_assignments(self):
        indices = {id(info): index for index, info in enumerate(getattr(self, "_project_relink_infos", []))}
        return {feature_id: indices[id(info)] for feature_id, info in self._entity_by_feature_id.items() if id(info) in indices}

    def _project_refresh_relink_diagnostics(self):
        if not hasattr(self, "_project_relink_infos") or (not self._project_relink_infos and self._step_entity_info):
            self._project_build_relink_candidates()
        saved = [feature for feature in self.project.features.values() if feature.part_definition_id == self._active_part_id]
        self._project_relink_diagnostics = plan_relinking(
            saved, self._project_relink_candidates, assignments=self._project_relink_assignments(), auto_attach=False,
        )
        return self._project_relink_diagnostics

    def _project_relink_status_text(self):
        if getattr(self, "_project_revision_pending", False):
            return f"CAD revision {self._project_source_status}; open Reconnect Saved Features to accept and review it."
        unresolved = sum(item.matched_index is None for item in getattr(self, "_project_relink_diagnostics", ()))
        return f"CAD revision {getattr(self, '_project_source_status', 'unverified')}. {unresolved} saved feature link(s) need review."

    def _project_manual_relink(self, feature_id, entity_index):
        if getattr(self, "_project_revision_pending", False):
            raise ValueError("Accept the loaded CAD revision before reconnecting saved features.")
        feature = self.project.features.get(feature_id)
        if feature is None or feature.part_definition_id != self._active_part_id:
            raise ValueError("Select a saved feature from the active part.")
        signature = validate_manual_assignment(feature, entity_index, self._project_relink_candidates,
                                               self._project_relink_assignments())
        info = self._project_relink_infos[entity_index]
        previous = self._entity_by_feature_id.get(feature_id)
        if previous is not None and previous is not info:
            previous.pop("feature_id", None)
        feature.signature = signature.to_dict()
        feature.metadata["manual_relink"] = {"created_at": datetime.now(timezone.utc).isoformat(),
                                            "source_sha256": self._project_loaded_source_evidence.get(self._active_part_id, {}).get("loaded_sha256")}
        info["feature_id"] = feature.id
        self._entity_by_feature_id[feature.id] = info
        self._project_refresh_relinked_geometry()
        self._project_refresh_relink_diagnostics()
        self._project_invalidate_all_reports()
        self._project_note_change()
        return feature.id

    def _project_refresh_relinked_geometry(self):
        """Refresh only CAD-derived datum values; preserve all raw editor rows."""
        self._current_drf = None
        system = self.project.datum_systems.get(self._active_datum_system_id)
        for index, slot in enumerate(("Primary", "Secondary", "Tertiary")):
            entry = self._datum_slot[slot]
            if entry is None and not getattr(self, "_project_preserve_raw_geometry", False) and system and index < len(system.datum_reference_ids):
                reference = self.project.datum_references[system.datum_reference_ids[index]]
                entry = {"feature_id": reference.feature_id, "datum_ref_id": reference.id}
            if entry is None:
                continue
            info = self._entity_by_feature_id.get(entry.get("feature_id"))
            if info is not None:
                point, direction, description = self._gdt_extract_datum_geometry(info)
                if point is not None and direction is not None:
                    self._datum_slot[slot] = {**entry, "point": point, "direction": direction,
                                             "description": description, "kind": self._gdt_datum_kind(info)}
        self._update_datum_labels()
        self.drf_status_label.setText("Feature links changed. Rebuild the datum frame before evaluation.")
        self._project_restore_stack_links()
