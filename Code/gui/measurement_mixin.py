"""Mixin providing distance & angle measurement between two picked STEP
entities (face/edge/vertex), a translucent tolerance-offset preview to
visually flag clearance vs. interference, and "add to dimension bank"
support for whatever gets measured.

All measurements are computed directly from the same tessellated point
data already used to render each entity (mesh vertices for faces,
polyline points for edges, the single point for vertices) rather than by
calling into OCCT's own distance/analysis API. That keeps this mixin
independent of the exact compas_occ/pythonocc-core version installed, at
the cost of being a tessellation-resolution-limited approximation rather
than an exact analytic result. For engineering fit-up checks (as opposed
to metrology-grade output) this is normally more than accurate enough,
but the numbers are only as good as the STEP tessellation density -
coarsely tessellated curved faces will give noisier normals/angles.

Method:
- Min/max distance: brute-force point-to-point distance between the two
  entities' sampled points.
- Face "normal" / edge "direction": a best-fit plane (face) or best-fit
  line (edge) through the sampled points via SVD. This handles
  near-planar faces and straight/gently-curved edges well; it will be
  misleading on strongly curved geometry (e.g. a full cylindrical face),
  where "normal distance" and "angle" are less meaningful - the angle
  and normal-distance fields are still shown in that case since there's
  no reliable way to detect it up front, but treat them with suspicion
  if either entity is obviously curved.
- Normal distance: the min-distance vector, projected onto whichever
  entity has a face (preferring A's, falling back to B's), oriented so
  a positive value means "gap" and a negative value means "overlap /
  interference". This is the number offered to the dimension bank.
- Angle: angle between the two entities' fitted normal/direction
  vectors, folded into 0-90 degrees since SVD doesn't return a signed
  direction.
"""

import numpy as np

from PySide6.QtCore import QPoint
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMessageBox, QInputDialog, QMenu, QWidget

from compas.colors import Color

from tolstack import DimensionTemplate


