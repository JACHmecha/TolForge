"""A missing or skipped CAD backend cannot produce successful qualification."""

from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

_BOUNDARY = Path(__file__).with_name("conftest.py").read_text(encoding="utf-8")


def _make_backend(pytester, error=None):
    """Use tiny native stand-ins in subprocesses, independent of this machine."""
    pytester.makeconftest(_BOUNDARY)
    for package in ("gui", "OCC", "OCC/Core", "compas_occ"):
        directory = pytester.path / package
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "__init__.py").write_text("", encoding="utf-8")
    (pytester.path / "gui/runtime.py").write_text(
        "def configure_native_runtime():\n    return ()\n", encoding="utf-8",
    )
    (pytester.path / "OCC/Core/BRepPrimAPI.py").write_text(error or "", encoding="utf-8")
    (pytester.path / "OCC/Core/STEPControl.py").write_text("", encoding="utf-8")
    (pytester.path / "compas_occ/brep.py").write_text("", encoding="utf-8")


@pytest.mark.parametrize("error", [
    'raise ModuleNotFoundError("No module named OCC")',
    'raise ImportError("DLL load failed while importing _BRepPrimAPI")',
])
def test_required_qualification_fails_for_missing_or_broken_backend(pytester, error):
    _make_backend(pytester, error)
    pytester.makepyfile(
        "import pytest\n@pytest.mark.native_cad\ndef test_native():\n    pass\n",
    )
    result = pytester.runpytest_subprocess("--require-native-cad", "-m", "native_cad", "-q")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "Native CAD qualification requires a working backend" in result.stderr.str()


def test_headless_selection_does_not_require_or_skip_a_native_backend(pytester):
    _make_backend(pytester, 'raise ImportError("broken native DLL")')
    pytester.makepyfile(
        "import pytest\n"
        "def test_scalar():\n    assert 1 + 1 == 2\n"
        "@pytest.mark.native_cad\n@pytest.mark.usefixtures('native_cad_backend')\n"
        "def test_native():\n    pass\n",
    )
    result = pytester.runpytest_subprocess("-m", "not native_cad", "--strict-markers", "-q")
    result.assert_outcomes(passed=1, deselected=1)


def test_required_qualification_rejects_skipped_native_cases(pytester):
    _make_backend(pytester)
    pytester.makepyfile(
        "import pytest\n@pytest.mark.native_cad\n"
        "def test_native():\n    pytest.skip('Simulated unavailable feature')\n",
    )
    result = pytester.runpytest_subprocess("--require-native-cad", "-m", "native_cad", "-q")
    result.assert_outcomes(failed=1)
    assert "qualification cannot skip" in result.stdout.str()


def test_required_qualification_cannot_select_only_headless_cases(pytester):
    _make_backend(pytester)
    pytester.makepyfile("def test_scalar():\n    pass\n")
    result = pytester.runpytest_subprocess("--require-native-cad", "-q")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "selected no native_cad tests" in result.stderr.str()


def test_required_qualification_succeeds_with_working_backend_and_native_case(pytester):
    _make_backend(pytester)
    pytester.makepyfile(
        "import pytest\n@pytest.mark.native_cad\n"
        "@pytest.mark.usefixtures('native_cad_backend')\ndef test_native():\n    pass\n",
    )
    result = pytester.runpytest_subprocess("--require-native-cad", "-m", "native_cad", "-q")
    result.assert_outcomes(passed=1)
