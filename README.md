# TolForge

A tool for tolerance stack-up analysis using three methods: Worst Case, RSS
(Root Sum Squares), and Monte Carlo.

Includes a desktop GUI (PySide6) to build a dimension chain and run all
three methods without touching code.

## Structure

```
Code/
├── tolstack/
│   ├── __init__.py     # Public API: Stack, Dimension, StackResult, MonteCarloResult
│   ├── models.py       # Pure data models (no logic)
│   └── stack.py        # Calculation logic (Stack class)
├── examples/
│   └── basic_usage.py  # Runnable console example
├── gui/
│   └── app.py           # Desktop GUI
└── main.py             # Quick entry point (console)
```

## Installation

```bash
git clone https://github.com/JACHmecha/3D-tolerance-stack-up-tool.git
cd 3D-tolerance-stack-up-tool
pip install -r requirements.txt
```

## Usage

### Desktop GUI

```bash
cd Code
python gui/app.py
```

Editable dimension table (name, nominal, tol+, tol-, sign, optional Cpk),
method selector, and Calculate button. Worst Case and RSS show the numeric
summary; Monte Carlo also plots a histogram of the resulting distribution.

**Monte Carlo model per dimension:**
- Empty "Cpk" cell → uniform sampling across the full tolerance range
  (the most pessimistic scenario, doesn't represent a real process).
- "Cpk" cell with a value (e.g. 1.33) → split normal distribution,
  calibrated so the tolerance limit sits at `3 × Cpk` standard deviations
  from nominal.
- "Global Cpk" field next to the Calculate button → applies that Cpk to
  any dimension that doesn't have its own value in the table.

The Monte Carlo result explicitly lists which model was used for each
dimension, so it's never ambiguous which statistical assumption produced
the histogram.

> **Note:** the three tolerance methods produce different bounds from the
> same input stack (Base/Spacer/Bearing below). That spread — Worst Case
> vs. RSS vs. Monte Carlo — is the actual point of doing this kind of
> analysis instead of picking one method by default.

| Worst Case | RSS | Monte Carlo |
|---|---|---|
| ![Worst Case](docs/screenshots/worst_case.png) | ![RSS](docs/screenshots/rss.png) | ![Monte Carlo](docs/screenshots/monte_carlo.png) |

### Console

```bash
cd Code
python main.py
python examples/basic_usage.py
```

### As a library

```python
from tolstack import Stack, Dimension

stack = Stack()
stack.add_dimension(Dimension(name="Base", nominal=25.0, tol_plus=0.10, tol_minus=0.05))
stack.add_dimension(Dimension(
    name="Bearing", nominal=40.0, tol_plus=0.20, tol_minus=0.10, sign=-1, cpk=1.33
))

stack.summary(method="rss")  # or "worst_case" / "monte_carlo"
```

## Migration notes (single script → package)

- `method` in `summary()` is now normalized to lowercase and validated
  against a list of allowed methods, raising `ValueError` if it doesn't
  match (previously: passing `"Monte_Carlo"` with mixed case caused a
  silent `NameError` because `result` was never assigned).
- The usage example moved to `Code/examples/basic_usage.py`, outside the
  library, so `tolstack` can be imported without running example code.
- The original Monte Carlo only supported uniform sampling, which
  implicitly assumes the worst-case process capability. `Dimension` now
  accepts an optional `cpk` to sample from a split normal distribution
  instead of uniform (see the GUI section above for details).

## Known gaps

- `tolstack/models.py` and `tolstack/stack.py` still have docstrings and
  comments in Spanish; `gui/app.py` is already in English. The repo is in
  a mixed-language state until someone decides whether to translate the
  backend too.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
