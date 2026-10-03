"""Preview and validate already aligned, one-feature-per-row CSV measurements.

No coordinate fitting or unit conversion is performed. Source bytes are captured
once; changing the mapping reparses that captured revision, not the live file.
"""
from dataclasses import dataclass
import csv
import hashlib
import io
import json
from math import isfinite
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from .inspection import INSPECTION_FIELDS, InspectionFeature
from .json_data import validate_json_value


@dataclass(frozen=True)
class CsvSource:
    path: str
    contents: bytes
    sha256: str
    delimiter: str
    headers: tuple
    records: tuple


@dataclass(frozen=True)
class ImportErrorDetail:
    row: int | None
    field: str
    message: str

    def __str__(self):
        location = f"Row {self.row} · " if self.row is not None else ""
        return f"{location}{self.field}: {self.message}"


class ImportValidationError(ValueError):
    def __init__(self, errors):
        self.errors = tuple(errors)
        super().__init__("\n".join(map(str, self.errors)))


@dataclass(frozen=True)
class ImportPreview:
    """JSON-backed detached rows and ancestry; callers receive fresh copies."""
    _json: str
    errors: tuple

    @property
    def valid(self):
        return not self.errors

    def to_dict(self):
        return json.loads(self._json)

    def accepted(self):
        if self.errors:
            raise ImportValidationError(self.errors)
        return self.to_dict()


def parse_csv_bytes(contents, path, *, delimiter="auto"):
    if not isinstance(contents, bytes):
        raise ValueError("CSV source must be bytes.")
    decoded = contents.decode("utf-8-sig", errors="strict")
    if delimiter == "auto":
        try:
            delimiter = csv.Sniffer().sniff(decoded[:65536], delimiters=",;\t").delimiter
        except csv.Error:
            delimiter = ","
    if delimiter not in (",", ";", "\t"):
        raise ValueError("CSV delimiter must be comma, semicolon or tab.")
    reader = csv.reader(io.StringIO(decoded, newline=""), delimiter=delimiter, strict=True)
    try:
        headers = tuple(cell.strip() for cell in next(reader))
    except StopIteration:
        raise ValueError("CSV is empty; a header and measurements are required.") from None
    if not headers or any(not name for name in headers) or len(headers) != len(set(headers)):
        raise ValueError("CSV headers must be nonempty and unique.")
    records = []
    while True:
        source_row = reader.line_num + 1
        try:
            cells = next(reader)
        except StopIteration:
            break
        if not cells or all(not cell.strip() for cell in cells):
            continue
        if len(cells) != len(headers):
            raise ValueError(f"Row {source_row}: expected {len(headers)} columns, found {len(cells)}.")
        records.append((source_row, tuple(cells)))
    if not records:
        raise ValueError("CSV has no measurement rows.")
    return CsvSource(str(Path(path).resolve()), contents, hashlib.sha256(contents).hexdigest(),
                     delimiter, headers, tuple(records))


def read_aligned_csv(path, *, delimiter="auto"):
    return parse_csv_bytes(Path(path).read_bytes(), path, delimiter=delimiter)


def default_mapping(source):
    """Canonical legacy headers map automatically; other headers need review."""
    headers = {name.casefold(): name for name in source.headers}
    return {field: ({"column": headers[field]} if field in headers else
                    {"constant": {"modifier": "RFS", "feature_kind": "hole"}.get(field, "")})
            for field in INSPECTION_FIELDS}


def normalized_frame(value):
    return "".join(str(value).split()).casefold()


def validate_mapping(mapping, headers=None):
    if not isinstance(mapping, dict) or set(mapping) != set(INSPECTION_FIELDS):
        raise ValueError("Mapping must describe every inspection field.")
    for field, definition in mapping.items():
        if (not isinstance(definition, dict) or len(definition) != 1
                or next(iter(definition)) not in ("column", "constant")
                or not isinstance(next(iter(definition.values())), str)):
            raise ValueError(f"Mapping {field} must specify one column or text constant.")
        if "column" in definition and (not definition["column"] or
                                        headers is not None and definition["column"] not in headers):
            raise ValueError(f"Mapping {field} references a missing column.")


def validate_alignment(alignment):
    if not isinstance(alignment, dict) or alignment.get("confirmed") is not True:
        raise ValueError("Explicitly confirm that coordinates are externally aligned; no fitting is performed.")
    for key in ("datum_frame", "method"):
        if not isinstance(alignment.get(key), str) or not alignment[key].strip():
            raise ValueError(f"External alignment {key.replace('_', ' ')} is required.")


