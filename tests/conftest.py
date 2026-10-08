"""Make native CAD coverage explicit without weakening the desktop baseline."""

import importlib
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))


@pytest.fixture(autouse=True)
def discard_unsaved_changes_by_default(monkeypatch):
    """Keep GUI cleanup noninteractive; lifecycle tests choose explicit answers."""
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Discard)


def pytest_addoption(parser):
    parser.addoption(
        "--require-native-cad", action="store_true", default=False,
        help="Require a working STEP backend and fail if any native_cad case skips.",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "native_cad: exercises the real OpenCASCADE/compas_occ backend",
    )


def _load_native_backend():
    from gui.runtime import configure_native_runtime

    configure_native_runtime()
    for module in ("OCC.Core.BRepPrimAPI", "OCC.Core.STEPControl", "compas_occ.brep"):
        importlib.import_module(module)


def pytest_sessionstart(session):
    # Match source startup before Qt fixtures load, including Windows ICU
    # selection when a Conda CAD environment has its own versioned ICU DLLs.
    from gui.runtime import configure_native_runtime

    configure_native_runtime()
    if session.config.getoption("--require-native-cad"):
        try:
            _load_native_backend()
        except Exception as exc:
            raise pytest.UsageError(
                f"Native CAD qualification requires a working backend: {type(exc).__name__}: {exc}"
            ) from exc


def pytest_collection_finish(session):
    if session.config.getoption("--require-native-cad") and not any(
        item.get_closest_marker("native_cad") for item in session.items
    ):
        raise pytest.UsageError("Native CAD qualification selected no native_cad tests.")


@pytest.fixture(scope="session")
def native_cad_backend(request):
    """Ordinary full-suite runs may skip optional CAD; qualification never does."""
    if request.config.getoption("--require-native-cad"):
        return  # Session startup already proved the required imports.
    try:
        _load_native_backend()
    except Exception as exc:
        pytest.skip(f"Optional native CAD backend unavailable: {type(exc).__name__}: {exc}")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    result = yield
    report = result.get_result()
    if (item.config.getoption("--require-native-cad")
            and item.get_closest_marker("native_cad") and report.skipped):
        report.outcome = "failed"
        report.longrepr = "Native CAD qualification cannot skip a selected native_cad test."