class MeasurementMixin:
    """Expects the host class (TolstackWindow) to provide, from its own
    __init__: self._step_entity_info, self._step_preview_renderer,
    self.step_status_label, self.bank, self._refresh_bank_combo (from
    DimensionBankMixin), and the Measure-tab widgets built in app.py:
    self.measure_slot_a_label, self.measure_slot_b_label,
    self.measure_result_labels (dict with keys "min", "max", "normal",
    "xyz", "angle"), self.measure_tol_plus_input, self.measure_tol_minus_input.
    """

    # ------------------------------------------------------------------
    # Setup / slot management
    # ------------------------------------------------------------------

    def _measure_init_state(self):
        self._measure_slot = {"A": None, "B": None}
        self._measure_arm = None  # "A" or "B" while waiting for the next pick
        self._measure_offset_obj = None  # the translucent preview object, if any
        self._measure_last = None  # dict of the most recent computed measurement

    def measure_arm_slot_a(self):
        self._measure_arm_slot("A")

    def measure_arm_slot_b(self):
        self._measure_arm_slot("B")

    def _measure_arm_slot(self, slot: str):
        self._measure_arm = slot
        self.step_status_label.setText(
            f"Click a face, edge, or vertex in the viewport to set it as point {slot}."
        )

    def measure_clear_slot_a(self):
        self._measure_clear_slot("A")

    def measure_clear_slot_b(self):
        self._measure_clear_slot("B")

    def _measure_clear_slot(self, slot: str):
        self._measure_slot[slot] = None
        self._measure_update_slot_labels()
        self._measure_clear_results()

    def _measure_assign_slot(self, slot: str, info: dict | None):
        if info is None:
            self._measure_slot[slot] = None
            self._measure_update_slot_labels()
            self._measure_clear_results()
            return

        self._measure_slot[slot] = info
        self._measure_ensure_circle_fit(info)
        self._measure_update_slot_labels()

        if self._measure_slot["A"] is not None and self._measure_slot["B"] is not None:
            self._measure_compute()
        else:
            self.step_status_label.setText(
                f"Point {slot} set: {info['type'].capitalize()} #{info['index']}"
            )

    def _build_measure_context_menu(self, info: dict | None):
        menu = QMenu("Measurement", self if isinstance(self, QWidget) else None)

        for slot, label in (("A", "Set as Measure A"), ("B", "Set as Measure B")):
            action = QAction(label, menu)
            action.setEnabled(info is not None)
            action.triggered.connect(lambda checked=False, slot=slot, info=info: self._measure_assign_slot(slot, info))
            menu.addAction(action)

        menu.addSeparator()
        bank_action = QAction("Add measurement to Dimension Bank", menu)
        bank_action.setEnabled(
            info is not None
            and self._measure_slot["A"] is not None
            and self._measure_slot["B"] is not None
            and self._measure_last is not None
        )
        bank_action.triggered.connect(self._add_context_menu_measurement_to_bank)
        menu.addAction(bank_action)
        return menu

    def _add_context_menu_measurement_to_bank(self):
        if self._measure_slot["A"] is not None and self._measure_slot["B"] is not None:
            self._measure_compute()
        self.add_measurement_to_bank()

    def _show_measure_context_menu(self, info: dict | None, pos):
        menu = self._build_measure_context_menu(info)
        if self._step_preview_renderer is not None:
            if isinstance(pos, tuple):
                pos = QPoint(*pos)
            menu.exec(self._step_preview_renderer.mapToGlobal(pos))
        else:
            menu.exec()

    def _measure_on_pick(self, obj) -> bool:
        """Called from StepViewerMixin._on_step_entity_picked for every
        pick. Returns True if this pick was consumed for measurement
        (i.e. a slot was armed), False if the normal single-selection
        status text should be shown instead."""
        if self._measure_arm is None:
            return False

        info = self._step_entity_info.get(id(obj)) if obj is not None else None
        if info is None:
            # Clicked empty space while armed - leave the slot armed and
            # say so, rather than silently discarding the pending arm.
            self.step_status_label.setText(
                f"No entity under that click - still waiting for point {self._measure_arm}."
            )
            return True

        slot = self._measure_arm
        self._measure_arm = None
        self._measure_assign_slot(slot, info)
        return True

    def _measure_update_slot_labels(self):
        for slot, label_widget in (
            ("A", self.measure_slot_a_label), ("B", self.measure_slot_b_label)
        ):
            info = self._measure_slot[slot]
            if info is None:
                label_widget.setText(f"{slot}: (none)")
            else:
                text = f"{slot}: {info['type'].capitalize()} #{info['index']}"
                circle = info.get("circle")
                if circle is not None:
                    text += f"  (\u2300{circle['radius'] * 2:.4f})"
                label_widget.setText(text)

    def _measure_clear_results(self):
        for lbl in self.measure_result_labels.values():
            lbl.setText("-")
        self._measure_last = None
        self._measure_clear_offset_preview()

    # ------------------------------------------------------------------
    # Geometry math
    # ------------------------------------------------------------------

    @staticmethod
    def _fit_normal_or_direction(points: np.ndarray, kind: str):
        """Best-fit plane normal (face) or best-fit line direction (edge)
        through a point cloud, via SVD. Returns (centroid, unit_vector) or
        (centroid, None) when no normal/direction is meaningful (vertex,
        or a degenerate/single-point cloud)."""
        centroid = points.mean(axis=0)
        if kind == "vertex" or len(points) < 2:
            return centroid, None

        centered = points - centroid
        try:
            _u, _s, vt = np.linalg.svd(centered, full_matrices=False)
        except np.linalg.LinAlgError:
            return centroid, None

        # Smallest singular vector = normal to the best-fit plane (face).
        # Largest singular vector = principal direction along the point
        # cloud (edge).
        vector = vt[-1] if kind == "face" else vt[0]
        norm = np.linalg.norm(vector)
        if norm == 0:
            return centroid, None
        return centroid, vector / norm

    def _measure_ensure_circle_fit(self, info: dict):
        """Lazily fits and caches a circle on this entity (stored on the
        same dict that lives in self._step_entity_info, so re-picking the
        same face/edge later - even into a different slot - reuses the
        fit instead of recomputing it).

        Doesn't try to guess up front whether the entity actually IS a
        circular feature (a straight edge, for instance, will still get
        "fit" to some circle) - the rms_residual field in the result is
        the honest signal for that; a large residual relative to the
        radius means the shape doesn't look like a circle, but that's
        left for the caller/UI to flag rather than silently refusing.

        Only fits face/edge entities - a whole-solid selection (from the
        toolbar's "Solids" pick filter) aggregates points spanning the
        entire 3D body, not a single roughly-planar feature, so a "circle
        fit" on that data would just be numeric noise rather than a
        meaningful failure signal via rms_residual; better to refuse it
        outright than let a nonsense fit through.
        """
        if "circle" in info:
            return
        if info["type"] not in ("face", "edge") or len(info["points"]) < 3:
            info["circle"] = None
            return
        info["circle"] = self._fit_circle(np.asarray(info["points"], dtype=float))

    @staticmethod
    def _fit_circle(points: np.ndarray):
        """Fits a circle to a (roughly) planar point cloud: best-fit
        plane via SVD, then an algebraic least-squares circle fit
        (Kasa's method) within that plane.

        Deliberately doesn't reuse _fit_normal_or_direction: that method
        uses the LARGEST singular vector as an edge's "direction", which
        is right for a straight edge but wrong here - a circular loop of
        points is close to isotropic in-plane (similar spread in both
        in-plane directions) with most of its remaining variance out of
        plane, so - like a face - the correct normal is the SMALLEST
        singular vector, regardless of whether the entity happens to be
        labeled "face" or "edge".

        Returns a dict with "center" (3D point), "radius", "normal", and
        "rms_residual" (root-mean-square of each point's radial error
        against the fitted circle, in the same units as the geometry -
        large relative to the radius is a sign this wasn't actually a
        circular feature). Returns None if the fit is degenerate (e.g.
        all points collinear).
        """
        centroid = points.mean(axis=0)
        centered = points - centroid
        try:
            _u, _s, vt = np.linalg.svd(centered, full_matrices=False)
        except np.linalg.LinAlgError:
            return None

        normal = vt[-1]
        u_axis, v_axis = vt[0], vt[1]

        local = centered @ np.column_stack([u_axis, v_axis])  # (N, 2) in-plane coords

        # Algebraic (Kasa) circle fit: x^2 + y^2 = D*x + E*y + F, solved
        # as a plain linear least squares for (D, E, F).
        design = np.column_stack([local[:, 0], local[:, 1], np.ones(len(local))])
        rhs = local[:, 0] ** 2 + local[:, 1] ** 2
        try:
            solution, *_ = np.linalg.lstsq(design, rhs, rcond=None)
        except np.linalg.LinAlgError:
            return None
        d_coef, e_coef, f_coef = solution
        center_local = np.array([d_coef / 2, e_coef / 2])
        radius_sq = f_coef + center_local[0] ** 2 + center_local[1] ** 2
        if radius_sq <= 0:
            return None
        radius = float(np.sqrt(radius_sq))

        center_3d = centroid + center_local[0] * u_axis + center_local[1] * v_axis
        residuals = np.linalg.norm(local - center_local, axis=1) - radius
        rms_residual = float(np.sqrt(np.mean(residuals**2)))

        return {
            "center": center_3d, "radius": radius, "normal": normal, "rms_residual": rms_residual,
        }

    def _measure_compute(self):
        info_a, info_b = self._measure_slot["A"], self._measure_slot["B"]
        pts_a = np.asarray(info_a["points"], dtype=float)
        pts_b = np.asarray(info_b["points"], dtype=float)

        # Brute-force point-to-point distance matrix. Fine for typical
        # per-face/per-edge tessellation counts; could get slow on very
        # dense meshes, but there's no dependency here beyond numpy.
        dist_matrix = np.linalg.norm(pts_a[:, None, :] - pts_b[None, :, :], axis=-1)
        min_idx = np.unravel_index(np.argmin(dist_matrix), dist_matrix.shape)
        min_distance = float(dist_matrix[min_idx])
        max_distance = float(dist_matrix.max())
        closest_a, closest_b = pts_a[min_idx[0]], pts_b[min_idx[1]]
        delta = closest_b - closest_a  # vector from A's nearest point to B's

        centroid_a, normal_a = self._fit_normal_or_direction(pts_a, info_a["type"])
        centroid_b, normal_b = self._fit_normal_or_direction(pts_b, info_b["type"])

        # Prefer A's normal (if A is a face) as the projection axis for
        # "normal distance"; fall back to B's. Only meaningful if at
        # least one of the two is a face (or a well-fit edge direction).
        reference_normal = None
        reference_is_face = False
        if info_a["type"] == "face" and normal_a is not None:
            reference_normal, reference_is_face = normal_a, True
        elif info_b["type"] == "face" and normal_b is not None:
            reference_normal, reference_is_face = normal_b, True
        elif normal_a is not None:
            reference_normal = normal_a
        elif normal_b is not None:
            reference_normal = normal_b

        normal_distance = None
        if reference_normal is not None:
            # Orient the reference normal to point from A's centroid
            # toward B's centroid, so a positive normal_distance always
            # means "gap" and negative means "overlap/interference",
            # regardless of which way the fitted normal happened to face.
            if np.dot(centroid_b - centroid_a, reference_normal) < 0:
                reference_normal = -reference_normal
            normal_distance = float(np.dot(delta, reference_normal))

        angle_deg = None
        if normal_a is not None and normal_b is not None:
            cos_angle = np.clip(abs(np.dot(normal_a, normal_b)), -1.0, 1.0)
            angle_deg = float(np.degrees(np.arccos(cos_angle)))

        circle_a, circle_b = info_a.get("circle"), info_b.get("circle")
        circle_center_distance = None
        if circle_a is not None and circle_b is not None:
            # Radial offset between the two fitted circle centers,
            # projected into the plane perpendicular to their (shared)
            # axis - this is the number that matters for e.g. a hole in
            # one part vs. a hole in another part stacked along the same
            # axis (LED hole vs. sticker hole): any separation ALONG the
            # axis is just the gap between the parts and irrelevant to
            # how well the two apertures line up.
            axis_a, axis_b = circle_a["normal"], circle_b["normal"]
            if np.dot(axis_a, axis_b) < 0:
                axis_b = -axis_b
            axis = axis_a + axis_b
            axis_norm = np.linalg.norm(axis)
            axis = axis / axis_norm if axis_norm > 0 else axis_a
            delta_c = circle_b["center"] - circle_a["center"]
            radial_vec = delta_c - axis * np.dot(delta_c, axis)
            circle_center_distance = float(np.linalg.norm(radial_vec))

        self._measure_last = {
            "min_distance": min_distance,
            "max_distance": max_distance,
            "delta": delta,
            "normal_distance": normal_distance,
            "reference_normal": reference_normal,
            "reference_is_face": reference_is_face,
            "angle_deg": angle_deg,
            "circle_a": circle_a,
            "circle_b": circle_b,
            "circle_center_distance": circle_center_distance,
        }
        self._measure_display_results()

    def _measure_display_results(self):
        m = self._measure_last
        labels = self.measure_result_labels
        labels["min"].setText(f"{m['min_distance']:.4f} mm")
        labels["max"].setText(f"{m['max_distance']:.4f} mm")
        labels["normal"].setText(
            f"{m['normal_distance']:.4f} mm" if m["normal_distance"] is not None
            else "N/A (need a face in A or B)"
        )
        dx, dy, dz = m["delta"]
        labels["xyz"].setText(f"\u0394X {dx:.4f}  \u0394Y {dy:.4f}  \u0394Z {dz:.4f}")
        labels["angle"].setText(
            f"{m['angle_deg']:.3f}\u00b0" if m["angle_deg"] is not None
            else "N/A (need two faces/edges)"
        )
        labels["radius_a"].setText(
            f"\u2205{m['circle_a']['radius']*2:.4f}  (fit residual {m['circle_a']['rms_residual']:.4f})"
            if m["circle_a"] is not None else "N/A (A not recognized as circular)"
        )
        labels["radius_b"].setText(
            f"\u2205{m['circle_b']['radius']*2:.4f}  (fit residual {m['circle_b']['rms_residual']:.4f})"
            if m["circle_b"] is not None else "N/A (B not recognized as circular)"
        )
        labels["circle_center"].setText(
            f"{m['circle_center_distance']:.4f} mm" if m["circle_center_distance"] is not None
            else "N/A (need a circle fit on both A and B)"
        )
        self.step_status_label.setText(
            "Measured "
            f"{self._measure_slot['A']['type'].capitalize()} #{self._measure_slot['A']['index']} "
            "to "
            f"{self._measure_slot['B']['type'].capitalize()} #{self._measure_slot['B']['index']}."
        )

    # ------------------------------------------------------------------
    # Tolerance offset preview
    # ------------------------------------------------------------------

    def show_tolerance_offset(self):
        """Offset whichever selected entity is a face along the measured
        (oriented) normal by (nominal - tol_minus) - the worst-case
        closest approach - and show it as a translucent surface: green
        if that worst case still clears the other entity, red if it
        would interfere.
        """
        if self._measure_last is None or self._measure_last["reference_normal"] is None:
            QMessageBox.warning(
                self, "No measurement",
                "Measure two entities (at least one a face) first."
            )
            return

        face_info = None
        for slot in ("A", "B"):
            info = self._measure_slot[slot]
            if info is not None and info["type"] == "face":
                face_info = info
                break
        if face_info is None or face_info.get("mesh") is None:
            QMessageBox.warning(
                self, "No face selected",
                "The tolerance offset preview requires a face (not just an edge/vertex) in A or B."
            )
            return

        try:
            tol_plus = float(self.measure_tol_plus_input.text() or 0.0)
            tol_minus = float(self.measure_tol_minus_input.text() or 0.0)
        except ValueError:
            QMessageBox.warning(self, "Invalid tolerance", "Tol + / Tol - must be numbers.")
            return

        nominal = self._measure_last["normal_distance"]
        worst_case = nominal - tol_minus
        best_case = nominal + tol_plus
        normal = self._measure_last["reference_normal"]

        # reference_normal already points from A's centroid toward B's
        # (set in _measure_compute), so translating the face along it by
        # worst_case consistently moves it *towards* the other entity
        # regardless of which slot (A or B) actually holds the face.
        offset_vector = normal * worst_case

        self._measure_clear_offset_preview()

        try:
            source_mesh = face_info["mesh"]
            offset_mesh = source_mesh.copy()
            base_points = np.asarray(face_info["points"], dtype=float)
            new_points = base_points + offset_vector
            for vkey, new_xyz in zip(offset_mesh.vertices(), new_points):
                offset_mesh.vertex_attributes(vkey, "xyz", new_xyz.tolist())

            color = Color.from_hex("#4caf50") if worst_case > 0 else Color.from_hex("#f44336")
            scene = self._step_preview_renderer.scene
            try:
                obj = scene.add(
                    offset_mesh, show_faces=True, show_lines=False,
                    facecolor=color, opacity=0.35,
                )
            except TypeError:
                # Older compas_viewer without an `opacity` kwarg - still
                # show the offset, just opaque rather than translucent.
                obj = scene.add(offset_mesh, show_faces=True, show_lines=False, facecolor=color)
            self._measure_offset_obj = obj

            self._step_preview_renderer.makeCurrent()
            self._step_preview_renderer.rebuild_buffers()
            self._step_preview_renderer.doneCurrent()
            self._step_preview_renderer.update()

            verdict = "CLEARANCE" if worst_case > 0 else "INTERFERENCE"
            self.step_status_label.setText(
                f"Tolerance offset preview: nominal {nominal:.4f} mm, "
                f"worst-case {worst_case:.4f} mm, best-case {best_case:.4f} mm -> {verdict}"
            )
        except Exception as exc:  # pragma: no cover - runtime environment specific
            QMessageBox.warning(self, "Could not build offset preview", str(exc))

    def clear_tolerance_offset(self):
        self._measure_clear_offset_preview()

    def _measure_clear_offset_preview(self):
        if self._measure_offset_obj is not None and self._step_preview_renderer is not None:
            try:
                self._step_preview_renderer.scene.remove(self._measure_offset_obj)
                self._step_preview_renderer.makeCurrent()
                self._step_preview_renderer.rebuild_buffers()
                self._step_preview_renderer.doneCurrent()
                self._step_preview_renderer.update()
            except Exception:
                pass
            self._measure_offset_obj = None

    # ------------------------------------------------------------------
    # Add to dimension bank
    # ------------------------------------------------------------------

    def add_measurement_to_bank(self):
        if self._measure_last is None:
            QMessageBox.warning(self, "No measurement", "Measure two entities first.")
            return

        if self._measure_last.get("circle_center_distance") is not None:
            nominal = self._measure_last["circle_center_distance"]
            suffix = " (circle center offset)"
        elif self._measure_last["normal_distance"] is not None:
            nominal = self._measure_last["normal_distance"]
            suffix = ""
        elif self._measure_last["angle_deg"] is not None:
            nominal = self._measure_last["angle_deg"]
            suffix = " (deg)"
        else:
            nominal = self._measure_last["min_distance"]
            suffix = " (min dist.)"

        info_a, info_b = self._measure_slot["A"], self._measure_slot["B"]
        default_name = (
            f"{info_a['type'].capitalize()}{info_a['index']}-"
            f"{info_b['type'].capitalize()}{info_b['index']}{suffix}"
        )
        name, ok = QInputDialog.getText(self, "Add to dimension bank", "Name:", text=default_name)
        if not ok or not name.strip():
            return
        name = name.strip()

        try:
            tol_plus = float(self.measure_tol_plus_input.text() or 0.0)
            tol_minus = float(self.measure_tol_minus_input.text() or 0.0)
        except ValueError:
            QMessageBox.warning(self, "Invalid tolerance", "Tol + / Tol - must be numbers.")
            return

        template = DimensionTemplate(
            name=name, nominal=nominal, tol_plus=tol_plus, tol_minus=tol_minus, cpk=None
        )

        if name in self.bank.names():
            choice = QMessageBox.question(
                self, "Overwrite entry",
                f"'{name}' already exists in the bank. Overwrite it?"
            )
            if choice != QMessageBox.Yes:
                return
            self.bank.add(template, overwrite=True)
        else:
            self.bank.add(template)

        self._refresh_bank_combo()
        QMessageBox.information(
            self, "Added",
            f"'{name}' added to the dimension bank ({nominal:.4f}{suffix or ' mm'})."
        )

    def add_circle_diameter_a_to_bank(self):
        self._add_circle_diameter_to_bank("A")

    def add_circle_diameter_b_to_bank(self):
        self._add_circle_diameter_to_bank("B")

    def _add_circle_diameter_to_bank(self, slot: str):
        """Banks a single fitted circle's diameter on its own - for a
        hole's diameter and its manufacturing tolerance, independent of
        any second entity/feature."""
        info = self._measure_slot.get(slot)
        if info is None or info.get("circle") is None:
            QMessageBox.warning(
                self, "No circle fit",
                f"Point {slot} isn't set, or wasn't recognized as a circular feature."
            )
            return

        diameter = info["circle"]["radius"] * 2
        default_name = f"{info['type'].capitalize()}{info['index']}_diameter"
        name, ok = QInputDialog.getText(self, "Add to dimension bank", "Name:", text=default_name)
        if not ok or not name.strip():
            return
        name = name.strip()

        try:
            tol_plus = float(self.measure_tol_plus_input.text() or 0.0)
            tol_minus = float(self.measure_tol_minus_input.text() or 0.0)
        except ValueError:
            QMessageBox.warning(self, "Invalid tolerance", "Tol + / Tol - must be numbers.")
            return

        template = DimensionTemplate(
            name=name, nominal=diameter, tol_plus=tol_plus, tol_minus=tol_minus, cpk=None
        )
        if name in self.bank.names():
            choice = QMessageBox.question(
                self, "Overwrite entry", f"'{name}' already exists in the bank. Overwrite it?"
            )
            if choice != QMessageBox.Yes:
                return
            self.bank.add(template, overwrite=True)
        else:
            self.bank.add(template)

        self._refresh_bank_combo()
        QMessageBox.information(
            self, "Added", f"'{name}' added to the dimension bank (\u2300{diameter:.4f} mm)."
        )
