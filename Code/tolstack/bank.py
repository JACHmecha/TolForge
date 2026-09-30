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
from pathlib import Path

from .models import Dimension
from .json_data import dumps_strict, loads_strict, require_finite_number, require_text


@dataclass
class DimensionTemplate:
    """A dimension's physical attributes, without a sign."""
    name: str
    nominal: float
    tol_plus: float
    tol_minus: float
    cpk: float | None = None

    def __post_init__(self):
        self.validate()

    def validate(self) -> None:
        require_text(self.name, "Dimension name")
        for label in ("nominal", "tol_plus", "tol_minus"):
            require_finite_number(getattr(self, label), f"{self.name}: {label}")
        if self.tol_plus < 0 or self.tol_minus < 0:
            raise ValueError(f"{self.name}: tolerance magnitudes cannot be negative.")
        require_finite_number(self.nominal + self.tol_plus, f"{self.name}: upper bound")
        require_finite_number(self.nominal - self.tol_minus, f"{self.name}: lower bound")
        if self.cpk is not None:
            require_finite_number(self.cpk, f"{self.name}: Cpk")
            if self.cpk <= 0:
                raise ValueError(f"{self.name}: Cpk must be positive.")


@dataclass
class DimensionBank:
    entries: dict = field(default_factory=dict)

    def __post_init__(self):
        self.validate()

    def validate(self) -> None:
        if not isinstance(self.entries, dict):
            raise ValueError("Dimension bank entries must be an object.")
        for name, template in self.entries.items():
            self._validate_entry(name, template)

    @staticmethod
    def _validate_entry(name, template) -> None:
        require_text(name, "Bank entry name")
        if not isinstance(template, DimensionTemplate):
            raise ValueError("Bank entries must be DimensionTemplate objects.")
        template.validate()
        if name != template.name:
            raise ValueError(f"Bank key '{name}' does not match template name '{template.name}'.")

    def add(self, template: DimensionTemplate, overwrite: bool = False):
        """Adds a template to the bank. Raises if the name exists unless overwrite=True."""
        if not isinstance(template, DimensionTemplate):
            raise ValueError("Bank entries must be DimensionTemplate objects.")
        template.validate()
        if not isinstance(self.entries, dict):
            raise ValueError("Dimension bank entries must be an object.")
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
        template = self.entries[name]
        self._validate_entry(name, template)
        return template

    def names(self) -> list:
        """Returns bank entry names, sorted alphabetically."""
        return sorted(self.entries.keys())

    def to_dimension(self, name: str, sign: int = 1) -> Dimension:
        """Builds a Dimension (with the given sign) from a bank template."""
        if type(sign) is not int or sign not in (1, -1):
            raise ValueError(f"sign must be +1 or -1, not {sign}.")
        t = self.get(name)
        return Dimension(
            name=t.name, nominal=t.nominal,
            tol_plus=t.tol_plus, tol_minus=t.tol_minus,
            sign=sign, cpk=t.cpk
        )

    def save(self, path: str):
        """Saves the bank to a JSON file."""
        self.validate()
        data = {name: asdict(t) for name, t in self.entries.items()}
        payload = dumps_strict(data)
        Path(path).write_text(payload, encoding="utf-8")

    @classmethod
    def load(cls, path: str) -> "DimensionBank":
        """Loads a bank from a JSON file."""
        data = loads_strict(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Dimension bank file must be an object.")
        entries = {}
        for name, attrs in data.items():
            if not isinstance(attrs, dict):
                raise ValueError(f"Bank entry '{name}' must be an object.")
            try:
                entries[name] = DimensionTemplate(**attrs)
            except TypeError as exc:
                raise ValueError(f"Invalid bank entry '{name}': {exc}") from exc
        return cls(entries=entries)
