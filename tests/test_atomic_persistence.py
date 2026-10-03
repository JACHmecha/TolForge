"""Disk failures must never replace a saved study with partial JSON."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

from tolstack import persistence
from tolstack.annotations import AnnotationSet, DimensionLinkDefinition, FeatureReference
from tolstack.bank import DimensionBank, DimensionTemplate
from tolstack.domain import ToleranceDefinition
from tolstack.features import FeatureSignature
from tolstack.project import Project


def _fail_file_operation(monkeypatch, failure, destination):
    """Inject a partial write, sync failure or replacement failure at disk I/O."""
    if failure.startswith("write"):
        original = persistence.tempfile.NamedTemporaryFile
        target_write = 2 if failure == "write_backup" else 1
        writes = 0

        class FailingWriter:
            def __init__(self, output):
                self.output = output

            def __enter__(self):
                self.output.__enter__()
                return self

            def __exit__(self, *args):
                return self.output.__exit__(*args)

            def __getattr__(self, name):
                return getattr(self.output, name)

            def write(self, payload):
                nonlocal writes
                writes += 1
                if writes == target_write:
                    self.output.write(payload[:max(1, len(payload) // 2)])
                    raise OSError("Injected partial write")
                return self.output.write(payload)

        monkeypatch.setattr(
            persistence.tempfile, "NamedTemporaryFile",
            lambda *args, **kwargs: FailingWriter(original(*args, **kwargs)),
        )
    elif failure.startswith("fsync"):
        original = persistence.os.fsync
        target_sync = 2 if failure == "fsync_backup" else 1
        syncs = 0

        def failing_sync(file_descriptor):
            nonlocal syncs
            syncs += 1
            if syncs == target_sync:
                raise OSError("Injected sync failure")
            return original(file_descriptor)

        monkeypatch.setattr(persistence.os, "fsync", failing_sync)
    else:
        original = persistence.os.replace
        target = persistence.backup_path(destination) if failure == "replace_backup" else destination

        def failing_replace(source, output):
            if Path(output) == target:
                raise OSError("Injected replacement failure")
            return original(source, output)

        monkeypatch.setattr(persistence.os, "replace", failing_replace)


@pytest.mark.parametrize("failure", [
    "write_destination", "fsync_destination", "write_backup", "fsync_backup",
    "replace_backup", "replace_destination",
])
def test_failed_save_preserves_destination_and_leaves_no_temporary_files(tmp_path, monkeypatch, failure):
    destination = tmp_path / "study.json"
    recovery = persistence.backup_path(destination)
    old = b'{"study": "current saved revision"}\n'
    earlier = b'{"study": "earlier saved revision"}\n'
    destination.write_bytes(old)
    recovery.write_bytes(earlier)
    _fail_file_operation(monkeypatch, failure, destination)

    with pytest.raises(OSError, match="Injected"):
        persistence.save_json(destination, {"study": "new revision", "samples": [1.0, 2.0]})

    assert destination.read_bytes() == old
    assert recovery.read_bytes() == (old if failure == "replace_destination" else earlier)
    assert set(tmp_path.iterdir()) == {destination, recovery}


@pytest.mark.parametrize("failure", ["write_destination", "fsync_destination", "replace_destination"])
def test_failed_first_save_does_not_leave_a_partial_file(tmp_path, monkeypatch, failure):
    destination = tmp_path / "new-study.json"
    _fail_file_operation(monkeypatch, failure, destination)

    with pytest.raises(OSError, match="Injected"):
        persistence.save_json(destination, {"study": "first saved revision"})

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("invalid", [object(), float("nan"), float("inf")])
def test_serialization_failure_happens_before_creating_or_changing_files(tmp_path, monkeypatch, existing, invalid):
    destination = tmp_path / "study.json"
    old = b'{"study": "saved"}'
    if existing:
        destination.write_bytes(old)

    def unexpected_staging(*args, **kwargs):
        pytest.fail("Invalid JSON was not rejected before disk staging")

    monkeypatch.setattr(persistence.tempfile, "NamedTemporaryFile", unexpected_staging)
    with pytest.raises(ValueError):
        persistence.save_json(destination, {"measurements": [invalid]})

    if existing:
        assert destination.read_bytes() == old
        assert list(tmp_path.iterdir()) == [destination]
    else:
        assert list(tmp_path.iterdir()) == []


def test_success_preserves_exact_previous_bytes_and_rotates_one_backup(tmp_path):
    destination = tmp_path / "informe-árbol.json"
    old = b'{ "revision": 1, "measurements": [1.234567890123456] }\n'
    destination.write_bytes(old)
    recovery = persistence.backup_path(destination)
    recovery.write_text('{"revision": 0}', encoding="utf-8")
    latest = {"revision": 2, "label": "Árbol", "measurements": [0.000012345678912345]}

    persistence.save_json(destination, latest)

    assert json.loads(destination.read_text(encoding="utf-8")) == latest
    assert recovery.read_bytes() == old
    assert set(tmp_path.iterdir()) == {destination, recovery}


@pytest.mark.parametrize("invalid_bytes", [
    b'{"unfinished":', b'{"duplicate": 1, "duplicate": 2}',
    b'{"measurement": NaN}', b'{"measurement": 1e400}', b'\xff\xfeinvalid',
])
def test_corrupt_destination_cannot_overwrite_valid_recovery_copy(tmp_path, invalid_bytes):
    destination = tmp_path / "report.json"
    recovery = persistence.backup_path(destination)
    destination.write_bytes(invalid_bytes)
    old = b'{"report": "recoverable"}'
    recovery.write_bytes(old)

    persistence.save_json(destination, {"report": "new valid result"})

    assert json.loads(destination.read_text(encoding="utf-8")) == {"report": "new valid result"}
    assert recovery.read_bytes() == old
    assert set(tmp_path.iterdir()) == {destination, recovery}


def _document(kind, revision):
    if kind == "project":
        document = Project(f"Study revision {revision}", id="study-id")
        document.add_tolerance(ToleranceDefinition(
            "Gap", "size", 1.234567890123456, 0.1, 0.2, id="gap",
        ))
        document.study = {"objective": f"Drawing revision {revision}", "seed": "42"}
        return document
    if kind == "bank":
        return DimensionBank({"Spacer": DimensionTemplate("Spacer", revision, 0.1, 0.2, 1.33)})
    signature = FeatureSignature("circle", [1.234567890123456, 2.0, 3.0], [0.0, 0.0, 1.0], 5.0, 16, 10.0)
    document = AnnotationSet(source_file=f"plate-revision-{revision}.step")
    document.add_feature_ref(FeatureReference(signature, label="Hole", id="hole"))
    document.dimension_links.append(DimensionLinkDefinition("Diameter", "hole", "diametral", id="link"))
    return document


def _payload(document):
    if isinstance(document, DimensionBank):
        from dataclasses import asdict
        return {name: asdict(template) for name, template in document.entries.items()}
    return document.to_dict()


@pytest.mark.parametrize("kind", ["project", "bank", "annotations"])
def test_domain_previous_version_round_trip_is_read_only(tmp_path, kind):
    previous = _document(kind, 1)
    latest = _document(kind, 2)
    destination = tmp_path / f"{kind}.json"
    previous.save(destination)
    assert not persistence.backup_path(destination).exists()
    previous_bytes = destination.read_bytes()
    latest.save(destination)
    files_before_recovery = {path.name: path.read_bytes() for path in tmp_path.iterdir()}

    recovered = type(previous).load_previous(destination)

    assert _payload(recovered) == _payload(previous)
    assert _payload(type(previous).load(destination)) == _payload(latest)
    assert persistence.backup_path(destination).read_bytes() == previous_bytes
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == files_before_recovery


@pytest.mark.parametrize("kind", ["project", "bank", "annotations"])
def test_domain_invalid_primary_does_not_displace_valid_previous_version(tmp_path, kind):
    previous = _document(kind, 1)
    destination = tmp_path / f"{kind}.json"
    previous.save(destination)
    _document(kind, 2).save(destination)
    recovery = persistence.backup_path(destination)
    previous_bytes = recovery.read_bytes()
    malformed = _payload(_document(kind, 2))
    if kind == "project":
        malformed["name"] = ""
    elif kind == "bank":
        malformed["Spacer"]["tol_plus"] = -1.0
    else:
        malformed["feature_refs"]["hole"]["signature"]["kind"] = "unsupported-kind"
    destination.write_text(json.dumps(malformed), encoding="utf-8")

    _document(kind, 3).save(destination)

    assert recovery.read_bytes() == previous_bytes
    assert _payload(type(previous).load_previous(destination)) == _payload(previous)
    assert _payload(type(previous).load(destination)) == _payload(_document(kind, 3))


@pytest.mark.parametrize("kind", ["project", "bank", "annotations"])
def test_invalid_previous_version_is_rejected_without_changing_disk(tmp_path, kind):
    document = _document(kind, 1)
    destination = tmp_path / f"{kind}.json"
    document.save(destination)
    recovery = persistence.backup_path(destination)
    recovery.write_text('{"measurement": NaN}', encoding="utf-8")
    files_before_recovery = {path.name: path.read_bytes() for path in tmp_path.iterdir()}

    with pytest.raises(ValueError, match="finite"):
        type(document).load_previous(destination)

    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == files_before_recovery


def test_malformed_annotation_structure_cannot_displace_valid_recovery_copy(tmp_path):
    destination = tmp_path / "annotations.json"
    previous = _document("annotations", 1)
    previous.save(destination)
    _document("annotations", 2).save(destination)
    recovery = persistence.backup_path(destination)
    previous_bytes = recovery.read_bytes()
    destination.write_text("[]", encoding="utf-8")

    _document("annotations", 3).save(destination)

    assert recovery.read_bytes() == previous_bytes
    assert _payload(AnnotationSet.load_previous(destination)) == _payload(previous)
