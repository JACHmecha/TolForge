"""
Dimension bank: a reusable library of dimension templates, so the same
physical dimensions can be pulled into different stack analyses without
retyping their attributes every time.

Sign is deliberately NOT part of the bank. Whether a dimension adds or
subtracts is a property of how it's used within a specific stack chain,
not an intrinsic property of the dimension itself — the same physical
part (e.g. "Bearing") could be +1 in one stack and -1 in a different one.
"""

from dataclasses import dataclass, field, asdict
import json
from pathlib import Path

from .models import Dimension


@dataclass
class DimensionTemplate:
    """A dimension's physical attributes, without a sign."""
    name: str
    nominal: float
    tol_plus: float
    tol_minus: float
    cpk: float | None = None


@dataclass
class DimensionBank:
    entries: dict = field(default_factory=dict)

    def add(self, template: DimensionTemplate, overwrite: bool = False):
        """Adds a template to the bank. Raises if the name exists unless overwrite=True."""
        if template.name in self.entries and not overwrite:
            raise ValueError(
                f"'{template.name}' already exists in the bank. "
                f"Pass overwrite=True to replace it."
            )
        self.entries[template.name] = template

    def remove(self, name: str):
        """Removes a template by name."""
        if name not in self.entries:
            raise KeyError(f"'{name}' not found in the bank.")
        del self.entries[name]

    def get(self, name: str) -> DimensionTemplate:
        if name not in self.entries:
            raise KeyError(f"'{name}' not found in the bank.")
        return self.entries[name]

    def names(self) -> list:
        """Returns bank entry names, sorted alphabetically."""
        return sorted(self.entries.keys())

    def to_dimension(self, name: str, sign: int = 1) -> Dimension:
        """Builds a Dimension (with the given sign) from a bank template."""
        if sign not in (1, -1):
            raise ValueError(f"sign must be +1 or -1, not {sign}.")
        t = self.get(name)
        return Dimension(
            name=t.name, nominal=t.nominal,
            tol_plus=t.tol_plus, tol_minus=t.tol_minus,
            sign=sign, cpk=t.cpk
        )

    def save(self, path: str):
        """Saves the bank to a JSON file."""
        data = {name: asdict(t) for name, t in self.entries.items()}
        Path(path).write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, path: str) -> "DimensionBank":
        """Loads a bank from a JSON file."""
        data = json.loads(Path(path).read_text())
        entries = {name: DimensionTemplate(**attrs) for name, attrs in data.items()}
        return cls(entries=entries)
