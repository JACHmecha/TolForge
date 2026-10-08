# I08 — Reproducible Windows profiles and executable qualification

The user selected I08 on 2026-10-08. Implementation is in the uncommitted
primary working tree based on main `7745e2bf230468e80ab9e2d9ee32f51df281ed3f`.
The preserved earlier source and external memory vault were not synchronized.

## Implemented boundary

- Windows x64 Python 3.12.15, complete SHA256-locked desktop/build/test archives,
  official source-commit/archive pin for compas_occ 1.5.0 and explicit native
  Conda archives for OCC/OCCT 7.9.3 `novtk`. Source Python 3.10+ remains supported.
- Exact environment/version/origin checks before building, OCC PE import closure
  from the selected interpreter prefix, DLL/extension SHA256 evidence and
  embedded build metadata. No workstation search paths supply packaged CAD.
- Windows-owned ICU selection before Qt imports, including build subprocesses.
  The pinned Conda environment exposed an ICU alias/export incompatibility with
  Qt; the fix preserves installed native files and records selected paths.
- Separate scalar/CAD executables, fresh build staging, profile-preserving
  publication, source revision/dirty state/per-file and aggregate hashes,
  dependency install manifests, strict tests and recursive artifact checksums.
- Frozen exact-profile checks, scalar exclusion of optional OCC, native closure
  hash validation, all loaded DLL/PYD path/hash inventory and rejection of
  external library borrowing. Source runtime precedence remains unchanged.
- A narrow exception records the injected Windows Defender `MpOAV.dll` only
  from the OS-resolved Defender directory after offline Windows trust and
  Microsoft publisher verification. Its path, hash and signer remain evidence;
  arbitrary external CAD/Qt/application libraries still fail qualification.
- Cylinder, planar box and cone STEP round-trips through the application worker.
  Planes/cylinders are recognized analytically; conical surfaces remain `other`
  in the application, with explicit meshing/round-trip evidence. I08 adds no
  conformance solver or new supported drawing control.
- True production Qt/OpenGL drawing, GPU picking and camera checks, a hashed
  screenshot and driver evidence. Persistent STEP fixtures can be replayed.
  Offscreen/minimal platforms cannot produce native viewport qualification.
- PowerShell-only portable target installation/check: verify package hashes,
  detach executable, isolate user configuration/environment and compare exact
  embedded provenance and executable hashes. CAD requires its native viewport.
- Release matrix builds both profiles; separate fresh Windows jobs consume
  artifacts only. Both target profiles must qualify before release upload.
  Required source-CAD CI shares the same dependency locks.

## Evidence recorded during implementation

The existing Python 3.10/OCC 7.9.0 source environment passed 778 integrated tests
with required native CAD, strict markers and zero skips. Fourteen subsequently
added build-helper tests passed separately. Runtime/verifier focused checks
also passed. The source native viewport rendered a three-face cylinder on the
local NVIDIA RTX 4060 Laptop GPU/OpenGL 3.3, with geometry, picking and camera
checks passing and saved framebuffer evidence.

Final builds used the locked Python 3.12.15 environments. The CAD suite passed
**807 tests**, native CAD required, with zero skips. The scalar suite passed
**799 tests**, with the eight native-CAD tests explicitly deselected. Both
executables passed their frozen profile smoke checks with workstation runtime
overrides removed. The CAD executable verified all **385** bundled native
DLL/extension hashes and three generated STEP round-trips.

Both detached target checks passed with `machine_scope=isolated-workstation`.
The CAD target used the real Windows Qt/OpenGL 3.3 Core context on the NVIDIA
RTX 4060 Laptop GPU, driver 610.91. It drew three cylinder face objects,
changed 190,334 framebuffer pixels and passed GPU picking and camera controls.
The saved screenshot was visually inspected. Cylinder and box surfaces were
recognized analytically; the cone round-trip retains its existing `other`
surface classification. These checks do not extend solver coverage.

| Profile | Executable SHA256 |
|---|---|
| scalar | `a28f3bba153147628d08364f619187109287200cb363a157ffe7f091ce090ac8` |
| cad | `c39750e5d19ec27d23ee8473d4392d8ef4cbcc2f06d0a0a95a7c18fd24191ac7` |

Both embedded build identities describe source snapshot
`4a9d3e545053890ca419c0efea8f461d276f0638a338f82adf97893d7adb6570`,
with full per-file provenance in each package. After those builds, the separate
PowerShell verifier gained native-sidecar-to-build hash binding and its own
SHA256 report field; all **six verifier regressions passed**. The release
workflow also adds the exact verifier and recomputes checksums after appending
fresh-target evidence. These verifier, verifier-test, workflow and documentation
updates do not change the frozen application.
The final target reports identify verifier
`25659fbb1611eb180a9db1dd193d65dae3989c588b0cb4b850ebb98e4b28a8a8`.

Evidence lives in `dist/scalar` and `dist/cad`: original build/test/frozen
records, plus `target-qualification/` with detached reports, the exact verifier,
its regression result and CAD screenshot/STEP fixtures. The recursive package
`SHA256.json` also covers the appended target evidence. Use these identities
rather than treating HEAD alone as this dirty implementation's identity.

## Remaining qualification boundary

This workstation has no Windows Sandbox. A local detached launch records an
isolated-workstation result; it cannot establish fresh-machine installation.
Hosted build and fresh-target workflows were configured but not dispatched by
this implementation. A clean Windows result requires their actual successful
run (or an equivalent reviewed fresh Windows target with the portable verifier).
Native graphics failures stop that qualification rather than falling back to
headless success. No release, merge or clean-machine pass is implied.

The build recipes reproduce dependency identities. They do not promise
byte-for-byte identical executables across build machines. Every actual artifact
has its own SHA256 and captured evidence. The distribution is a portable
Windows executable; no MSI installation or signing claim is made.
