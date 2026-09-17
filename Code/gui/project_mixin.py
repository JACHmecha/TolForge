"""Bridge between GUI interactions and the persistent Project domain model."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog, QMessageBox

from tolstack import (
    DatumReference, DatumSystem, Distribution, FeatureDefinition,
    LinearStackDefinition, PartDefinition, PartOccurrence, Project,
    StackTerm, ToleranceDefinition,
)
from tolstack.domain import new_id
from tolstack.features import FeatureSignature, match_signature, signature_from_points


class ProjectMixin:
    """Owns the current Project and translates GUI state at its boundary."""

    TOLERANCE_ID_ROLE = Qt.UserRole + 201
    STACK_TERM_ID_ROLE = Qt.UserRole + 202

    def _project_init_state(self):
        self.project = Project("Untitled")
        self._project_path = None
        self._active_part_id = None
        self._active_occurrence_id = None
        self._active_datum_system_id = None
        self._entity_by_feature_id = {}

    def _project_install_menu(self):
        menu = self.menuBar().addMenu("&File")
        actions = (
            ("&New Project", self.new_project),
            ("&Open Project...", self.open_project),
            ("&Save Project", self.save_project),
            ("Save Project &As...", self.save_project_as),
        )
        for text, slot in actions:
            action = QAction(text, self)
            action.triggered.connect(slot)
            menu.addAction(action)

    def new_project(self):
        self.project = Project("Untitled")
        self._project_path = None
        self._active_part_id = None
        self._active_occurrence_id = None
        self._active_datum_system_id = None
        self._entity_by_feature_id = {}
        self.table.setRowCount(0)
        for slot in ("Primary", "Secondary", "Tertiary"):
            self._datum_slot[slot] = None
        self._current_drf = None
        self._update_datum_labels()
        self.drf_status_label.setText("Datum reference frame not built yet.")
        self.clear_step_preview()
        self._project_update_title()

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open TolForge project", "", "TolForge projects (*.tolforge.json);;JSON (*.json)"
        )
        if not path:
            return
        try:
            project = Project.load(path)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            QMessageBox.warning(self, "Could not open project", str(exc))
            return

        self.project = project
        self._project_path = path
        self._active_part_id = next(iter(project.parts), None)
        self._active_occurrence_id = next(
            (item.id for item in project.occurrences.values()
             if item.part_definition_id == self._active_part_id),
            None,
        )
        self._active_datum_system_id = next(iter(project.datum_systems), None)
        self._entity_by_feature_id = {}
        self._project_restore_stack_to_ui()
        self._project_update_title()

        part = project.parts.get(self._active_part_id)
        if part and part.source_file and Path(part.source_file).is_file():
            self._start_step_load(part.source_file)
        else:
            self.step_status_label.setText(
                "Project loaded. Its STEP source is unavailable; choose Load STEP to relink geometry."
            )

    def save_project(self):
        if self._project_path is None:
            self.save_project_as()
            return
        self._project_save_to(self._project_path)

    def save_project_as(self):
        default_name = f"{self.project.name or 'project'}.tolforge.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save TolForge project", default_name,
            "TolForge projects (*.tolforge.json);;JSON (*.json)",
        )
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".tolforge.json"
        self._project_save_to(path)

    def _project_save_to(self, path: str):
        try:
            self._project_sync_stack_from_ui()
            self._project_sync_datums_from_ui()
            self.project.save(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Could not save project", str(exc))
            return
        self._project_path = path
        self._project_update_title()
        self.step_status_label.setText(f"Saved project: {Path(path).name}")

    def _project_update_title(self):
        suffix = Path(self._project_path).name if self._project_path else "Unsaved"
        self.setWindowTitle(f"Tol-Forge — {self.project.name} [{suffix}]")

    # ------------------------------------------------------------------
    # STEP source and stable feature identities
    # ------------------------------------------------------------------

    def _project_on_step_loaded(self, path: str):
        normalized = str(Path(path).resolve())
        part = next(
            (item for item in self.project.parts.values()
             if item.source_file and str(Path(item.source_file).resolve()) == normalized),
            None,
        )
        # Opening a saved single-part project and choosing the same CAD file
        # from a new location is a relink, not a second part definition.
        if part is None and self._project_path is not None and self._active_part_id:
            part = self.project.parts.get(self._active_part_id)
            if part is not None:
                part.source_file = normalized
        if part is None:
            part = self.project.add_part(
                PartDefinition(name=Path(path).stem, source_file=normalized)
            )
            occurrence = self.project.add_occurrence(
                PartOccurrence(part.id, f"{part.name}:1", grounded=not self.project.occurrences)
            )
        else:
            occurrence = next(
                (item for item in self.project.occurrences.values()
                 if item.part_definition_id == part.id),
                None,
            )
            if occurrence is None:
                occurrence = self.project.add_occurrence(
                    PartOccurrence(part.id, f"{part.name}:1", grounded=not self.project.occurrences)
                )
        self._active_part_id = part.id
        self._active_occurrence_id = occurrence.id
        self._project_reattach_features()
        self._project_restore_stack_links()
        self._project_restore_datums()

    def _project_register_feature(self, info: dict, label: str | None = None) -> str:
        current_id = info.get("feature_id")
        if current_id in self.project.features:
            return current_id
        if self._active_part_id is None:
            raise ValueError("Load a STEP part before registering a feature.")

        signature = signature_from_points(info["type"], info["points"], info.get("circle"))
        if signature is None:
            raise ValueError("The selected entity has no usable geometry signature.")
        kind = {
            "circle": "circle", "plane": "plane", "point": "point", "generic": "generic"
        }[signature.kind]
        feature = self.project.add_feature(
            FeatureDefinition(
                self._active_part_id,
                label or f"{info['type'].title()} {info['index'] + 1}",
                kind,
                signature=signature.to_dict(),
            )
        )
        info["feature_id"] = feature.id
        self._entity_by_feature_id[feature.id] = info
        return feature.id

    def _project_find_entity_info(self, feature_id: str) -> dict | None:
        return self._entity_by_feature_id.get(feature_id)

    def _project_reattach_features(self):
        self._entity_by_feature_id = {}
        saved = [
            feature for feature in self.project.features.values()
            if feature.part_definition_id == self._active_part_id and feature.signature
        ]
        if not saved:
            return

        infos = list(self._step_entity_info.values())
        candidates_by_kind = {}
        used = set()
        unresolved = 0
        for feature in saved:
            target = FeatureSignature.from_dict(feature.signature)
            if target.kind not in candidates_by_kind:
                candidates = []
                for info in infos:
                    circle = None
                    if target.kind == "circle" and info["type"] in ("face", "edge"):
                        self._measure_ensure_circle_fit(info)
                        circle = info.get("circle")
                    candidates.append(
                        signature_from_points(info["type"], info["points"], circle)
                    )
                candidates_by_kind[target.kind] = candidates
            candidates = candidates_by_kind[target.kind]
            eligible = [(index, candidate) for index, candidate in enumerate(candidates)
                        if candidate is not None and index not in used]
            result = match_signature(target, [candidate for _, candidate in eligible])
            if result.matched_index is None or result.confidence == "ambiguous":
                unresolved += 1
                continue
            info_index = eligible[result.matched_index][0]
            info = infos[info_index]
            info["feature_id"] = feature.id
            self._entity_by_feature_id[feature.id] = info
            used.add(info_index)
        if unresolved:
            self.step_status_label.setText(
                f"Geometry loaded; {unresolved} saved feature link(s) need manual relinking."
            )

    # ------------------------------------------------------------------
    # Stack table persistence
    # ------------------------------------------------------------------

    def _project_sync_stack_from_ui(self):
        stack = next(iter(self.project.stacks.values()), None)
        if stack is None:
            stack = LinearStackDefinition("Main stack")
            self.project.stacks[stack.id] = stack

        previous_tolerance_ids = {term.tolerance_id for term in stack.terms}
        terms = []
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            if name_item is None:
                continue
            name = name_item.text().strip() or f"Dimension {row + 1}"
            nominal = float(self.table.item(row, 1).text())
            tol_plus = float(self.table.item(row, 2).text())
            tol_minus = float(self.table.item(row, 3).text())
            sign = 1 if self._get_sign_from_row(row) == "+" else -1
            cpk_item = self.table.item(row, 5)
            cpk_text = cpk_item.text().strip() if cpk_item else ""
            distribution = (
                Distribution("normal", {"cpk": float(cpk_text)})
                if cpk_text else Distribution("uniform")
            )
            link = name_item.data(self.LINK_ROLE) or {}
            feature_id = link.get("feature_id")
            mode = link.get("mode")
            tolerance_id = name_item.data(self.TOLERANCE_ID_ROLE) or new_id()
            term_id = name_item.data(self.STACK_TERM_ID_ROLE) or new_id()
            tolerance_kind = {
                "diametral": "size", "positional": "position", "normal_offset": "distance"
            }.get(mode, "distance")
            self.project.tolerances[tolerance_id] = ToleranceDefinition(
                name, tolerance_kind, nominal, tol_plus, tol_minus,
                feature_id=feature_id, distribution=distribution, id=tolerance_id,
            )
            terms.append(StackTerm(tolerance_id, sign, mode, id=term_id))
            name_item.setData(self.TOLERANCE_ID_ROLE, tolerance_id)
            name_item.setData(self.STACK_TERM_ID_ROLE, term_id)
        stack.terms = terms

        live_ids = {term.tolerance_id for value in self.project.stacks.values() for term in value.terms}
        for tolerance_id in previous_tolerance_ids - live_ids:
            self.project.tolerances.pop(tolerance_id, None)
        self.project.validate()

    def _project_restore_stack_to_ui(self):
        self.table.setRowCount(0)
        stack = next(iter(self.project.stacks.values()), None)
        if stack is None:
            return
        for term in stack.terms:
            tolerance = self.project.tolerances[term.tolerance_id]
            cpk = tolerance.distribution.parameters.get("cpk") if tolerance.distribution.kind == "normal" else None
            row = self.table.rowCount()
            self._add_table_row(
                tolerance.name, tolerance.nominal, tolerance.tolerance_plus,
                tolerance.tolerance_minus, term.sign, cpk,
            )
            name_item = self.table.item(row, 0)
            name_item.setData(self.TOLERANCE_ID_ROLE, tolerance.id)
            name_item.setData(self.STACK_TERM_ID_ROLE, term.id)
            if tolerance.feature_id and term.preview_mode:
                self._stack_link_set_row_link(
                    row, {"feature_id": tolerance.feature_id, "mode": term.preview_mode}
                )

    def _project_restore_stack_links(self):
        for row, link, _value, _nominal in self._stack_link_read_all():
            if link.get("feature_id") in self._entity_by_feature_id:
                self._stack_link_install_slider(row)
        self._stack_link_rebuild_preview()

    # ------------------------------------------------------------------
    # Datum persistence
    # ------------------------------------------------------------------

    def _project_sync_datums_from_ui(self):
        entries = [self._datum_slot[name] for name in ("Primary", "Secondary", "Tertiary")]
        if any(entry is None or not entry.get("feature_id") for entry in entries):
            return

        old_system = self.project.datum_systems.pop(self._active_datum_system_id, None)
        if old_system:
            for datum_id in old_system.datum_reference_ids:
                self.project.datum_references.pop(datum_id, None)

        references = []
        for label, entry in zip(("A", "B", "C"), entries):
            reference = DatumReference(entry["feature_id"], label)
            self.project.datum_references[reference.id] = reference
            references.append(reference)
            entry["datum_ref_id"] = reference.id
        system = DatumSystem("Primary datum reference frame", [item.id for item in references])
        self.project.datum_systems[system.id] = system
        self._active_datum_system_id = system.id

    def _project_restore_datums(self):
        system = self.project.datum_systems.get(self._active_datum_system_id)
        if system is None:
            return
        slots = ("Primary", "Secondary", "Tertiary")
        for slot, datum_id in zip(slots, system.datum_reference_ids):
            datum = self.project.datum_references.get(datum_id)
            info = self._entity_by_feature_id.get(datum.feature_id) if datum else None
            if info is None:
                self._datum_slot[slot] = None
                continue
            point, direction, description = self._gdt_extract_datum_geometry(info)
            if point is None:
                self._datum_slot[slot] = None
                continue
            self._datum_slot[slot] = {
                "point": point, "direction": direction, "description": description,
                "feature_id": datum.feature_id, "datum_ref_id": datum.id,
            }
        self._update_datum_labels()
        if all(self._datum_slot[slot] is not None for slot in slots):
            self.build_datum_frame()
