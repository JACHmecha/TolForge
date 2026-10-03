"""Aligned CSV mapping, complete validation and immutable import ancestry."""
import csv
from copy import deepcopy
import hashlib
import io
import json

import pytest

from tolstack.inspection import INSPECTION_FIELDS
from tolstack.inspection_import import (
    default_mapping, parse_csv_bytes, preview_import, ImportValidationError,
)
from tolstack.project import Project
from tolstack.workflow import validate_study


def row(**changes):
    value = dict(name="Hole 1", basic_x="10", basic_y="20", measured_x="10.03", measured_y="20.04",
                 diameter="10.1", size_lower="10", size_upper="10.2", position_tolerance="0.2",
                 modifier="RFS", feature_kind="hole")
    value.update(changes)
    return value


def source(rows=None, *, delimiter=",", headers=INSPECTION_FIELDS, bom=False):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=headers, delimiter=delimiter)
    writer.writeheader()
    writer.writerows(rows or [row()])
    contents = output.getvalue().encode("utf-8-sig" if bom else "utf-8")
    return parse_csv_bytes(contents, "measurements.csv")


def preview(csv_source=None, **changes):
    csv_source = csv_source or source()
    options = dict(mapping=default_mapping(csv_source), units="mm",
                   external_alignment={"confirmed": True, "datum_frame": "A | B | C", "method": "CMM program 17"},
                   fitting_method="Least squares")
    options.update(changes)
    return preview_import(csv_source, **options)


@pytest.mark.parametrize("delimiter", [",", ";", "\t"])
def test_utf8_bom_and_dialects_preserve_original_hash_and_aligned_values(delimiter):
    captured = source(delimiter=delimiter, bom=True)
    accepted = preview(captured).accepted()
    assert captured.delimiter == delimiter
    assert accepted["rows"][0]["measured_x"] == "10.03"
    descriptor = accepted["source_descriptor"]
    assert descriptor["import_sha256"] == hashlib.sha256(captured.contents).hexdigest()
    assert descriptor["format"]["delimiter"] == delimiter
    assert descriptor["format"]["encoding"] == "utf-8-sig"


def test_noncanonical_columns_and_constants_are_recorded_exactly():
    captured = source([dict(ID="P-17", Label="Mount hole", X="10.03", Y="20.04", Dia="10.1")],
                      headers=("ID", "Label", "X", "Y", "Dia"))
    mapping = {field: {"constant": value} for field, value in row().items()}
    mapping.update(name={"column": "Label"}, measured_x={"column": "X"}, measured_y={"column": "Y"},
                   diameter={"column": "Dia"})
    accepted = preview(captured, mapping=mapping, source_feature_id_column="ID", units="in").accepted()
    assert accepted["rows"][0]["name"] == "Mount hole"
    assert accepted["rows"][0]["diameter"] == "10.1"  # No conversion.
    assert accepted["row_metadata"][0]["source_feature_id"] == "P-17"
    assert accepted["source_descriptor"]["mapping"] == mapping
    assert accepted["source_descriptor"]["units"] == "in"
    assert accepted["source_descriptor"]["fitting_method"] == "Least squares"


@pytest.mark.parametrize("field,value,message", [
    ("measured_x", "nan", "finite"), ("measured_y", "inf", "finite"), ("basic_x", "", "finite"),
    ("diameter", "0", "positive"), ("size_lower", "-1", "positive"), ("size_upper", "9", "size_lower"),
    ("position_tolerance", "-0.1", "nonnegative"), ("modifier", "MMB", "RFS"),
    ("feature_kind", "slot", "hole"), ("name", " ", "required"),
])
def test_invalid_final_row_blocks_whole_batch_with_source_row_and_field(field, value, message):
    result = preview(source([row(), row(name="Hole 2", **{field: value})] if field != "name" else
                            [row(), row(name=value)]))
    assert not result.valid
    assert any(error.row == 3 and error.field == field and message in error.message for error in result.errors)
    with pytest.raises(ImportValidationError, match="Row 3"):
        result.accepted()


@pytest.mark.parametrize("data", [
    b"", b"name,name\na,b\n", b",x\na,b\n", b"name,x\na\n", b"name\n\xff\n",
    b'name,x\n"unclosed,3\n',
])
def test_invalid_encoding_headers_and_records_are_rejected(data):
    with pytest.raises((ValueError, UnicodeError, csv.Error)):
        parse_csv_bytes(data, "bad.csv")