def preview_import(source, mapping, *, units, external_alignment, fitting_method,
                   source_feature_id_column=None, existing_names=(), existing_ids=(),
                   existing_units=(), dataset_units=None, existing_frames=()):
    """Validate the entire batch without changing the dataset or source file."""
    existing_names = tuple(existing_names)
    existing_ids = tuple(existing_ids)
    existing_units = tuple(existing_units)
    existing_frames = tuple(existing_frames)
    errors = []
    try:
        validate_mapping(mapping, source.headers)
    except ValueError as exc:
        errors.append(ImportErrorDetail(None, "mapping", str(exc)))
    if units not in ("mm", "in"):
        errors.append(ImportErrorDetail(None, "units", "choose mm or in; conversion is not available"))
    if existing_names or existing_ids or existing_units:
        if dataset_units != units or any(value != units for value in existing_units):
            errors.append(ImportErrorDetail(None, "units", "existing measurements use different units; changing the label does not convert values"))
    try:
        validate_alignment(external_alignment)
    except ValueError as exc:
        errors.append(ImportErrorDetail(None, "alignment", str(exc)))
    frame = external_alignment.get("datum_frame", "") if isinstance(external_alignment, dict) else ""
    if any(value and normalized_frame(value) != normalized_frame(frame) for value in existing_frames):
        errors.append(ImportErrorDetail(None, "alignment", "datum frame differs from existing measurements; coordinate transformation is not available"))
    if not isinstance(fitting_method, str) or not fitting_method.strip():
        errors.append(ImportErrorDetail(None, "fitting_method", "record the source fitting method or state that it was not recorded"))
    if source_feature_id_column is not None and source_feature_id_column not in source.headers:
        errors.append(ImportErrorDetail(None, "source_feature_id", "selected source identifier column is missing"))
    if errors:
        return ImportPreview(json.dumps({"rows": [], "row_metadata": [], "source_descriptor": None}), tuple(errors))

    # Canonical settings make identifiers stable across previews and reloads.
    alignment = {"confirmed": True, "datum_frame": frame.strip(),
                 "method": external_alignment["method"].strip()}
    settings = {"mapping": mapping, "units": units, "external_alignment": alignment,
                "fitting_method": fitting_method.strip(), "source_feature_id_column": source_feature_id_column,
                "delimiter": source.delimiter, "source_sha256": source.sha256}
    import_id = str(uuid5(NAMESPACE_URL, "tolforge:aligned-csv:" + json.dumps(settings, sort_keys=True)))
    names = {str(name).strip() for name in existing_names}
    ids = set(existing_ids)
    external_ids = set()
    rows, metadata = [], []
    numeric = INSPECTION_FIELDS[1:9]
    for line, cells in source.records:
        record = dict(zip(source.headers, cells))
        row = {key: (record[definition["column"]] if "column" in definition else definition["constant"]).strip()
               for key, definition in mapping.items()}
        row["modifier"] = row["modifier"].upper()
        row["feature_kind"] = row["feature_kind"].lower()
        row_errors = []
        if not row["name"]:
            row_errors.append(ImportErrorDetail(line, "name", "feature name is required"))
        elif row["name"] in names:
            row_errors.append(ImportErrorDetail(line, "name", "feature name duplicates an existing or imported measurement"))
        names.add(row["name"])
        numbers = {}
        for field in numeric:
            try:
                value = float(row[field])
                if not isfinite(value):
                    raise ValueError()
                numbers[field] = value
                if field in ("diameter", "size_lower", "size_upper") and value <= 0:
                    row_errors.append(ImportErrorDetail(line, field, "must be positive"))
                elif field == "position_tolerance" and value < 0:
                    row_errors.append(ImportErrorDetail(line, field, "must be nonnegative"))
            except (ValueError, OverflowError):
                row_errors.append(ImportErrorDetail(line, field, "expected a finite number"))
        if ("size_lower" in numbers and "size_upper" in numbers
                and numbers["size_lower"] > numbers["size_upper"]):
            row_errors.append(ImportErrorDetail(line, "size_upper", "must be at least size_lower"))
        if row["modifier"] not in ("RFS", "MMC", "LMC"):
            row_errors.append(ImportErrorDetail(line, "modifier", "supported values are RFS, MMC and LMC"))
        if row["feature_kind"] not in ("hole", "pin"):
            row_errors.append(ImportErrorDetail(line, "feature_kind", "supported values are hole and pin"))
        external_id = record[source_feature_id_column].strip() if source_feature_id_column else None
        if source_feature_id_column and (not external_id or external_id in external_ids):
            row_errors.append(ImportErrorDetail(line, "source_feature_id", "source identifier must be nonempty and unique within the batch"))
        external_ids.add(external_id)
        identity = str(uuid5(NAMESPACE_URL, f"tolforge:measurement:{import_id}:" +
                             ("external:" + external_id if external_id is not None else f"row:{line}")))
        if identity in ids:
            row_errors.append(ImportErrorDetail(line, "id", "this source measurement has already been imported"))
        ids.add(identity)
        if not row_errors:
            InspectionFeature.from_row(row)  # Keep the service aligned with the bounded engine.
        errors.extend(row_errors)
        rows.append(row)
        metadata.append({"id": identity, "units": units, "source_feature_id": external_id,
                         "source_row": line, "import_id": import_id, "import_sha256": source.sha256,
                         "source_path": source.path, "external_alignment": alignment,
                         "fitting_method": fitting_method.strip()})
    descriptor = {"kind": "inspection_csv", "path": source.path, "import_sha256": source.sha256,
                  "importer_kind": "generic_aligned_csv", "importer_version": 1, "import_id": import_id,
                  "mapping": mapping, "units": units, "external_alignment": alignment,
                  "fitting_method": fitting_method.strip(), "source_feature_id_column": source_feature_id_column,
                  "format": {"delimiter": source.delimiter, "encoding": "utf-8-sig", "header": list(source.headers)},
                  "accepted_count": len(rows), "measurement_ids": [item["id"] for item in metadata],
                  "source_feature_ids": [item["source_feature_id"] for item in metadata]}
    payload = {"rows": rows, "row_metadata": metadata, "source_descriptor": descriptor}
    return ImportPreview(json.dumps(payload, allow_nan=False, sort_keys=True), tuple(errors))


