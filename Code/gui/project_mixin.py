"""Bridge between GUI interactions and the persistent Project domain model."""

from pathlib import Path
from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog, QMessageBox

from tolstack import (
    DatumReference, DatumSystem, Distribution, FeatureDefinition,
    LinearStackDefinition, PartDefinition, PartOccurrence, Project,
    StackTerm, ToleranceDefinition, PositionControlDefinition,
    PositionPatternMember,
)
from tolstack.domain import new_id
from tolstack.features import FeatureSignature, match_signature, signature_from_points
from tolstack.gdt import PatternFeature, PatternPositionControl
from tolstack.workflow import validate_workspace_project, require_supported_distribution
from gui.analysis_mixin import AnalysisMixin


class ProjectMixin:
    """Owns the current Project and translates GUI state at its boundary."""

    TOLERANCE_ID_ROLE = Qt.UserRole + 201
    STACK_TERM_ID_ROLE = Qt.UserRole + 202
    PATTERN_FEATURE_ID_ROLE = Qt.UserRole + 211
    PATTERN_MEMBER_ID_ROLE = Qt.UserRole + 212
    PATTERN_SIZE_TOLERANCE_ID_ROLE = Qt.UserRole + 213
    PATTERN_X_TOLERANCE_ID_ROLE = Qt.UserRole + 214
    PATTERN_Y_TOLERANCE_ID_ROLE = Qt.UserRole + 215

    def _project_init_state(self):
        self.project = Project("Untitled")
        self._project_path = None
        self._active_part_id = None
        self._active_occurrence_id = None
        self._active_datum_system_id = None
        self._active_position_control_id = None
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
        self._active_position_control_id = None
        self._entity_by_feature_id = {}
        self.table.setRowCount(0)
        self.pattern_table.setRowCount(0)
        for slot in ("Primary", "Secondary", "Tertiary"):
            self._datum_slot[slot] = None
        self._current_drf = None
        self._update_datum_labels()
        self.drf_status_label.setText("Datum reference frame not built yet.")
        self.clear_step_preview()
        self._project_update_title()
        self._study_restore()

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open TolForge project", "", "TolForge projects (*.tolforge.json);;JSON (*.json)"
        )
        if not path:
            return
        try:
            project = Project.load(path)
            validate_workspace_project(project)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            QMessageBox.warning(self, "Could not open project", str(exc))
            return

        self.clear_step_preview()
        self.project = project
        self._project_path = path
        self._active_part_id = next(iter(project.parts), None)
        self._active_occurrence_id = next(
            (item.id for item in project.occurrences.values()
             if item.part_definition_id == self._active_part_id),
            None,
        )
        self._active_datum_system_id = next(iter(project.datum_systems), None)
        self._active_position_control_id = next(iter(project.position_controls), None)
        self._entity_by_feature_id = {}
        self._project_restore_stack_to_ui()
        self._study_restore()
        self.pattern_table.setRowCount(0)
        for slot in ("Primary", "Secondary", "Tertiary"):
            self._datum_slot[slot] = None
        self._current_drf = None
        self._update_datum_labels()
        self.drf_status_label.setText("Datum reference frame awaiting geometry.")
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
        previous = deepcopy(self.project)
        try:
            self._study_capture()
            datum_count = sum(entry is not None for entry in self._datum_slot.values())
            if datum_count not in (0, 3) or (self.project.datum_systems and datum_count != 3):
                raise ValueError("Complete the A/B/C datum selection before saving. The existing saved datum system has not been replaced.")
            if self.project.position_controls and not self.pattern_table.rowCount():
                if any(member.feature_id not in self._entity_by_feature_id
                       for control in self.project.position_controls.values() for member in control.members):
                    raise ValueError("Reattach the saved pattern geometry before saving; unresolved definitions must not be discarded.")
            self._project_sync_stack_from_ui()
            self._project_sync_datums_from_ui()
            self._project_sync_position_from_ui()
            self.project.save(path)
        except (OSError, ValueError) as exc:
            self.project = previous
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
        self._project_restore_position_control()

    def _project_register_feature(self, info: dict, label: str | None = None) -> str:
        current_id = info.get("feature_id")
        if current_id in self.project.features:
            return current_id
        if self._active_part_id is None:
            raise ValueError("Load a STEP part before registering a feature.")

        signature = signature_from_points(info["type"], info["points"], info.get("circle"), info.get("surface"))
        if signature is None:
            raise ValueError("The selected entity has no usable geometry signature.")
        kind = {
            "circle": "circle", "cylinder": "cylinder", "plane": "plane", "point": "point", "generic": "generic"
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
                        signature_from_points(info["type"], info["points"], circle,
                                              info.get("surface") if target.kind == "cylinder" else None)
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
        dimensions = AnalysisMixin._build_stack(self).dimensions
        stack = next(iter(self.project.stacks.values()), None)
        if stack is None:
            stack = LinearStackDefinition("Main stack")
            self.project.stacks[stack.id] = stack

        previous_tolerance_ids = {term.tolerance_id for term in stack.terms}
        terms = []
        for row, dimension in enumerate(dimensions):
            name_item = self.table.item(row, 0)
            name, nominal = dimension.name, dimension.nominal
            tol_plus, tol_minus = dimension.tol_plus, dimension.tol_minus
            sign = 1 if dimension.sign == "+" else -1
            distribution = (
                Distribution("normal", {"cpk": dimension.cpk})
                if dimension.cpk is not None else Distribution("uniform")
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

        system = self.project.datum_systems.get(self._active_datum_system_id)
        old_ids = list(system.datum_reference_ids) if system else []
        references = []
        for index, (label, entry) in enumerate(zip(("A", "B", "C"), entries)):
            reference_id = entry.get("datum_ref_id")
            if reference_id not in self.project.datum_references:
                reference_id = old_ids[index] if index < len(old_ids) else new_id()
            reference = DatumReference(entry["feature_id"], label, id=reference_id)
            self.project.datum_references[reference.id] = reference
            references.append(reference)
            entry["datum_ref_id"] = reference.id
        for stale_id in set(old_ids) - {item.id for item in references}:
            self.project.datum_references.pop(stale_id, None)
        if system is None:
            system = DatumSystem(
                "Primary datum reference frame", [item.id for item in references]
            )
        else:
            system.name = "Primary datum reference frame"
            system.datum_reference_ids = [item.id for item in references]
        self.project.datum_systems[system.id] = system
        self._active_datum_system_id = system.id

    def _project_restore_datums(self):
        self._current_drf = None
        self._datum_slot = {"Primary": None, "Secondary": None, "Tertiary": None}
        system = self.project.datum_systems.get(self._active_datum_system_id)
        if system is None:
            self._update_datum_labels()
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
                "kind": self._gdt_datum_kind(info),
            }
        self._update_datum_labels()
        if all(self._datum_slot[slot] is not None for slot in slots):
            self.build_datum_frame()

    # ------------------------------------------------------------------
    # Position-control persistence and analysis adapter
    # ------------------------------------------------------------------

    def _project_sync_position_from_ui(self):
        if self.pattern_table.rowCount() == 0:
            control = self.project.position_controls.pop(
                self._active_position_control_id, None
            )
            if control:
                referenced = {
                    term.tolerance_id
                    for stack in self.project.stacks.values()
                    for term in stack.terms
                }
                for member in control.members:
                    for tolerance_id in (
                        member.size_tolerance_id,
                        member.position_x_tolerance_id,
                        member.position_y_tolerance_id,
                    ):
                        if tolerance_id not in referenced:
                            self.project.tolerances.pop(tolerance_id, None)
            self._active_position_control_id = None
            return
        if self._active_datum_system_id not in self.project.datum_systems:
            raise ValueError("Build a complete datum reference frame before saving the pattern.")

        control = self.project.position_controls.get(self._active_position_control_id)
        if control is None:
            control = PositionControlDefinition(
                "Position control", self._active_datum_system_id, 0.0
            )
            self.project.position_controls[control.id] = control
            self._active_position_control_id = control.id

        previous_tolerance_ids = {
            tolerance_id
            for member in control.members
            for tolerance_id in (
                member.size_tolerance_id,
                member.position_x_tolerance_id,
                member.position_y_tolerance_id,
            )
        }
        members = []
        for row in range(self.pattern_table.rowCount()):
            def cell(column):
                item = self.pattern_table.item(row, column)
                return item.text().strip() if item else ""

            name_item = self.pattern_table.item(row, 0)
            feature_id = name_item.data(self.PATTERN_FEATURE_ID_ROLE) if name_item else None
            if feature_id not in self.project.features:
                raise ValueError(f"Pattern row {row + 1} is not linked to a persistent feature.")

            member_id = name_item.data(self.PATTERN_MEMBER_ID_ROLE) or new_id()
            size_id = name_item.data(self.PATTERN_SIZE_TOLERANCE_ID_ROLE) or new_id()
            x_id = name_item.data(self.PATTERN_X_TOLERANCE_ID_ROLE) or new_id()
            y_id = name_item.data(self.PATTERN_Y_TOLERANCE_ID_ROLE) or new_id()
            size_tol = float(cell(8) or 0.0)
            x_tol = float(cell(6) or 0.0)
            y_tol = float(cell(7) or 0.0)
            common = {"feature_id": feature_id, "distribution": Distribution("uniform")}
            self.project.tolerances[size_id] = ToleranceDefinition(
                f"{cell(0)} size", "size", float(cell(5)), size_tol, size_tol,
                id=size_id, **common,
            )
            self.project.tolerances[x_id] = ToleranceDefinition(
                f"{cell(0)} X position", "position", 0.0, x_tol, x_tol,
                id=x_id, **common,
            )
            self.project.tolerances[y_id] = ToleranceDefinition(
                f"{cell(0)} Y position", "position", 0.0, y_tol, y_tol,
                id=y_id, **common,
            )
            member = PositionPatternMember(
                cell(0), feature_id, float(cell(1)), float(cell(2)),
                size_id, x_id, y_id, id=member_id,
            )
            members.append(member)
            name_item.setData(self.PATTERN_MEMBER_ID_ROLE, member_id)
            name_item.setData(self.PATTERN_SIZE_TOLERANCE_ID_ROLE, size_id)
            name_item.setData(self.PATTERN_X_TOLERANCE_ID_ROLE, x_id)
            name_item.setData(self.PATTERN_Y_TOLERANCE_ID_ROLE, y_id)

        try:
            base_tolerance = float(self.gdt_base_tolerance_input.text() or 0.0)
            mmc_size = float(self.gdt_mmc_size_input.text() or 0.0)
            lmc_size = float(self.gdt_lmc_size_input.text() or 0.0)
        except ValueError as exc:
            raise ValueError("Position tolerance, MMC size, and LMC size must be numbers.") from exc
        control.datum_system_id = self._active_datum_system_id
        control.base_tolerance_diameter = base_tolerance
        control.modifier = self.gdt_modifier_combo.currentText()
        control.mmc_size = mmc_size
        control.lmc_size = lmc_size
        control.feature_kind = self.gdt_feature_kind_combo.currentText()
        control.members = members
        control.__post_init__()

        live_ids = {
            tolerance_id
            for value in self.project.position_controls.values()
            for member in value.members
            for tolerance_id in (
                member.size_tolerance_id,
                member.position_x_tolerance_id,
                member.position_y_tolerance_id,
            )
        }
        live_ids.update(
            term.tolerance_id for stack in self.project.stacks.values() for term in stack.terms
        )
        for tolerance_id in previous_tolerance_ids - live_ids:
            self.project.tolerances.pop(tolerance_id, None)

    def _project_restore_position_control(self):
        self.pattern_table.setRowCount(0)
        control = self.project.position_controls.get(self._active_position_control_id)
        if control is None:
            return
        self.gdt_base_tolerance_input.setText(str(control.base_tolerance_diameter))
        self.gdt_modifier_combo.setCurrentText(control.modifier)
        self.gdt_mmc_size_input.setText(str(control.mmc_size))
        self.gdt_lmc_size_input.setText(str(control.lmc_size))
        self.gdt_feature_kind_combo.setCurrentText(control.feature_kind)
        if self._current_drf is None:
            return

        for member in control.members:
            info = self._entity_by_feature_id.get(member.feature_id)
            if info is None:
                continue
            self._measure_ensure_circle_fit(info)
            circle = info.get("circle")
            if circle is None:
                continue
            actual_x, actual_y = self._current_drf.to_local_xy(circle["center"])
            size = self.project.tolerances[member.size_tolerance_id]
            x_variation = self.project.tolerances[member.position_x_tolerance_id]
            y_variation = self.project.tolerances[member.position_y_tolerance_id]
            row = self.pattern_table.rowCount()
            self._pattern_add_row(
                member.name, member.basic_x, member.basic_y, actual_x, actual_y,
                size.nominal, feature_id=member.feature_id,
            )
            self.pattern_table.item(row, 6).setText(str(x_variation.tolerance_plus))
            self.pattern_table.item(row, 7).setText(str(y_variation.tolerance_plus))
            self.pattern_table.item(row, 8).setText(str(size.tolerance_plus))
            name_item = self.pattern_table.item(row, 0)
            name_item.setData(self.PATTERN_MEMBER_ID_ROLE, member.id)
            name_item.setData(self.PATTERN_SIZE_TOLERANCE_ID_ROLE, size.id)
            name_item.setData(self.PATTERN_X_TOLERANCE_ID_ROLE, x_variation.id)
            name_item.setData(self.PATTERN_Y_TOLERANCE_ID_ROLE, y_variation.id)

    @staticmethod
    def _cpk_from_distribution(distribution: Distribution) -> float | None:
        if distribution.kind != "normal":
            return None
        value = distribution.parameters.get("cpk")
        return float(value) if value is not None else None

    def _project_build_pattern_control(self) -> PatternPositionControl:
        if self._current_drf is None or any(entry is None for entry in getattr(self, "_datum_slot", {}).values()):
            raise ValueError("Build a complete datum reference frame before evaluation.")
        if self.project.units.length != "mm" or self.project.units.angle != "deg":
            raise ValueError("CAD/GD&T analysis currently requires mm and deg. Automatic conversion is not implemented.")
        for system in self.project.datum_systems.values():
            if any(self.project.datum_references[ref].modifier != "RFS" for ref in system.datum_reference_ids):
                raise ValueError("Datum material-boundary modifiers and datum mobility are not supported.")
        for tolerance in self.project.tolerances.values():
            require_supported_distribution(tolerance.distribution, tolerance.name)
        self._project_sync_datums_from_ui()
        self._project_sync_position_from_ui()
        control = self.project.position_controls.get(self._active_position_control_id)
        if control is None or not control.members:
            raise ValueError("No persistent position-control pattern is defined.")
        if self._current_drf is None:
            raise ValueError("Build the datum reference frame before evaluation.")

        features = []
        for member in control.members:
            info = self._entity_by_feature_id.get(member.feature_id)
            if info is None:
                raise ValueError(f"Feature '{member.name}' is not attached to loaded geometry.")
            self._measure_ensure_circle_fit(info)
            circle = info.get("circle")
            if circle is None:
                raise ValueError(f"Feature '{member.name}' is no longer circular.")
            actual_x, actual_y = self._current_drf.to_local_xy(circle["center"])
            size = self.project.tolerances[member.size_tolerance_id]
            x_variation = self.project.tolerances[member.position_x_tolerance_id]
            y_variation = self.project.tolerances[member.position_y_tolerance_id]
            features.append(PatternFeature(
                name=member.name,
                basic_x=member.basic_x, basic_y=member.basic_y,
                actual_x=actual_x, actual_y=actual_y,
                size_nominal=size.nominal,
                size_tol_plus=size.tolerance_plus,
                size_tol_minus=size.tolerance_minus,
                size_cpk=self._cpk_from_distribution(size.distribution),
                position_tol_plus_x=x_variation.tolerance_plus,
                position_tol_minus_x=x_variation.tolerance_minus,
                position_tol_plus_y=y_variation.tolerance_plus,
                position_tol_minus_y=y_variation.tolerance_minus,
                position_cpk=(
                    self._cpk_from_distribution(x_variation.distribution)
                    or self._cpk_from_distribution(y_variation.distribution)
                ),
            ))
        return PatternPositionControl(
            features=features,
            base_tolerance_diameter=control.base_tolerance_diameter,
            modifier=control.modifier,
            mmc_size=control.mmc_size,
            lmc_size=control.lmc_size,
            feature_kind=control.feature_kind,
        )
