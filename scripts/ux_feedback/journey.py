"""Bounded Qt Widgets pilot driven through the same controls as a user.

This module deliberately imports Qt only inside ``run_journey``: the parent
runner must select its isolated offscreen platform before Qt initializes.
Renderer, persistence observation and recovery location are setup boundaries;
all measured edits/navigation/analysis use QtTest mouse or keyboard events.
Screenshots cover scalar widgets/layout only, never CAD/native rendering.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import platform
import sys
import time
import traceback
from unittest.mock import patch


class ProductFailure(AssertionError):
    """An explicit oracle disagreed after the driver delivered its action."""


class DriverError(RuntimeError):
    """A driver/precondition failure must never masquerade as a product defect."""


def run_journey(output_dir: Path, size: tuple[int, int], inject_failure: bool = False) -> dict:
    """Return evidence for U01, U02 and U06 in one fresh child process.

    ``output_dir`` must be an isolated configuration directory owned by the
    caller. No engineering projects are opened or saved. The diagnostic flag
    changes only an expected oracle value; it never mutates production code.
    """
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    width, height = size
    result = {
        "id": f"{width}x{height}", "width": width, "height": height,
        "status": "runner_error", "environment": {},
        "coverage": {
            "mode": "QtTest scalar widgets, offscreen layout",
            "scenarios": ["U01", "U02", "U06"],
            "excluded": ["native desktop", "CAD viewport", "GPU/picking", "RSS", "Monte Carlo", "human usability"],
            "diagnostic": bool(inject_failure),
            "persistence": "Synthetic inputs only; isolated recovery path; persistence observers suspended.",
        },
        "steps": [], "scenarios": [], "findings": [],
    }
    window = app = None
    font_ids = []
    previous_hook = sys.excepthook
    asynchronous_errors = []
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Code"))
        from gui.runtime import configure_native_runtime

        configure_native_runtime()
        from PySide6 import __version__ as pyside_version
        from PySide6.QtCore import Qt, QTimer, qVersion
        from PySide6.QtGui import QFontDatabase
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea
        import gui.step_viewer_mixin as viewport
        from gui.app import TolstackWindow
        from gui.theme import apply_application_palette
        from tolstack import drafts
    except (ImportError, OSError) as exc:
        result["status"] = "infrastructure_unavailable"
        result["findings"].append({"id": "environment", "classification": "infrastructure", "severity": "high", "title": "Qt environment unavailable", "description": f"{type(exc).__name__}: {exc}", "reproduction": [], "suggestion": "Run with the documented GUI dependencies and Qt platform plugin available."})
        return result

    def qt_exception(kind, value, tb):
        asynchronous_errors.append("".join(traceback.format_exception(kind, value, tb)))

    sys.excepthook = qt_exception

    class Pilot:
        scenario = "U01"
        override_screenshot = None

        def settle(self):
            # Processing is bounded; waits below are condition driven.
            for _ in range(4):
                app.processEvents()
            if asynchronous_errors:
                raise DriverError("Unhandled Qt callback: " + asynchronous_errors[-1])

        def wait_for(self, predicate, description, timeout_ms=1500):
            until = time.monotonic() + timeout_ms / 1000
            while time.monotonic() < until:
                self.settle()
                if predicate():
                    return
                QTest.qWait(10)
            raise DriverError(f"Timed out waiting for {description} ({timeout_ms} ms)")

        def verify(self, condition, description):
            if not condition:
                raise ProductFailure(description)

        def screenshot(self, stem, widget=None):
            path = output_dir / f"{stem}.png"
            if path.exists():
                raise DriverError(f"Refusing to replace evidence: {path.name}")
            pixmap = (widget or window).grab()
            if pixmap.isNull() or not pixmap.save(str(path), "PNG") or path.stat().st_size == 0:
                raise DriverError(f"Could not capture {path.name}")
            return path.name

        def scroll_areas(self, widget):
            parent = widget.parentWidget()
            while parent:
                if isinstance(parent, QScrollArea):
                    yield parent
                parent = parent.parentWidget()

        def reveal(self, widget):
            if not widget.isVisible() or not widget.isEnabled():
                raise DriverError(f"Control unavailable: {widget.objectName() or widget.__class__.__name__}")
            # Keyboard events scroll the real visible container, without
            # changing its value directly or invoking application handlers.
            for area in self.scroll_areas(widget):
                bar = area.verticalScrollBar()
                def fits():
                    bounds = area.viewport().rect()
                    return (bounds.contains(widget.mapTo(area.viewport(), widget.rect().topLeft()))
                            and bounds.contains(widget.mapTo(area.viewport(), widget.rect().bottomRight())))
                if not fits():
                    QTest.keyClick(bar, Qt.Key_Home)
                    self.settle()
                    for _ in range(200):
                        if fits():
                            break
                        before = bar.value()
                        QTest.keyClick(bar, Qt.Key_Down)
                        self.settle()
                        if bar.value() == before:
                            break
                    if not fits():
                        raise DriverError("Control could not be reached by scrolling")

        def click(self, widget):
            self.reveal(widget)
            QTest.mouseClick(widget, Qt.LeftButton, pos=widget.rect().center())
            self.settle()

        def button(self, caption):
            found = [w for w in window.findChildren(QPushButton) if w.text() == caption and w.isVisible()]
            if len(found) != 1:
                raise DriverError(f"Expected one visible button {caption!r}, found {len(found)}")
            return found[0]

        def workspace(self, name):
            self.click(window.workspace_buttons[name])
            self.verify(window.sidebar.currentWidget() is window.workspace_pages[name], f"Navigation did not open {name}")

        def top(self, widget):
            for area in self.scroll_areas(widget):
                QTest.keyClick(area.verticalScrollBar(), Qt.Key_Home)
            self.settle()

        def cell(self, row, column, text=None, sign=None):
            table = window.table
            self.reveal(table)
            QTest.mouseClick(table.viewport(), Qt.LeftButton, pos=table.viewport().rect().center())
            QTest.keyClick(table, Qt.Key_Home, Qt.ControlModifier)
            for _ in range(row):
                QTest.keyClick(table, Qt.Key_Down)
            for _ in range(column):
                QTest.keyClick(table, Qt.Key_Right)
            self.settle()
            if (table.currentIndex().row(), table.currentIndex().column()) != (row, column):
                raise DriverError(f"Keyboard failed to select cell ({row}, {column})")
            if sign is not None:
                if table.sign(row) != sign:
                    QTest.keyClick(table, Qt.Key_Space)
                self.settle()
                if table.sign(row) != sign:
                    raise DriverError("Sign keyboard event was not committed")
                return
            if text is None:
                return
            QTest.keyClick(table, Qt.Key_F2)
            self.settle()
            editors = [widget for widget in table.findChildren(QLineEdit) if widget.isVisible()]
            if len(editors) != 1:
                raise DriverError("Table did not expose its text editor after F2")
            editor = editors[0]
            QTest.keyClick(editor, Qt.Key_A, Qt.ControlModifier)
            QTest.keyClicks(editor, text)
            QTest.keyClick(editor, Qt.Key_Return)
            self.settle()
            if table.item(row, column).text() != text:
                raise DriverError(f"Keyboard edit did not commit row {row + 1}, column {column + 1}")

        def input(self, widget, text):
            self.click(widget)
            editor = widget.lineEdit() if hasattr(widget, "lineEdit") else widget
            QTest.keyClick(editor, Qt.Key_A, Qt.ControlModifier)
            QTest.keyClicks(editor, text)
            QTest.keyClick(editor, Qt.Key_Tab)
            self.settle()

        def report(self, plus):
            report = window._last_analysis_report
            self.verify(report is not None, "Analyze stack did not produce a current report")
            # Independent arithmetic: housing minus pin, and uniform variance
            # proportional to each symmetric tolerance squared.
            expected_nominal = 10 - 9
            if inject_failure:
                expected_nominal += 0.125
            expected_min = (10 - plus) - (9 + 0.1)
            expected_max = (10 + plus) - (9 - 0.1)
            self.verify(math.isclose(report.result.nominal, expected_nominal, abs_tol=1e-12),
                        "Verifier selftest: injected nominal mismatch (not a real defect)" if inject_failure else "Nominal clearance differs from independent 10 - 9 oracle")
            self.verify(math.isclose(report.result.lower_limit, expected_min, abs_tol=1e-12), "Worst-case minimum differs from independent extrema oracle")
            self.verify(math.isclose(report.result.upper_limit, expected_max, abs_tol=1e-12), "Worst-case maximum differs from independent extrema oracle")
            expected_housing = plus ** 2 / (plus ** 2 + 0.1 ** 2)
            contributions = {item.name: item.variance_fraction for item in report.contributions}
            self.verify(set(contributions) == {"Housing", "Pin"}, "Contributors do not identify both entered dimensions")
            self.verify(math.isclose(contributions["Housing"], expected_housing, abs_tol=1e-12), "Housing contribution differs from independent uniform variance oracle")
            self.verify(math.isclose(contributions["Pin"], 1 - expected_housing, abs_tol=1e-12), "Pin contribution differs from independent uniform variance oracle")
            return {"nominal": report.result.nominal, "minimum": report.result.lower_limit, "maximum": report.result.upper_limit,
                    "contributions": contributions, "acceptance": report.acceptance.status, "fit_at_zero": report.fit_at_zero.verdict}

        def label(self, text):
            labels = [item for item in window.result_label.findChildren(QLabel) if item.text() == text and item.isVisible()]
            if len(labels) != 1:
                raise ProductFailure(f"Results do not expose the visible label {text!r}")
            return labels[0]

        def warning(self, button, expected_title, stem, message_tokens=()):
            seen = []
            errors = []
            timer = QTimer(window)
            started = time.monotonic()

            def dismiss():
                modal = app.activeModalWidget()
                if modal is None:
                    if time.monotonic() - started > 4:
                        timer.stop()
                    return
                timer.stop()
                try:
                    if not isinstance(modal, QMessageBox):
                        QTest.keyClick(modal, Qt.Key_Escape)
                        raise DriverError(f"Unexpected modal {type(modal).__name__}")
                    seen.append({"title": modal.windowTitle(), "message": modal.text()})
                    self.override_screenshot = self.screenshot(stem, modal)
                    ok = modal.button(QMessageBox.Ok)
                    if ok is None:
                        QTest.keyClick(modal, Qt.Key_Escape)
                        raise DriverError("Expected warning has no OK action")
                    QTest.mouseClick(ok, Qt.LeftButton)
                except Exception as exc:
                    errors.append(exc)
                    QTest.keyClick(modal, Qt.Key_Escape)

            timer.timeout.connect(dismiss)
            timer.start(20)
            try:
                self.click(button)
                self.settle()
                if errors:
                    raise errors[0]
                self.verify(bool(seen), "Expected a visible warning after the delivered action")
                self.verify(seen[0]["title"] == expected_title, f"Expected {expected_title!r}; observed {seen[0]['title']!r}")
                message = seen[0]["message"].lower()
                self.verify(all(token.lower() in message for token in message_tokens),
                            f"Warning did not identify the expected field or recovery action: {message_tokens!r}")
                return seen[0]
            finally:
                timer.stop()
                timer.deleteLater()

        def step(self, identifier, title, action, expected, operation):
            started = time.monotonic()
            step = {"id": identifier, "scenario": self.scenario, "title": title, "action": action,
                    "expected": expected, "observed": None, "status": "pass", "screenshot": None}
            self.override_screenshot = None
            error = None
            try:
                step["observed"] = operation()
                self.settle()
            except ProductFailure as exc:
                step["status"] = "product_failure"
                error = exc
            except Exception as exc:
                step["status"] = "runner_error"
                error = exc
            if error:
                step["observed"] = f"{type(error).__name__}: {error}"
            try:
                step["screenshot"] = self.override_screenshot or self.screenshot(identifier)
            except Exception as exc:
                step["status"] = "runner_error"
                step["observed"] = f"{step['observed']}; screenshot failed: {exc}"
                error = error or exc
            step["elapsed_ms"] = round((time.monotonic() - started) * 1000, 2)
            result["steps"].append(step)
            with (output_dir / "steps.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(step, ensure_ascii=False) + "\n")
            if error:
                result["status"] = step["status"]
                result["findings"].append({"id": identifier, "step": identifier, "scenario": self.scenario,
                                           "classification": "defect_reproduced" if step["status"] == "product_failure" else "runner_error",
                                           "severity": "high", "title": "Verifier selftest (diagnostic only)" if inject_failure else title,
                                           "description": step["observed"], "screenshot": step["screenshot"], "expected": expected,
                                           "action": action, "reproduction": [item["action"] for item in result["steps"]],
                                           "suggestion": "Diagnostic only: rerun without --inject-failure to evaluate the application." if inject_failure else
                                           "Repeat the listed actions and compare the captured state with the independent expected result; inspect the affected validation or result presentation." if step["status"] == "product_failure" else
                                           "Inspect the driver action and environment in steps.jsonl before drawing conclusions about the product."})
                raise error

    pilot = Pilot()
    try:
        app = QApplication.instance() or QApplication([])
        if not QFontDatabase.families():
            fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
            for name in ("segoeui.ttf", "segoeuib.ttf"):
                if (fonts / name).exists():
                    font_ids.append(QFontDatabase.addApplicationFont(str(fonts / name)))
        if not QFontDatabase.families():
            raise ImportError("No Qt fonts available for meaningful widget/layout evidence")
        apply_application_palette(app)
        recovery_dir = output_dir / ".state" / "drafts"
        # The source-mode draft location otherwise points into the checkout.
        # Disable only environment/native-rendering and persistence observers;
        # analysis, validation and widget signals remain real.
        with patch.object(viewport, "Renderer", None), patch.object(drafts, "draft_directory", return_value=recovery_dir):
            window = TolstackWindow()
        window._project_change_timer.stop()
        window._project_draft_timer.stop()
        window._project_change_pause += 1
        window.resize(width, height)
        window.show()
        pilot.settle()
        result["environment"] = {
            "python": platform.python_version(), "pyside6": pyside_version, "qt": qVersion(),
            "os": platform.platform(), "qt_platform": app.platformName(), "device_pixel_ratio": window.devicePixelRatioF(),
            "requested_size": [width, height], "actual_size": [window.width(), window.height()],
            "renderer": "disabled: scalar widget evidence only", "fonts_loaded": len(font_ids),
        }
        if (window.width(), window.height()) != (width, height):
            raise DriverError(f"Requested {width}x{height}, but Qt produced {window.width()}x{window.height()}; this size was not tested")
        if app.platformName() != "offscreen" or not math.isclose(window.devicePixelRatioF(), 1.0, abs_tol=1e-9):
            raise DriverError("The initial pilot requires Qt offscreen at device pixel ratio 1; observed environment is recorded")

        def prepare():
            pilot.workspace("stack")
            while window.table.rowCount():
                pilot.cell(0, 0)
                before = window.table.rowCount()
                pilot.click(pilot.button("- Remove selected"))
                pilot.verify(window.table.rowCount() == before - 1, "Remove selected did not remove the selected example row")
            pilot.top(window.table)
            return {"rows": window.table.rowCount(), "workspace": "stack"}

        pilot.step("U01-01", "Start a fresh synthetic stack", "Open Stack; select and remove the three example rows using visible controls", "Stack page with no rows", prepare)

        def enter():
            for row, values in enumerate((("Housing", "10", "0.2", "0.2", "+", ""), ("Pin", "9", "0.1", "0.1", "-", ""))):
                pilot.click(pilot.button("+ Add dimension"))
                for column, value in enumerate(values):
                    if column == 4:
                        pilot.cell(row, column, sign=value)
                    else:
                        pilot.cell(row, column, text=value)
            pilot.cell(0, 0)
            pilot.top(window.table)
            return {"rows": [list(row) for row in window.table.model().rows_snapshot()]}

        pilot.step("U01-02", "Enter opposing dimensions", "Add two rows; type names, nominal dimensions and symmetric tolerances; toggle Pin sign with Space", "Housing 10 ±0.2 minus Pin 9 ±0.1; blank Cpk means uniform", enter)

        def analyze():
            pilot.click(window.stack_analyze_button)
            pilot.verify(window.sidebar.currentWidget() is window.results_tab, "Analyze stack did not open Results")
            observation = pilot.report(.2)
            pilot.top(window.result_label)
            return observation

        pilot.step("U01-03", "Analyze the entered stack", "Click Analyze stack (Worst Case)", "Nominal 1; bounds [0.7, 1.3]; contributions Housing 80%, Pin 20%", analyze)
        result["scenarios"].append({"id": "U01", "status": "pass", "title": "Create and analyze a signed tolerance stack", "scope": "QtTest scalar inputs and Worst Case results; independent extrema and uniform variance oracles"})
        pilot.scenario = "U02"

        def limits():
            # Maximum first avoids an invalid transient min > max.
            pilot.input(window.range_max_input, "1.1")
            pilot.input(window.range_min_input, "0.9")
            pilot.verify(math.isclose(window.range_min_input.value(), .9), "Acceptance minimum was not committed")
            pilot.verify(math.isclose(window.range_max_input.value(), 1.1), "Acceptance maximum was not committed")
            pilot.click(window.results_analyze_button)
            observation = pilot.report(.2)
            report = window._last_analysis_report
            pilot.verify(report.acceptance.status == "overlaps_limits", "Functional acceptance should overlap, not fully meet [0.9, 1.1]")
            pilot.verify(report.fit_at_zero.verdict == "gap", "Positive [0.7, 1.3] band should have a gap at zero")
            pilot.verify(report.acceptance.rejection_probability is None, "Worst Case must not invent a probabilistic yield")
            pilot.reveal(pilot.label("Functional acceptance").parentWidget())
            return observation

        pilot.step("U02-01", "Distinguish acceptance from clearance", "Set visible acceptance fields to [0.9, 1.1]; click Analyze stack", "Overlaps functional limits while zero-clearance fit is GAP; no invented yield", limits)

        def fit_review():
            pilot.reveal(pilot.label("Separate zero-clearance fit check").parentWidget())
            return {"visible_section": "Separate zero-clearance fit check", "fit": window._last_analysis_report.fit_at_zero.verdict}

        pilot.step("U02-02", "Review the separate fit decision", "Scroll Results with the keyboard to the zero-clearance fit card", "Explicitly separate fit section", fit_review)

        def contributors():
            pilot.reveal(pilot.label("Variance contributors").parentWidget())
            return {"visible_section": "Variance contributors", "fractions": {item.name: item.variance_fraction for item in window._last_analysis_report.contributions}}

        pilot.step("U02-03", "Review dominant tolerance", "Scroll Results with the keyboard to variance contributors", "Housing contributes 80%; Pin contributes 20%", contributors)
        result["scenarios"].append({"id": "U02", "status": "pass", "title": "Interpret functional acceptance, fit and contributors", "scope": "Functional limits distinct from zero fit; cards reachable with keyboard scrolling"})
        pilot.scenario = "U06"

        def invalid():
            pilot.workspace("stack")
            pilot.cell(0, 2, text="invalid")
            pilot.workspace("results")
            pilot.verify(window._last_analysis_report is None, "Editing inputs left the old report current")
            pilot.verify("run analysis" in window.result_label.text().lower(), "Editing inputs did not communicate stale results")
            pilot.top(window.result_label)
            return {"current_report": False, "message": window.result_label.text()}

        pilot.step("U06-01", "Invalidate old results on edit", "Replace Housing Tol+ with invalid text using the table editor; open Results", "Previous report cleared and refresh guidance visible", invalid)
        pilot.step("U06-02", "Block stale report export", "Click Export stack report; capture and dismiss the real warning", "Warning instructs running stack analysis before exporting; no report save dialog", lambda: pilot.warning(pilot.button("Export stack report"), "No current report", "U06-02-warning", ("run", "stack analysis", "before exporting")))
        pilot.step("U06-03", "Explain an invalid dimension", "Click Analyze stack; capture Invalid data and dismiss its OK button", "Warning identifies Row 1, positive tolerance and finite-number requirement; no current report", lambda: pilot.warning(window.results_analyze_button, "Invalid data", "U06-03-warning", ("row 1", "positive tolerance", "finite")))

        def correction():
            pilot.verify(window._last_analysis_report is None, "Invalid analysis retained a current report")
            pilot.workspace("stack")
            pilot.cell(0, 2, text="0.1")
            pilot.cell(0, 3, text="0.1")
            pilot.click(window.stack_analyze_button)
            observation = pilot.report(.1)
            pilot.verify(window._last_analysis_report.acceptance.status == "overlaps_limits", "Corrected [0.8, 1.2] must still overlap [0.9, 1.1]")
            pilot.top(window.result_label)
            return observation

        pilot.step("U06-04", "Correct and reevaluate a tighter tolerance", "Correct Housing tolerance to ±0.1; click Analyze stack", "Fresh nominal 1; bounds [0.8, 1.2]; equal 50% variance contributions", correction)
        result["scenarios"].append({"id": "U06", "status": "pass", "title": "Reject invalid input, block stale export and recover", "scope": "Committed invalid cell, real validation/export warnings, stale result clearing and corrected analysis"})
        result["status"] = "pass"
    except (ProductFailure, DriverError) as exc:
        if not result["findings"]:
            result["status"] = "runner_error"
            result["findings"].append({"id": "setup", "classification": "runner_error", "severity": "high", "title": "Journey setup failed", "description": f"{type(exc).__name__}: {exc}", "reproduction": [], "suggestion": "Inspect child process logs and setup before interpreting product behavior."})
    except (ImportError, OSError) as exc:
        result["status"] = "infrastructure_unavailable"
        result["findings"].append({"id": "setup", "classification": "infrastructure", "severity": "high", "title": "Journey environment unavailable", "description": f"{type(exc).__name__}: {exc}", "reproduction": [], "suggestion": "Check installed Qt dependencies, fonts and writable isolated output directory."})
    except Exception as exc:
        result["status"] = "runner_error"
        result["findings"].append({"id": "unexpected", "classification": "runner_error", "severity": "high", "title": "Unexpected runner failure", "description": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc(), "reproduction": [], "suggestion": "Inspect the child process traceback; this is not evidence of a product defect."})
    finally:
        # Only cleanup guards are bypassed; user-facing measured actions above
        # never call handlers directly. deleteLater avoids Save/Discard prompts.
        if window is not None:
            for timer in window.findChildren(QTimer):
                timer.stop()
            window.hide()
            window.deleteLater()
            app.processEvents()
        for font_id in font_ids:
            QFontDatabase.removeApplicationFont(font_id)
        sys.excepthook = previous_hook
        completed = {item["id"] for item in result["scenarios"]}
        failed_scenario = next((step["scenario"] for step in result["steps"] if step["status"] != "pass"), None)
        for identifier in ("U01", "U02", "U06"):
            if identifier not in completed:
                result["scenarios"].append({"id": identifier, "status": result["status"] if identifier == failed_scenario else "not_run", "title": "Stopped after first failure", "scope": "No passing evidence claimed for this scenario"})
    return result
