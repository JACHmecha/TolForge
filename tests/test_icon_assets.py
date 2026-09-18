import json
from pathlib import Path
from xml.etree import ElementTree


ICON_DIR = Path(__file__).resolve().parents[1] / "Code" / "gui" / "assets" / "icons" / "gdt"


def test_gdt_icon_manifest_references_valid_unique_svg_files():
    manifest = json.loads((ICON_DIR / "manifest.json").read_text(encoding="utf-8"))
    entries = manifest["icons"]
    ids = [entry["id"] for entry in entries]
    files = [entry["file"] for entry in entries]

    assert manifest["schema_version"] == 1
    assert len(ids) == len(set(ids))
    assert len(files) == len(set(files))
    assert set(files) == {path.name for path in ICON_DIR.glob("*.svg")}

    for filename in files:
        root = ElementTree.parse(ICON_DIR / filename).getroot()
        assert root.tag.endswith("svg")
        assert root.attrib["viewBox"] == manifest["view_box"]


def test_gdt_icon_library_contains_current_tolforge_controls():
    manifest = json.loads((ICON_DIR / "manifest.json").read_text(encoding="utf-8"))
    ids = {entry["id"] for entry in manifest["icons"]}

    assert {"position", "diameter", "mmc", "lmc", "rfs", "datum_feature"} <= ids
