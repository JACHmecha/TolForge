"""Mixin linking Stack Table dimensions directly to picked STEP features,
so the tolerance range of each dimension can be explored live in the 3D
viewport - as translucent offset geometry, exactly like the existing
single-feature tolerance-offset preview, but driven by the dimensions
already in the stack (including several dimensions sharing one feature,
e.g. a hole's diameter AND its position) and by the stack's own
worst-case/Monte-Carlo results, not just a manual one-off measurement.

Scope, stated explicitly:
- A linked dimension's value always ranges over its own
  [nominal-tol_minus, nominal+tol_plus] - same convention as everywhere
  else in this app.
- Three link modes:
    "diametral"     - grows/shrinks a circular edge/face about its
                       fitted center (the dimension IS the diameter).
    "positional"    - translates a circular edge along its own fitted
                       in-plane axis (u or v) by the dimension's
                       deviation from nominal. Only available for
                       circular edges (needs the u/v basis from
                       _fit_circle) - a real GD&T position tolerance is
                       a 2D zone, but one 1D Stack Table dimension can
                       only drive 1D motion; for true 2D exploration use
                       the GD&T Position tab's pattern features instead.
    "normal_offset" - translates a face or circular edge along its own
                       fitted normal by the dimension's deviation from
                       nominal (same mechanism as the existing
                       show_tolerance_offset in MeasurementMixin, just
                       driven by a stack dimension instead of a manual
                       Tol+/Tol- entry).
- Several dimensions can link to the SAME feature (the hole-diameter +
  hole-position example): their effects are combined into one preview
  per feature, rebuilt from ALL currently-linked dimensions' current
  values every time any one of them changes.
- Worst-case snap uses the same per-dimension direction Stack.worst_case()
  itself uses (derived here via Stack._sign_multiplier rather than by
  reimplementing sign logic) - see _worst_case_dimension_value.
- Monte Carlo snap runs its OWN sampler (mirroring Stack.monte_carlo()'s
  exact sampling convention) rather than modifying Stack.monte_carlo() to
  additionally expose per-dimension arrays - keeps this feature from
  touching the existing, tested Stack class at all.
"""

import numpy as np
from PySide6.QtWidgets import (
    QMessageBox, QInputDialog, QSlider, QWidget, QHBoxLayout, QLabel,
    QTableWidgetItem,
)
from PySide6.QtCore import Qt, QTimer

from tolstack import Stack
from .offset_preview import tolerance_limits, surface_normal, offset_layers, replace_preview, refresh_renderer

LINK_MODES = ("diametral", "positional", "normal_offset")
LINK_LABELS = ("Diameter", "Position", "Surface offset")
SLIDER_STEPS = 1000  # QSlider is integer-only; this is the resolution mapped onto [nominal-tol_minus, nominal+tol_plus]


