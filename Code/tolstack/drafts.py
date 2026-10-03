"""Recovery-only envelopes for incomplete editor state, separate from Project.

A draft contains a validated domain snapshot and raw editor strings. It has no
analysis results, no executable objects and no relaxed engineering validation.
Loading a draft never evaluates or writes an engineering project.
"""

from copy import deepcopy
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
from uuid import uuid4

from .json_data import loads_strict, validate_json_value, require_text
from .persistence import save_json
from .project import Project

DRAFT_KIND = "tolforge-recovery-draft"
DRAFT_SCHEMA_VERSION = 1
TABLE_WIDTHS = {"stack": 6, "pattern": 9, "inspection": 11, "drawing_controls": 8}
ACTIVE_IDS = ("_active_part_id", "_active_occurrence_id", "_active_datum_system_id", "_active_position_control_id")
CELL_ROLES = {"356", "457", "458", "467", "468", "469", "470", "471", "477"}


def draft_directory() -> Path:
    if getattr(sys, "frozen", False):
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return local / "TolForge" / "drafts"
    return Path(__file__).resolve().parents[2] / ".tolforge" / "drafts"


def new_draft_id() -> str:
    return str(uuid4())


def create_draft(project, ui, context, *, draft_id=None) -> dict:
    data = {
        "kind": DRAFT_KIND, "draft_schema_version": DRAFT_SCHEMA_VERSION,
        "draft_id": draft_id or new_draft_id(),
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "project_snapshot": deepcopy(project), "ui": deepcopy(ui), "context": deepcopy(context),
    }
    validate_draft(data)
    return data


def validate_draft(data) -> None:
    validate_json_value(data, "Recovery draft")
    if not isinstance(data, dict) or data.get("kind") != DRAFT_KIND:
        raise ValueError("This file is not a TolForge recovery draft.")
    if type(data.get("draft_schema_version")) is not int or data["draft_schema_version"] != DRAFT_SCHEMA_VERSION:
        raise ValueError("Unsupported recovery draft version.")
    require_text(data.get("draft_id"), "Draft ID")
    require_text(data.get("saved_at"), "Draft creation time")
    Project.from_dict(data.get("project_snapshot"))
    context, ui = data.get("context"), data.get("ui")
    if not isinstance(context, dict) or not isinstance(ui, dict):
        raise ValueError("Draft context and editor state must be objects.")
    for field in ("project_path", "recovered_from", *ACTIVE_IDS):
        if context.get(field) is not None and not isinstance(context[field], str):
            raise ValueError(f"Draft {field} must be text or null.")
    widgets, tables = ui.get("widgets"), ui.get("tables")
    if not isinstance(widgets, dict) or not isinstance(tables, dict):
        raise ValueError("Draft widgets and tables must be objects.")
    for name, state in widgets.items():
        if not isinstance(state, dict) or state.get("kind") not in ("text", "choice", "check", "spin"):
            raise ValueError(f"Invalid draft widget {name}.")
        if state["kind"] == "check":
            if type(state.get("value")) is not bool:
                raise ValueError(f"Draft checkbox {name} must be boolean.")
        elif not isinstance(state.get("text"), str):
            raise ValueError(f"Draft widget {name} must contain raw text.")
        if state["kind"] == "spin" and (type(state.get("value")) not in (float, int)):
            raise ValueError(f"Draft spin editor {name} needs its last numeric value.")
    if set(tables) != set(TABLE_WIDTHS):
        raise ValueError("Draft tables do not match the supported editor schema.")
    for name, width in TABLE_WIDTHS.items():
        if not isinstance(tables[name], list):
            raise ValueError(f"Draft {name} rows must be a list.")
        for row in tables[name]:
            if not isinstance(row, list) or len(row) != width:
                raise ValueError(f"Draft {name} row must have {width} input cells.")
            for cell in row:
                if not isinstance(cell, dict) or not isinstance(cell.get("text"), str):
                    raise ValueError("Draft cells must contain raw text.")
                roles = cell.get("roles", {})
                if not isinstance(roles, dict) or not set(roles).issubset(CELL_ROLES):
                    raise ValueError("Draft cell metadata contains unsupported roles.")
                for role, value in roles.items():
                    if role == "356":
                        if value is not None and (not isinstance(value, dict)
                                or not isinstance(value.get("feature_id"), str)
                                or value.get("mode") not in ("normal_offset", "diametral", "positional")):
                            raise ValueError("Invalid draft stack feature link.")
                    elif role == "477":
                        if value is not None and (not isinstance(value, dict)
                                or not isinstance(value.get("id"), str) or not value["id"].strip()):
                            raise ValueError("Draft measurement metadata needs a stable identity.")
                    elif value is not None and not isinstance(value, str):
                        raise ValueError("Draft persistent IDs must be strings.")
    datums = ui.get("datums")
    if not isinstance(datums, dict) or set(datums) != {"Primary", "Secondary", "Tertiary"}:
        raise ValueError("Draft must retain all three datum slots.")
    for entry in datums.values():
        if entry is None:
            continue
        if not isinstance(entry, dict) or entry.get("kind", "plane") not in ("plane", "axis"):
            raise ValueError("Invalid draft datum selection.")
        for field in ("point", "direction"):
            values = entry.get(field)
            if not isinstance(values, list) or len(values) != 3 or any(type(v) not in (int, float) for v in values):
                raise ValueError(f"Draft datum {field} must contain three finite coordinates.")
        if not isinstance(entry.get("description"), str):
            raise ValueError("Draft datum description must be text.")
        for field in ("feature_id", "datum_ref_id"):
            if entry.get(field) is not None and not isinstance(entry[field], str):
                raise ValueError(f"Draft datum {field} must be text.")
    source_files = ui.get("inspection_source_files", [])
    if not isinstance(source_files, list) or any(not isinstance(value, dict) for value in source_files):
        raise ValueError("Draft inspection source descriptors must be objects.")


def save_draft(path, data) -> None:
    validate_draft(data)
    save_json(path, data, previous_validator=validate_draft)


def load_draft(path) -> dict:
    data = loads_strict(Path(path).read_text(encoding="utf-8"))
    validate_draft(data)
    return data


def available_drafts() -> list[Path]:
    directory = draft_directory()
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.recovery.json"), key=lambda path: path.stat().st_mtime, reverse=True)