def validate_row_metadata(metadata, rows):
    validate_json_value(metadata, "Inspection measurement metadata")
    if not isinstance(metadata, list) or len(metadata) != len(rows):
        raise ValueError("Inspection row metadata must have one object per measurement row.")
    ids = set()
    for item in metadata:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].strip():
            raise ValueError("Inspection measurement metadata requires a nonempty stable id.")
        if item["id"] in ids:
            raise ValueError("Inspection measurement ids must be unique.")
        ids.add(item["id"])
        if "units" in item and item["units"] not in ("mm", "in"):
            raise ValueError("Inspection measurement units must be mm or in.")
        for key in ("source_feature_id", "import_id", "source_path", "fitting_method"):
            if key in item and item[key] is not None and not isinstance(item[key], str):
                raise ValueError(f"Inspection measurement {key} must be text.")
        if "source_row" in item and (type(item["source_row"]) is not int or item["source_row"] < 2):
            raise ValueError("Inspection source_row must identify a CSV data row.")
        if "import_sha256" in item:
            _validate_hash(item["import_sha256"])
        if "external_alignment" in item:
            validate_alignment(item["external_alignment"])


def _validate_hash(value):
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdefABCDEF" for char in value):
        raise ValueError("Inspection import_sha256 must be a 64-character SHA-256 digest.")


def validate_import_descriptor(source):
    """Validate richer descriptors without breaking old path/hash-only files."""
    validate_json_value(source, "Inspection import descriptor")
    if source.get("importer_kind") == "generic_aligned_csv":
        required = {"importer_version", "import_id", "mapping", "units", "external_alignment",
                    "fitting_method", "source_feature_id_column", "format", "accepted_count",
                    "measurement_ids", "source_feature_ids", "import_sha256"}
        if not required.issubset(source):
            raise ValueError("Generic aligned CSV descriptor is missing accepted import settings or identities.")
    if "mapping" in source:
        validate_mapping(source["mapping"])
    if "units" in source and source["units"] not in ("mm", "in"):
        raise ValueError("Inspection import units must be mm or in.")
    if "external_alignment" in source:
        validate_alignment(source["external_alignment"])
    for key in ("import_id", "importer_kind", "fitting_method", "source_feature_id_column"):
        if key in source and source[key] is not None and (not isinstance(source[key], str) or not source[key].strip()):
            raise ValueError(f"Inspection import {key} must be nonempty text.")
    if "importer_version" in source and (type(source["importer_version"]) is not int or source["importer_version"] < 1):
        raise ValueError("Inspection importer_version must be a positive integer.")
    if "accepted_count" in source and (type(source["accepted_count"]) is not int or source["accepted_count"] < 1):
        raise ValueError("Inspection accepted_count must be a positive integer.")
    for key in ("measurement_ids", "source_feature_ids"):
        if key in source and (not isinstance(source[key], list) or any(
                (not isinstance(value, str) or not value.strip()) and not (key == "source_feature_ids" and value is None)
                for value in source[key])):
            raise ValueError(f"Inspection import {key} must be a list of identifiers.")
        if key in source and "accepted_count" in source and len(source[key]) != source["accepted_count"]:
            raise ValueError(f"Inspection import {key} must match accepted_count.")
    if "measurement_ids" in source and len(source["measurement_ids"]) != len(set(source["measurement_ids"])):
        raise ValueError("Inspection import measurement_ids must be unique.")
    if "source_feature_ids" in source:
        identifiers = [value for value in source["source_feature_ids"] if value is not None]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Inspection import source_feature_ids must be unique within the batch.")
    if "format" in source:
        fmt = source["format"]
        if (not isinstance(fmt, dict) or fmt.get("delimiter") not in (",", ";", "\t")
                or fmt.get("encoding") != "utf-8-sig" or not isinstance(fmt.get("header"), list)
                or not fmt["header"] or any(not isinstance(value, str) or not value for value in fmt["header"])
                or len(fmt["header"]) != len(set(fmt["header"]))):
            raise ValueError("Inspection import format must record a valid UTF-8 CSV delimiter and unique headers.")
        if "mapping" in source:
            validate_mapping(source["mapping"], fmt["header"])
        if source.get("source_feature_id_column") is not None and source["source_feature_id_column"] not in fmt["header"]:
            raise ValueError("Inspection source identifier column is absent from the captured CSV headers.")
