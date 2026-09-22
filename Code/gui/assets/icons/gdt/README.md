# GD&T icon library

[Documentation home](../../../../../README.md)

The library contains 24 monochrome SVG symbols, each with a `0 0 64 64` view
box and transparent background. They share stroke weight and rounded line ends
for use in menus, toolbars, and feature-control-frame editors.

## Manifest and usage

`manifest.json` schema version 1 provides each icon's stable `id`, display
`label`, `category`, and `file`. Resolve by ID; do not derive filenames by
concatenating IDs (for example, `circular_runout` uses `circular-runout.svg`).
Categories are form, profile, orientation, location, runout, zone, modifier,
and datum.

Example with `Code` on `PYTHONPATH` or an installed package:

```python
import json
from importlib.resources import files

root = files("gui").joinpath("assets", "icons", "gdt")
manifest = json.loads(root.joinpath("manifest.json").read_text(encoding="utf-8"))
entry = next(icon for icon in manifest["icons"] if icon["id"] == "position")
svg = root.joinpath(entry["file"]).read_text(encoding="utf-8")
```

Preserve existing IDs when editing assets. Keep the manifest and files in sync;
`tests/test_icon_assets.py` checks their consistency. Both `setup.py` package
data and `TolForge.spec` include this directory; verify packaged rendering when
changing resource loading.

The `rfs` asset is a circled S for explanatory/legacy display; it should not be
automatically inserted into every callout. Asset availability does not mean
TolForge implements a numerical solver for that characteristic. See
[calculation scope](../../../../../docs/gdt-semantics.md).

These original vector drawings use the repository's Apache-2.0 license. Drawing
interpretation and symbol use must follow the requirements of the drawing;
this asset collection is not a standards reference.
