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
from tolstack.features import signature_from_points
from tolstack.relinking import plan_relinking, portable_source_path, resolve_source_path, source_revision_status
from tolstack.gdt import PatternFeature, PatternPositionControl
from tolstack.workflow import validate_workspace_project, require_supported_distribution
from tolstack.persistence import backup_path
from gui.analysis_mixin import AnalysisMixin
from gui.gdt_mixin import pattern_cell_value
from gui.project_lifecycle import ProjectLifecycleMixin
from gui.feature_relinking import FeatureRelinkingMixin


class ProjectMixin(FeatureRelinkingMixin, ProjectLifecycleMixin):
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
        self._project_recovered_from = None
        self._active_part_id = None
        self._active_occurrence_id = None
        self._active_datum_system_id = None
        self._active_position_control_id = None
        self._entity_by_feature_id = {}
        self._project_pending_raw_geometry = None
        self._project_step_precommit_was_dirty = None
        self._project_clear_loaded_source_evidence()
        self._project_lifecycle_init()

    def _project_install_menu(self):
        menu = self.menuBar().addMenu("&File")
        actions = (
            ("&New Project", self.new_project),
            ("&Open Project...", self.open_project),
            ("Open &Previous Saved Version...", self.open_previous_project),
            ("&Save Project", self.save_project),
            ("Save Project &As...", self.save_project_as),
            ("Save &Recovery Draft...", self.save_recovery_draft),
            ("Recover &Incomplete Work...", self.open_recovery_draft),
        )
        for text, slot in actions:
            action = QAction(text, self)
            action.triggered.connect(slot)
            menu.addAction(action)

    def new_project(self):
        if not self._project_may_replace("creating a new project"):
            return False
        self._project_clear_auto_draft()
        with self._project_suspend_changes():
            self._project_preserve_raw_geometry = False
            self._project_pending_raw_geometry = None
            self._project_step_precommit_was_dirty = None
            self.project = Project("Untitled")
            self._project_path = None
            self._project_recovered_from = None
            self._active_part_id = None
            self._active_occurrence_id = None
            self._active_datum_system_id = None
            self._active_position_control_id = None
            self._entity_by_feature_id = {}
            self._project_clear_loaded_source_evidence()
            self.table.setRowCount(0)
            self.pattern_table.setRowCount(0)
            for slot in ("Primary", "Secondary", "Tertiary"):
                self._datum_slot[slot] = None
            self._current_drf = None
            self._update_datum_labels()
            self.drf_status_label.setText("Datum reference frame not built yet.")
            self.clear_step_preview()
            self._study_restore()
            self._project_restore_projected_interference()
        self._project_mark_clean()
        self._project_update_title()
        return True

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open TolForge project", "", "TolForge projects (*.tolforge.json);;JSON (*.json)"
        )
        if not path:
            return False
        return self._project_open_from(path)

    def open_previous_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose project to recover", "",
            "TolForge projects (*.tolforge.json);;JSON (*.json);;All files (*)",
        )
        if not path:
            return False
        return self._project_open_from(backup_path(path), recovered_from=path)

    def _project_open_from(self, path, *, recovered_from=None):
        try:
            project = Project.load(path)
            validate_workspace_project(project)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            QMessageBox.warning(self, "Could not open project", str(exc))
            return False
        if not self._project_may_replace("opening another project"):
            return False
        if self._project_guard_saved:
            try:
                # The guard can save to the selected file (or rotate its
                # previous version). Load what is actually on disk now.
                project = Project.load(path)
                validate_workspace_project(project)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                QMessageBox.warning(self, "Could not open project", str(exc))
                return False

        self._project_clear_auto_draft()
        with self._project_suspend_changes():
            self._project_preserve_raw_geometry = False
            self._project_pending_raw_geometry = None
            self._project_step_precommit_was_dirty = None
            self.clear_step_preview()
            self.project = project
            # Recovery always requires Save As; opening a backup does not
            # establish a destination that a later Save could overwrite.
            self._project_path = None if recovered_from is not None else str(path)
            self._project_recovered_from = str(recovered_from) if recovered_from is not None else None
            self._active_part_id = next(iter(project.parts), None)
            self._active_occurrence_id = next(
                (item.id for item in project.occurrences.values()
                 if item.part_definition_id == self._active_part_id), None,
            )
            self._active_datum_system_id = next(iter(project.datum_systems), None)
            self._active_position_control_id = next(iter(project.position_controls), None)
            self._entity_by_feature_id = {}
            self._project_clear_loaded_source_evidence()
            self._project_restore_stack_to_ui()
            self._study_restore()
            self._project_restore_projected_interference()
            self.pattern_table.setRowCount(0)
            for slot in ("Primary", "Secondary", "Tertiary"):
                self._datum_slot[slot] = None
            self._current_drf = None
            self._update_datum_labels()
            self.drf_status_label.setText("Datum reference frame awaiting geometry.")
            self._project_restore_position_control()
        self._project_mark_clean(recovered=recovered_from is not None)
        self._project_update_title()

        part = project.parts.get(self._active_part_id)
        source = self._project_resolve_source(part) if part else None
        if source is not None and source.is_file():
            self._start_step_load(str(source))
            self._project_loading_clean_from_disk = recovered_from is None and self._step_load_thread is not None
        else:
            self.step_status_label.setText(
                "Project loaded. Its STEP source is unavailable; choose Load STEP to relink geometry."
            )
        if recovered_from is not None:
            self.step_status_label.setText(
                f"Recovered previous version of {Path(recovered_from).name}. "
                "Use Save As to keep it."
            )
        return True

    def save_project(self):
        if self._project_path is None:
            return self.save_project_as()
        return self._project_save_to(self._project_path)

    def save_project_as(self):
        default_name = f"{self.project.name or 'project'}.tolforge.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save TolForge project", default_name,
            "TolForge projects (*.tolforge.json);;JSON (*.json)",
        )
        if not path:
            return False
        if not path.lower().endswith(".json"):
            path += ".tolforge.json"
        return self._project_save_to(path)

    def _project_save_to(self, path: str):
        previous = deepcopy(self.project)
        previous_active_ids = {
            name: getattr(self, name)
            for name in ("_active_datum_system_id", "_active_position_control_id")
        }
        try:
            with self._project_suspend_changes():
                if getattr(self, "_project_revision_pending", False):
                    raise ValueError("Review and accept the loaded CAD revision before saving an engineering project.")
                self._study_capture()
                self._project_sync_projected_interference()
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
                # Save As rebases each known path against the new project
                # location; loaded evidence continues to use absolute paths.
                for part in self.project.parts.values():
                    source = self._project_resolve_source(part)
                    if source is not None:
                        part.source_file = portable_source_path(source, path)
                self.project.save(path)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.project = previous
            for name, value in previous_active_ids.items():
                setattr(self, name, value)
            QMessageBox.warning(self, "Could not save project", str(exc))
            self._project_note_change()
            return False
        self._project_path = path
        self._project_recovered_from = None
        self._project_preserve_raw_geometry = False
        self._project_clear_auto_draft()
        self._project_mark_clean()
        self._project_update_title()
        self.step_status_label.setText(f"Saved project: {Path(path).name}")
        return True

    def _project_sync_projected_interference(self):
        capture = getattr(self, "_eclipse_save_settings", None)
        if capture is None:
            return
        settings = capture()
        if settings is None:
            self.project.study.pop("projected_interference", None)
        else:
            from tolstack.projected_study import validate_projected_interference
            validate_projected_interference(settings)
            self.project.study["projected_interference"] = deepcopy(settings)

    def _project_restore_projected_interference(self):
        restore = getattr(self, "_eclipse_restore_settings", None)
        if restore is not None:
            restore(deepcopy(self.project.study.get("projected_interference")))

    def _project_update_title(self):
        suffix = Path(self._project_path).name if self._project_path else "Unsaved"
        changed = " *" if getattr(self, "_project_dirty", False) else ""
        self.setWindowTitle(f"Tol-Forge — {self.project.name}{changed} [{suffix}]")

    # ------------------------------------------------------------------
    # STEP source and stable feature identities
    # ------------------------------------------------------------------

    def _project_resolve_source(self, part):
        return resolve_source_path(part.source_file, self._project_path or getattr(self, "_project_recovered_from", None))

    def locate_project_source(self):
        part = self.project.parts.get(self._active_part_id)
        source = self._project_resolve_source(part) if part else None
        path, _ = QFileDialog.getOpenFileName(self, "Locate or reload CAD source", str(source or ""),
                                             "STEP files (*.step *.stp)")
        if not path:
            return False
        if part is not None:
            self._project_preserve_raw_geometry = True
        self._start_step_load(path)
        return True

    def _project_report_sources(self):
        descriptors = []
        for part in self.project.parts.values():
            loaded = getattr(self, "_project_loaded_source_evidence", {}).get(part.id, {})
            source = self._project_resolve_source(part)
            descriptors.append({"kind": "cad", "part_id": part.id, "reference": part.name,
                                "path": loaded.get("path") or (str(source) if source is not None else None),
                                "expected_sha256": part.source_sha256, **loaded})
        return descriptors

    def _project_on_step_loaded(self, path: str, *, source_sha256=None, source_hash_status="unverified"):
        precommit_dirty = getattr(self, "_project_step_precommit_was_dirty", None)
        was_dirty = self._project_is_dirty() if precommit_dirty is None else precommit_dirty
        self._project_step_precommit_was_dirty = None
        normalized = str(Path(path).resolve())
        part = next(
            (item for item in self.project.parts.values()
             if self._project_resolve_source(item) == Path(normalized)),
            None,
        )
        # Opening a saved single-part project and choosing the same CAD file
        # from a new location is a relink, not a second part definition.
        loaded_project = (self._project_path is not None or getattr(self, "_project_recovered_from", None) is not None
                          or getattr(self, "_project_preserve_raw_geometry", False))
        if part is None and loaded_project and self._active_part_id:
            part = self.project.parts.get(self._active_part_id)
        existing_part = part is not None
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
        # Only the loader's digest of geometry-producing bytes establishes
        # revision evidence. An arbitrary persisted hash is a comparison input.
        import re
        verified = (source_hash_status == "verified" and isinstance(source_sha256, str)
                    and re.fullmatch(r"[0-9a-fA-F]{64}", source_sha256) is not None)
        loaded_digest = source_sha256.lower() if verified else None
        self._project_source_status = source_revision_status(part.source_sha256, loaded_digest,
                                                            "verified" if verified else "unverified")
        source_metadata_changed = (self._project_resolve_source(part) != Path(normalized)
                                   or (verified and part.source_sha256 != loaded_digest))
        self._project_revision_pending = bool(existing_part and part.source_sha256
                                              and self._project_source_status != "unchanged")
        self._project_loaded_source_evidence = getattr(self, "_project_loaded_source_evidence", {})
        self._project_loaded_source_evidence[part.id] = {
            "path": normalized, "loaded_sha256": loaded_digest,
            "comparison_sha256": part.source_sha256,
            "comparison_source_path": str(self._project_resolve_source(part)) if self._project_resolve_source(part) is not None else None,
            "loaded_hash_status": "verified" if verified else "unverified",
            "loaded_capture_basis": "verified_geometry_source_bytes" if verified else "unavailable",
            "revision_status": self._project_source_status, "revision_accepted": not self._project_revision_pending,
        }
        if not self._project_revision_pending:
            if self._project_resolve_source(part) != Path(normalized):
                part.source_file = normalized
            if verified:
                part.source_sha256 = loaded_digest
        self._project_reattach_features()
        self._project_restore_stack_links()
        if getattr(self, "_project_preserve_raw_geometry", False):
            self._project_restore_raw_geometry_after_load()
        else:
            self._project_restore_datums()
            self._project_restore_position_control()
        self._project_invalidate_all_reports()
        if (getattr(self, "_project_loading_clean_from_disk", False) and not was_dirty
                and not self._project_revision_pending and not source_metadata_changed):
            self._project_mark_clean()
        else:
            self._project_note_change()
        self._project_loading_clean_from_disk = False

    def _project_accept_loaded_revision(self):
        if not getattr(self, "_project_revision_pending", False):
            return False
        part = self.project.parts[self._active_part_id]
        loaded = self._project_loaded_source_evidence[part.id]
        part.source_file = loaded["path"]
        part.source_sha256 = loaded["loaded_sha256"] if loaded["loaded_hash_status"] == "verified" else None
        loaded["revision_accepted"] = True
        self._project_revision_pending = False
        self._project_reattach_features()
        self._project_refresh_relinked_geometry()
        self._project_invalidate_all_reports()
        self._project_note_change()
        return True

    def _project_register_feature(self, info: dict, label: str | None = None) -> str:
        if getattr(self, "_project_revision_pending", False):
            raise ValueError("Accept the loaded CAD revision before registering or reconnecting features.")
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
        self._project_note_change()
        return feature.id

    def _project_find_entity_info(self, feature_id: str) -> dict | None:
        if getattr(self, "_project_revision_pending", False):
            return None
        return self._entity_by_feature_id.get(feature_id)

    def _project_reattach_features(self):
        self._entity_by_feature_id = {}
        self._project_build_relink_candidates()
        for info in self._project_relink_infos:
            info.pop("feature_id", None)
        saved = [feature for feature in self.project.features.values()
                 if feature.part_definition_id == self._active_part_id]
        self._project_relink_diagnostics = plan_relinking(
            saved, self._project_relink_candidates,
            auto_attach=not getattr(self, "_project_revision_pending", False),
        )
        for diagnostic in self._project_relink_diagnostics:
            if diagnostic.matched_index is not None:
                info = self._project_relink_infos[diagnostic.matched_index]
                info["feature_id"] = diagnostic.feature_id
                self._entity_by_feature_id[diagnostic.feature_id] = info
        unresolved = sum(item.matched_index is None for item in self._project_relink_diagnostics)
        if getattr(self, "_project_revision_pending", False):
            self.step_status_label.setText(
                f"CAD revision {self._project_source_status}. Review saved features and accept the loaded revision to reconnect."
            )
        elif unresolved:
            self.step_status_label.setText(f"Geometry loaded; {unresolved} saved feature link(s) need guided relinking.")

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
            size_tol = pattern_cell_value(self.pattern_table, row, 8, 0.0)
            x_tol = pattern_cell_value(self.pattern_table, row, 6, 0.0)
            y_tol = pattern_cell_value(self.pattern_table, row, 7, 0.0)
            common = {"feature_id": feature_id, "distribution": Distribution("uniform")}
            self.project.tolerances[size_id] = ToleranceDefinition(
                f"{cell(0)} size", "size", pattern_cell_value(self.pattern_table, row, 5), size_tol, size_tol,
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
                cell(0), feature_id, pattern_cell_value(self.pattern_table, row, 1),
                pattern_cell_value(self.pattern_table, row, 2),
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
        for member in control.members:
            info = self._entity_by_feature_id.get(member.feature_id)
            circle = None
            if info is not None:
                self._measure_ensure_circle_fit(info)
                circle = info.get("circle")
            resolved = self._current_drf is not None and circle is not None
            actual_x, actual_y = self._current_drf.to_local_xy(circle["center"]) if resolved else (0.0, 0.0)
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
            if not resolved:
                self.pattern_table.item(row, 3).setText("Unresolved")
                self.pattern_table.item(row, 4).setText("Unresolved")
                self.pattern_table.item(row, 9).setText("Reattach geometry and rebuild frame")
            name_item = self.pattern_table.item(row, 0)
            name_item.setData(self.PATTERN_MEMBER_ID_ROLE, member.id)
            name_item.setData(self.PATTERN_SIZE_TOLERANCE_ID_ROLE, size.id)
            name_item.setData(self.PATTERN_X_TOLERANCE_ID_ROLE, x_variation.id)
            name_item.setData(self.PATTERN_Y_TOLERANCE_ID_ROLE, y_variation.id)

    def _project_refresh_pattern_actual_values(self):
        """Refresh CAD-derived coordinates after an explicit frame rebuild."""
        if self._current_drf is None:
            return
        for row in range(self.pattern_table.rowCount()):
            name_item = self.pattern_table.item(row, 0)
            feature_id = name_item.data(self.PATTERN_FEATURE_ID_ROLE) if name_item else None
            info = self._entity_by_feature_id.get(feature_id)
            if info is None:
                continue
            self._measure_ensure_circle_fit(info)
            circle = info.get("circle")
            if circle is None:
                continue
            actual_x, actual_y = self._current_drf.to_local_xy(circle["center"])
            for column, value in ((3, actual_x), (4, actual_y)):
                item = self.pattern_table.item(row, column)
                if item is not None:
                    item.setData(Qt.EditRole, str(value))
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            status = self.pattern_table.item(row, 9)
            if status is not None:
                status.setText("-")

    @staticmethod
    def _cpk_from_distribution(distribution: Distribution) -> float | None:
        if distribution.kind != "normal":
            return None
        value = distribution.parameters.get("cpk")
        return float(value) if value is not None else None

    def _project_build_pattern_control(self) -> PatternPositionControl:
        if getattr(self, "_project_revision_pending", False):
            raise ValueError("Accept the loaded CAD revision before evaluating saved definitions.")
        if self._current_drf is None or any(entry is None for entry in getattr(self, "_datum_slot", {}).values()):
            raise ValueError("Build a complete datum reference frame before evaluation.")
        for slot, entry in getattr(self, "_datum_slot", {}).items():
            info = self._entity_by_feature_id.get(entry.get("feature_id"))
            if info is None:
                raise ValueError(f"Reattach valid geometry for datum {slot} before evaluation.")
            point, direction, _description = self._gdt_extract_datum_geometry(info)
            if point is None or direction is None:
                raise ValueError(f"Reattach valid geometry for datum {slot} before evaluation.")
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
