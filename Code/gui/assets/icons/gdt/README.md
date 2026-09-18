# GD&T icon library

Monochrome SVG symbols for TolForge's geometric characteristic and modifier
controls. Every icon uses a `64 x 64` view box, transparent background, rounded
line ends, and the same stroke weight so they can be presented together in
menus, toolbars, and feature-control-frame editors.

Use the stable IDs in `manifest.json`; UI code should not infer a symbol's
meaning from its filename. The `rfs` icon uses the traditional circled `S`
symbol. Current ASME practice normally indicates RFS by omitting a material
condition modifier, so the UI should treat this asset as an explanatory or
legacy option rather than automatically inserting it into a callout.

These are original, code-native vector drawings distributed under TolForge's
Apache-2.0 license. They are UI assets, not a substitute for checking a
production drawing against the applicable ASME Y14.5 or ISO GPS standard.