def test_duplicates_reject_names_and_external_ids_and_repeated_source_measurements():
    assert not preview(source([row(), row(name=" Hole 1 ")])).valid
    assert not preview(existing_names=["Hole 1"], existing_units=["mm"], dataset_units="mm").valid
    captured = source([dict(row(), source_id="X"), dict(row(name="Hole 2"), source_id="X")],
                      headers=INSPECTION_FIELDS + ("source_id",))
    duplicate = preview(captured, source_feature_id_column="source_id")
    assert any(error.field == "source_feature_id" for error in duplicate.errors)
    first = preview().accepted()
    repeated = preview(existing_ids=[first["row_metadata"][0]["id"]], dataset_units="mm", existing_units=["mm"])
    assert any(error.field == "id" for error in repeated.errors)


def test_unit_and_frame_labels_cannot_silently_convert_existing_measurements():
    changed_label = preview(units="in", existing_names=["Other"], existing_units=["mm"], dataset_units="in")
    assert any(error.field == "units" for error in changed_label.errors)
    mismatch = preview(existing_frames=["A | B | D"])
    assert any(error.field == "alignment" and "transformation" in error.message for error in mismatch.errors)
    assert preview(existing_frames=[" a|b|c "]).valid
    assert preview(units="in", dataset_units="mm").valid  # Empty dataset adopts source units.


@pytest.mark.parametrize("alignment", [
    {"confirmed": False, "datum_frame": "A", "method": "CMM"},
    {"confirmed": True, "datum_frame": "", "method": "CMM"},
    {"confirmed": True, "datum_frame": "A", "method": ""},
])
def test_explicit_external_alignment_is_required(alignment):
    assert not preview(external_alignment=alignment).valid


def test_identity_and_snapshots_survive_mapping_mutation_project_roundtrip(tmp_path):
    captured = source()
    mapping = default_mapping(captured)
    alignment = {"confirmed": True, "datum_frame": "A | B | C", "method": "CMM17"}
    prepared = preview(captured, mapping=mapping, external_alignment=alignment)
    original = prepared.accepted()
    assert preview(captured, mapping=mapping, external_alignment=alignment).accepted() == original
    mapping["name"] = {"constant": "Changed"}
    alignment["method"] = "Changed"
    detached = prepared.accepted()
    detached["row_metadata"][0]["id"] = "Changed"
    assert prepared.accepted() == original
    project = Project("Imported measurements")
    descriptor = deepcopy(original["source_descriptor"])
    descriptor["vendor_extension"] = {"calibration": "Cal 7", "uncertainty": 0.001}
    project.study = {"inspection": {"rows": original["rows"], "row_metadata": original["row_metadata"],
                                     "source_files": [descriptor]}}
    destination = tmp_path / "measurements.tolforge.json"
    project.save(destination)
    assert Project.load(destination).study == project.study
    assert json.loads(json.dumps(original, allow_nan=False)) == original


@pytest.mark.parametrize("mutate", [
    lambda data: data.update(row_metadata=[]),
    lambda data: data["row_metadata"][0].update(id=""),
    lambda data: data["row_metadata"][0].update(units="cm"),
    lambda data: data["row_metadata"][0].update(source_row=True),
    lambda data: data["source_files"][0].update(mapping={}),
    lambda data: data["source_files"][0].update(accepted_count=2),
    lambda data: data["source_files"][0].update(format={"delimiter": "|"}),
    lambda data: data["source_files"][0].update(external_alignment={"confirmed": False}),
])
def test_malformed_optional_import_metadata_is_rejected(mutate):
    accepted = preview().accepted()
    inspection = {"rows": accepted["rows"], "row_metadata": accepted["row_metadata"],
                  "source_files": [accepted["source_descriptor"]]}
    mutate(inspection)
    with pytest.raises(ValueError):
        validate_study({"inspection": inspection})


def test_legacy_path_hash_only_source_descriptor_remains_valid():
    validate_study({"inspection": {"rows": [row()], "source_files": [
        {"kind": "inspection_csv", "path": "source.csv", "import_sha256": "a" * 64}]}})


def test_unknown_finite_metadata_survives_and_nonfinite_extensions_are_rejected(tmp_path):
    accepted = preview().accepted()
    accepted["source_descriptor"]["vendor_extension"] = {"calibration": "Cal 7", "uncertainty": 0.001}
    inspection = {"rows": accepted["rows"], "row_metadata": accepted["row_metadata"],
                  "source_files": [accepted["source_descriptor"]]}
    validate_study({"inspection": inspection})
    inspection["source_files"][0]["vendor_extension"]["uncertainty"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        validate_study({"inspection": inspection})