class StackLinkMixin:
    """Expects the host class (TolstackWindow) to provide, from its own
    __init__: self.table (the Stack Table), self._step_entity_info,
    self._step_preview_renderer, self.step_status_label, plus
    self.stack_link_snap_iterations_input (QSpinBox) built in app.py.
    """

    LINK_ROLE = Qt.UserRole + 100  # QTableWidgetItem data role storing link dicts

    def _stack_link_init_state(self):
        self._stack_link_arm_row = None  # table row currently waiting for a pick
        self._stack_link_pending_mode = None
        self._stack_link_preview_objs = {}  # feature_key -> scene object currently shown for it
        self._stack_preview_timer = QTimer(self)
        self._stack_preview_timer.setSingleShot(True)
        self._stack_preview_timer.setInterval(35)
        self._stack_preview_timer.timeout.connect(self._stack_link_rebuild_preview)

    def _stack_link_schedule_preview(self, *_args):
        if not self._stack_preview_timer.isActive():
            self._stack_preview_timer.start()

    def _stack_link_sync_controls(self, *_args):
        controls = self.stack_offset_controls
        row = self.table.currentRow()
        try:
            item = self.table.item(row, 0)
            link = item.data(self.LINK_ROLE) if item is not None else None
            container = self.table.cellWidget(row, self.STACK_LINK_VALUE_COLUMN)
            if not link or link.get("mode") != "normal_offset" or container is None:
                raise ValueError("Select a row linked in normal_offset mode.")
            nominal = float(self.table.item(row, 1).text())
            controls.configure(
                float(self.table.item(row, 2).text()), float(self.table.item(row, 3).text()),
                self._stack_link_row_current_value(row) - nominal, self.project.units.length,
            )
            controls.reverse.blockSignals(True)
            controls.reverse.setChecked(bool(container.property("reverse_offset")))
            controls.reverse.blockSignals(False)
            controls.title.setText(f"Surface offset · {item.text()}")
            controls.setEnabled(True)
        except (ValueError, AttributeError):
            controls.setEnabled(False)
            controls.title.setText("Surface offset · select a linked row")

    def _stack_offset_controls_changed(self):
        row = self.table.currentRow()
        container = self.table.cellWidget(row, self.STACK_LINK_VALUE_COLUMN)
        if container is None:
            return
        nominal = float(self.table.item(row, 1).text())
        container.setProperty("reverse_offset", self.stack_offset_controls.reverse.isChecked())
        self._stack_link_set_row_value(row, nominal + self.stack_offset_controls.distance.value())
        self._stack_link_schedule_preview()

    # ------------------------------------------------------------------
    # Linking a row to a feature
    # ------------------------------------------------------------------

    def link_selected_row_to_feature(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No row selected", "Select a dimension row in the Stack Table first.")
            return

        mode, ok = QInputDialog.getItem(
            self, "Link mode", "How should this dimension drive the 3D preview?",
            LINK_LABELS, 0, False,
        )
        if not ok:
            return
        mode = LINK_MODES[LINK_LABELS.index(mode)]

        self._stack_link_arm_row = row
        self._stack_link_pending_mode = mode
        self.step_status_label.setText(
            f"Click a face or circular edge in the viewport to link row {row + 1} to it ({mode})."
        )

    def unlink_selected_row(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No row selected", "Select a dimension row in the Stack Table first.")
            return
        self._stack_link_set_row_link(row, None)
        self._stack_link_rebuild_preview()

    def _stack_link_on_pick(self, obj) -> bool:
        """Called from StepViewerMixin._on_step_entity_picked. Returns
        True if this pick was consumed to complete a pending row link."""
        if self._stack_link_arm_row is None:
            return False

        info = self._step_entity_info.get(id(obj)) if obj is not None else None
        if info is None:
            self.step_status_label.setText("No entity under that click - still waiting to link.")
            return True

        mode = self._stack_link_pending_mode
        row = self._stack_link_arm_row
        self._stack_link_arm_row = None
        self._stack_link_pending_mode = None
        self._stack_link_row_to_info(row, mode, info)
        return True

    def _stack_link_row_to_info(self, row: int, mode: str, info: dict) -> bool:
        """Complete a stack-feature link from a direct/contextual selection."""
        if info["type"] not in ("face", "edge"):
            QMessageBox.warning(
                self, "Can't link this",
                "Only faces and edges can be linked to a dimension - a vertex has no "
                "surface/curve to offset."
            )
            return False

        if mode in ("diametral", "positional"):
            self._measure_ensure_circle_fit(info)
            if info.get("circle") is None:
                QMessageBox.warning(
                    self, "Not a circular feature",
                    f"'{mode}' linking needs a circular edge/face (for its center and radius) - "
                    "this entity wasn't recognized as circular. Try 'normal_offset' instead, or "
                    "pick a hole's edge."
                )
                return False

        try:
            feature_id = self._project_register_feature(info)
        except ValueError as exc:
            QMessageBox.warning(self, "Could not register feature", str(exc))
            return True
        link = {"feature_id": feature_id, "mode": mode}
        if hasattr(self, "_update_selection_inspector"):
            self._update_selection_inspector(info)
        self._stack_link_set_row_link(row, link)
        self.step_status_label.setText(
            f"Linked row {row + 1} ({self.table.item(row, 0).text() if self.table.item(row, 0) else '?'}) "
            f"to {info['type']} #{info['index']} ({mode})."
        )
        self._stack_link_rebuild_preview()
        return True

    def context_link_selected_row(self, info: dict, mode: str):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No stack term selected", "Select a row in the Stack workspace first.")
            if hasattr(self, "_show_workspace"):
                self._show_workspace("stack")
            return
        if self._stack_link_row_to_info(row, mode, info) and hasattr(self, "_show_workspace"):
            self._show_workspace("stack")

    def context_add_size_tolerance(self, info: dict):
        self._measure_ensure_circle_fit(info)
        circle = info.get("circle")
        if circle is None:
            QMessageBox.warning(self, "Not circular", "A size tolerance requires circular geometry.")
            return
        name, ok = QInputDialog.getText(
            self, "Add size tolerance", "Dimension name:",
            text=f"Diameter {self.table.rowCount() + 1}",
        )
        if not ok or not name.strip():
            return
        row = self.table.rowCount()
        self._add_table_row(name.strip(), circle["radius"] * 2, 0.0, 0.0, "+", None)
        self._stack_link_row_to_info(row, "diametral", info)
        self.table.setCurrentCell(row, 0)
        if hasattr(self, "_show_workspace"):
            self._show_workspace("stack")

    def _stack_link_set_row_link(self, row: int, link: dict | None):
        """Stores link data on the row's Name cell (travels naturally
        with the row if it's reordered/removed - no separate row-index-
        keyed structure to keep in sync) and installs/removes that row's
        slider widget in the Value column."""
        name_item = self.table.item(row, 0)
        if name_item is None:
            # Defensive: every row should already have a Name item by the
            # time it can be linked, but don't crash if one's missing.
            name_item = QTableWidgetItem("")
            self.table.setItem(row, 0, name_item)
        name_item.setData(self.LINK_ROLE, link)

        if link is None:
            self.table.removeCellWidget(row, self.STACK_LINK_VALUE_COLUMN)
            return

        self._stack_link_install_slider(row)

    def _stack_link_install_slider(self, row: int):
        self.table.setColumnWidth(self.STACK_LINK_VALUE_COLUMN,
                                  max(210, self.table.columnWidth(self.STACK_LINK_VALUE_COLUMN)))
        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, SLIDER_STEPS)

        value_label = QLabel("nominal")
        value_label.setMinimumWidth(60)
        value_label.setStyleSheet("font-size: 10px;")

        container = QWidget()
        container.setProperty("preview_value", float(self.table.item(row, 1).text()))
        layout = QHBoxLayout(container)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.addWidget(slider, stretch=1)
        layout.addWidget(value_label)

        # Resolve the item's current row so deleting an earlier row doesn't
        # leave this slider editing the wrong feature.
        item = self.table.item(row, 0)
        slider.valueChanged.connect(lambda _val, item=item, lbl=value_label: self._stack_link_slider_value_changed(self.table.row(item), lbl))

        self.table.setCellWidget(row, self.STACK_LINK_VALUE_COLUMN, container)
        self._stack_link_set_row_value(row, float(self.table.item(row, 1).text()))

    def _stack_link_slider_value_changed(self, row: int, value_label: QLabel):
        try:
            container = self.table.cellWidget(row, self.STACK_LINK_VALUE_COLUMN)
            container.setProperty("preview_value", None)
            value = self._stack_link_row_current_value(row)
        except (ValueError, AttributeError):
            value_label.setText("?")
            return
        value_label.setText(f"{value:.4f}")
        self._stack_link_sync_controls()
        self._stack_link_schedule_preview()

    def _stack_link_row_current_value(self, row: int) -> float:
        """The dimension's value implied by its slider's current
        position, mapped onto [nominal-tol_minus, nominal+tol_plus]."""
        nominal = float(self.table.item(row, 1).text())
        tol_plus = float(self.table.item(row, 2).text())
        tol_minus = float(self.table.item(row, 3).text())
        tolerance_limits(tol_plus, tol_minus)
        if not np.isfinite(nominal):
            raise ValueError("Nominal must be finite.")
        container = self.table.cellWidget(row, self.STACK_LINK_VALUE_COLUMN)
        if container is None:
            return nominal
        precise_value = container.property("preview_value")
        if precise_value is not None:
            return min(max(float(precise_value), nominal - tol_minus), nominal + tol_plus)
        slider = container.findChild(QSlider)
        if slider is None:
            return nominal
        fraction = slider.value() / SLIDER_STEPS
        return (nominal - tol_minus) + fraction * (tol_plus + tol_minus)

    def _stack_link_set_row_value(self, row: int, value: float):
        """Moves a linked row's slider to represent `value` (clamped into
        its [nominal-tol_minus, nominal+tol_plus] range) without
        triggering a preview rebuild per-row - callers rebuild once after
        setting every row they need to."""
        nominal = float(self.table.item(row, 1).text())
        tol_plus = float(self.table.item(row, 2).text())
        tol_minus = float(self.table.item(row, 3).text())
        tolerance_limits(tol_plus, tol_minus)
        if not np.isfinite([nominal, value]).all():
            raise ValueError("Nominal and preview value must be finite.")
        span = tol_plus + tol_minus
        fraction = 0.5 if span <= 0 else (value - (nominal - tol_minus)) / span
        fraction = min(max(fraction, 0.0), 1.0)

        container = self.table.cellWidget(row, self.STACK_LINK_VALUE_COLUMN)
        if container is None:
            return
        value = min(max(value, nominal - tol_minus), nominal + tol_plus)
        container.setProperty("preview_value", value)
        slider = container.findChild(QSlider)
        if slider is None:
            return
        slider.blockSignals(True)
        slider.setValue(round(fraction * SLIDER_STEPS))
        slider.blockSignals(False)
        value_label = container.findChild(QLabel)
        if value_label is not None:
            value_label.setText(f"{value:.4f}")

    # ------------------------------------------------------------------
    # Reading links + rebuilding the combined preview
    # ------------------------------------------------------------------

    def _stack_link_read_all(self) -> list:
        """Returns a list of (row, link_dict, current_value, nominal)."""
        entries = []
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            if name_item is None:
                continue
            link = name_item.data(self.LINK_ROLE)
            if not link:
                continue
            try:
                nominal = float(self.table.item(row, 1).text())
                value = self._stack_link_row_current_value(row)
            except (AttributeError, ValueError):
                continue
            entries.append((row, link, value, nominal))
        return entries

    @staticmethod
    def _stack_link_feature_key(link: dict):
        if link.get("feature_id"):
            return link["feature_id"]
        return (link.get("solid_index"), link.get("entity_type"), link.get("entity_index"))

    def _stack_link_find_entity_info(self, link: dict) -> dict | None:
        if link.get("feature_id") and hasattr(self, "_project_find_entity_info"):
            return self._project_find_entity_info(link["feature_id"])
        target = self._stack_link_feature_key(link)
        for entry in self._step_entity_info.values():
            if entry["type"] != link["entity_type"] or entry["index"] != link["entity_index"]:
                continue
            if entry.get("solid_index") != link.get("solid_index"):
                continue
            return entry
        return None

    def reset_stack_links_to_nominal(self):
        for row, link, _value, nominal in self._stack_link_read_all():
            self._stack_link_set_row_value(row, nominal)
        self._stack_link_rebuild_preview()

    def _stack_link_rebuild_preview(self):
        self._stack_preview_timer.stop()
        self._stack_link_sync_controls()
        if self._step_preview_renderer is None:
            return
        entries = self._stack_link_read_all()
        valid_rows = {row for row, *_ in entries}
        invalid_keys = set()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            link = item.data(self.LINK_ROLE) if item is not None else None
            if link and row not in valid_rows:
                invalid_keys.add(self._stack_link_feature_key(link))
        if invalid_keys:
            self.step_status_label.setText("Offset preview paused for features with invalid nominal or tolerance values.")

        # Group by which underlying feature each link affects, so several
        # dimensions on one hole (diameter + position) combine into a
        # single preview instead of overwriting each other.
        groups = {}
        for row, link, value, nominal in entries:
            self._stack_link_set_row_value(row, value)
            info = self._stack_link_find_entity_info(link)
            if info is None:
                continue
            key = self._stack_link_feature_key(link)
            if key in invalid_keys:
                continue
            group = groups.setdefault(key, {"info": info, "deltas": [], "lower": 0.0, "upper": 0.0, "has_offset": False})
            direction = 1
            if link["mode"] == "normal_offset":
                container = self.table.cellWidget(row, self.STACK_LINK_VALUE_COLUMN)
                direction = -1 if container is not None and container.property("reverse_offset") else 1
                lower, upper = tolerance_limits(float(self.table.item(row, 2).text()), float(self.table.item(row, 3).text()))
                group["lower"] += min(lower * direction, upper * direction)
                group["upper"] += max(lower * direction, upper * direction)
                group["has_offset"] = True
            group["deltas"].append((link["mode"], (value - nominal) * direction))

        # Clear previews for any feature that no longer has a link (row
        # unlinked, or removed).
        for key in list(self._stack_link_preview_objs.keys()):
            if key not in groups:
                self._stack_link_remove_preview(key)

        for key, group in groups.items():
            try:
                bounds = (group["lower"], group["upper"]) if group["has_offset"] else None
                self._stack_link_build_feature_preview(key, group["info"], group["deltas"], bounds)
            except (ValueError, TypeError) as exc:
                self._stack_link_remove_preview(key)
                self.step_status_label.setText(f"Surface offset: {exc}")

    def _stack_link_build_feature_preview(self, key: tuple, info: dict, deltas: list, bounds=None):
        circle = info.get("circle")
        translation = np.zeros(3)
        radius_delta = 0.0

        for mode, delta in deltas:
            if mode == "diametral":
                radius_delta += delta / 2.0  # dimension is a DIAMETER; radius moves half as much
            elif mode == "positional" and circle is not None:
                translation = translation + circle["u_axis"] * delta
            elif mode == "normal_offset":
                # All normal motion and its limits are applied by the shared
                # nominal-relative surface path after diameter/position changes.
                pass

        base_points = np.asarray(info["points"], dtype=float)
        if radius_delta != 0.0 and circle is not None:
            center, u_axis, v_axis = circle["center"], circle["u_axis"], circle["v_axis"]
            centered = base_points - center
            u_coord = centered @ u_axis
            v_coord = centered @ v_axis
            radial = np.hypot(u_coord, v_coord)
            radial_safe = np.where(radial == 0, 1.0, radial)  # avoid /0 for a point exactly at center
            scale = (radial + radius_delta) / radial_safe
            new_u = u_coord * scale
            new_v = v_coord * scale
            out_of_plane = centered - np.outer(u_coord, u_axis) - np.outer(v_coord, v_axis)
            new_points = center + np.outer(new_u, u_axis) + np.outer(new_v, v_axis) + out_of_plane
        else:
            new_points = base_points

        new_points = new_points + translation

        try:
            if bounds is not None:
                preview_info = dict(info, points=new_points)
                normal = surface_normal(info)
                current = sum(delta for mode, delta in deltas if mode == "normal_offset")
                layers = offset_layers(preview_info, current, *bounds, normal,
                                       self.stack_offset_controls.limits.isChecked())
            else:
                layers = [("Current offset", new_points, "#FFAE5C", False)]
            self._stack_link_preview_objs[key] = replace_preview(
                self._step_preview_renderer, self._stack_link_preview_objs.get(key, []), info, layers,
            )
        except Exception as exc:
            self._stack_link_remove_preview(key)
            self.step_status_label.setText(f"Could not build the stack-link preview: {exc}")

    def _stack_link_remove_preview(self, key: tuple):
        objects = self._stack_link_preview_objs.pop(key, [])
        if objects and self._step_preview_renderer is not None:
            for obj in objects:
                self._step_preview_renderer.scene.remove(obj)
            refresh_renderer(self._step_preview_renderer)

    # ------------------------------------------------------------------
    # Snap to worst-case / Monte Carlo extreme
    # ------------------------------------------------------------------

    @staticmethod
    def _worst_case_dimension_value(dimension, extreme: str) -> float:
        """The value a single dimension takes at the stack's own
        worst-case upper/lower extreme - same sign convention
        Stack.worst_case() itself uses (derived here rather than
        reimplemented ad hoc): a sign=+1 dimension pushes the upper
        extreme by +tol_plus and the lower extreme by -tol_minus; a
        sign=-1 dimension does the opposite, since its contribution to
        the total is negated.
        """
        sign = Stack._sign_multiplier(dimension.sign)
        if extreme == "upper":
            return dimension.nominal + dimension.tol_plus if sign > 0 else dimension.nominal - dimension.tol_minus
        return dimension.nominal - dimension.tol_minus if sign > 0 else dimension.nominal + dimension.tol_plus

    def snap_to_worst_case_upper(self):
        self._snap_to_worst_case("upper")

    def snap_to_worst_case_lower(self):
        self._snap_to_worst_case("lower")

    def _snap_to_worst_case(self, extreme: str):
        try:
            stack = self._build_stack()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid data", str(exc))
            return

        by_name = {d.name: d for d in stack.dimensions}
        for row, link, _value, _nominal in self._stack_link_read_all():
            name_item = self.table.item(row, 0)
            name = name_item.text().strip() if name_item else None
            dimension = by_name.get(name)
            if dimension is None:
                continue
            target = self._worst_case_dimension_value(dimension, extreme)
            self._stack_link_set_row_value(row, target)

        self._stack_link_rebuild_preview()
        result = stack.worst_case()
        self.step_status_label.setText(
            f"Snapped linked dimensions to worst-case {extreme} "
            f"(stack total: {result.upper_limit if extreme == 'upper' else result.lower_limit:.4f})."
        )

    def snap_to_monte_carlo_max(self):
        self._snap_to_monte_carlo_extreme("max")

    def snap_to_monte_carlo_min(self):
        self._snap_to_monte_carlo_extreme("min")

    def _snap_to_monte_carlo_extreme(self, extreme: str):
        try:
            stack = self._build_stack()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid data", str(exc))
            return
        if not stack.dimensions:
            QMessageBox.warning(self, "No data", "Add at least one dimension.")
            return

        iterations = self.stack_link_snap_iterations_input.value()
        default_cpk_text = self.default_cpk_input.text().strip() if hasattr(self, "default_cpk_input") else ""
        default_cpk = float(default_cpk_text) if default_cpk_text else None

        names, raw_values, totals = self._sample_stack_per_dimension(stack, iterations, default_cpk)
        idx = int(np.argmax(totals)) if extreme == "max" else int(np.argmin(totals))
        sample_values = {name: raw_values[i, idx] for i, name in enumerate(names)}

        for row, link, _value, _nominal in self._stack_link_read_all():
            name_item = self.table.item(row, 0)
            name = name_item.text().strip() if name_item else None
            if name in sample_values:
                self._stack_link_set_row_value(row, sample_values[name])

        self._stack_link_rebuild_preview()
        self.step_status_label.setText(
            f"Snapped linked dimensions to the Monte Carlo sample with the {extreme} total "
            f"({totals[idx]:.4f}, out of {iterations} samples)."
        )

    @staticmethod
    def _sample_stack_per_dimension(stack: Stack, iterations: int, default_cpk: float | None):
        """Mirrors Stack.monte_carlo()'s exact sampling convention
        (uniform when no Cpk, Cpk-calibrated split-normal otherwise) but
        additionally keeps the per-dimension raw sampled values (not just
        their signed sum), so a specific interesting iteration's
        per-dimension values can be read back out - Stack.monte_carlo()
        itself only returns the aggregate, deliberately not modified here
        to add that (see module docstring)."""
        names = [d.name for d in stack.dimensions]
        raw_values = np.zeros((len(stack.dimensions), iterations))
        signed_values = np.zeros((len(stack.dimensions), iterations))

        for i, d in enumerate(stack.dimensions):
            cpk = d.cpk if d.cpk is not None else default_cpk
            if cpk is None:
                values = np.random.uniform(d.nominal - d.tol_minus, d.nominal + d.tol_plus, iterations)
            else:
                if cpk <= 0:
                    raise ValueError(f"Cpk for '{d.name}' must be > 0, not {cpk}.")
                sigma_plus, sigma_minus = d.tol_plus / (3 * cpk), d.tol_minus / (3 * cpk)
                z = np.random.standard_normal(iterations)
                values = d.nominal + np.where(z >= 0, z * sigma_plus, z * sigma_minus)
            raw_values[i] = values
            signed_values[i] = Stack._sign_multiplier(d.sign) * values

        totals = signed_values.sum(axis=0)
        return names, raw_values, totals
