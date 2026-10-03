"""Atomic JSON saves with one recoverable version, independent of Qt.

Serialize first, stage and flush files beside the destination, then replace.
Only a previous valid JSON document is rotated into the backup. A caller can
also validate its domain schema before replacing an existing good backup.
"""

import os
from pathlib import Path
import tempfile

from .json_data import dumps_strict, loads_strict


def backup_path(path: str | Path) -> Path:
    destination = Path(path)
    return destination.with_name(destination.name + ".bak")


def _remove_temporary(path: Path | None) -> None:
    if path is not None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            # Cleanup must never hide the error that prevented the save.
            pass


def _stage_bytes(destination: Path, payload: bytes) -> Path:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=destination.parent,
            prefix=f".{destination.name}-", suffix=".tmp", delete=False,
        ) as output:
            temporary = Path(output.name)
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        return temporary
    except BaseException:
        _remove_temporary(temporary)
        raise


def save_json(path: str | Path, data, *, previous_validator=None) -> None:
    """Save strict JSON without truncating an existing file on failure.

The old document is retained as ``<filename>.bak`` after validation. If the
destination already contains invalid data, leave the existing backup intact.
Unreadable destinations and backup/write/replace failures abort the save.
No operation that can report a save failure follows destination replacement.

This protects against ordinary write/replace failures. It is not a concurrent
writer lock or a guarantee against every filesystem/power-loss failure.
"""
    payload = dumps_strict(data).encode("utf-8")
    destination = Path(path)
    previous = None
    try:
        existing = destination.read_bytes()
    except FileNotFoundError:
        pass
    else:
        try:
            parsed = loads_strict(existing.decode("utf-8"))
            if previous_validator is not None:
                previous_validator(parsed)
        except (ValueError, TypeError, KeyError, UnicodeError):
            # Do not rotate a malformed file over a valid recovery copy.
            pass
        else:
            previous = existing

    staged_destination = None
    staged_backup = None
    try:
        staged_destination = _stage_bytes(destination, payload)
        if previous is not None:
            recovery = backup_path(destination)
            staged_backup = _stage_bytes(recovery, previous)
            os.replace(staged_backup, recovery)
            staged_backup = None
        os.replace(staged_destination, destination)
        staged_destination = None
    finally:
        _remove_temporary(staged_destination)
        _remove_temporary(staged_backup)
