# I09, I11 and F02 implementation evidence

The user selected I09, I11 and F02, with generic aligned CSV as the first import
format. Implementation is in the primary `tolforge` main working tree based on
`49459f8c688a39c87928e9b2516156bb0977ef17`, alongside the earlier uncommitted
I06/I04/I07 and I05/I12/F01 work. The separate earlier source workspace and
external memory vault are preserved. This is source implementation evidence;
no commit or release is asserted.

## I09: cancellable STEP loading and safe close

The worker checks a thread-safe cancellation event before/after the native read,
while hashing the source and between controllable geometry stages. Generation
tags protect queued stages/progress and terminal results from superseded loads.
The GUI exposes Cancel load, stage text and progress; canceled loads retain the
previous displayed scene. A native operation is allowed to return before
cancellation completes.

Scene changes and project handoff run on the GUI thread without unrestricted
event processing inside the commit. Both worker/thread owners remain retained
until terminal handling and thread completion, including a nonblocking join
check for native teardown. Close disables the window and defers destruction
while ownership remains. A rapid Clear/replacement cannot attach an old result
or overwrite newer status text.

The worker captures SHA256 before and after extraction, with file-identity
checks. A source changing during extraction is rejected. Verified loaded bytes
are handed to the project bridge independently of declared project hashes.

## I11: guided relinking and CAD revision evidence

Inspect offers Review saved feature links and Locate saved CAD source. The panel
lists saved stable IDs, unresolved/ambiguous/matched states, candidates,
heuristic scores/reasons and assignments already occupying a candidate. Manual
assignment checks geometric kind and exclusive occupancy, updates the saved
signature and preserves feature, datum, pattern-member and tolerance IDs.
Missing definitions and saved pattern rows remain available for review.

Relative source paths resolve against the engineering/recovery project anchor;
Save As rebases them while preserving the physical target. Loaded source bytes
are compared with the saved hash. Changed/unverified revisions against a saved
baseline require explicit acceptance before attachment, CAD evaluation or
engineering save. Recovery drafts preserve pending work. Relinking retains raw
inputs and clears the ready datum frame; explicit frame rebuild refreshes actual
pattern coordinates from current geometry at full precision.

Reports retain the comparison at load, verified loaded bytes and separately
hashed referenced bytes at evaluation. Matching recorded hashes alone cannot
claim loaded geometry equivalence. Missing/changed files remain explicit, and
export retains original evidence rather than re-reading source files.

## F02: reviewed generic aligned CSV import

The Qt-independent import service captures UTF-8/BOM CSV bytes once. The review
dialog supports comma/semicolon/tab delimiters, each required field mapped to a
column or constant, source units, optional source feature IDs, external datum
frame/alignment procedure, fitting method and explicit alignment confirmation.
Both source and mapped previews show the first 20 rows; validation checks every
row and reports row/field errors. Acceptance revalidates current dataset
constraints before appending the entire batch. Cancel and invalid imports leave
live data and current reports unchanged.

Every measurement has a stable ID. Imported row ancestry records source row,
external feature ID, import ID/hash/path, units, alignment and fitting method;
the source descriptor records the exact mapping and format. Ancestry survives
editing, save/reopen, raw recovery drafts and report snapshots. Legacy rows gain
manual IDs without fabricated import evidence. Unit/frame relabeling cannot
convert/transform values or admit mixed datasets. Input or ancestry edits
invalidate inspection, scalar and CAD report contexts; derived display results
do not invalidate them.

This format is one feature per row with decimal-point numbers. No vendor export
or customer inspection dataset was supplied. The bounded generic format is
verified with synthetic mapped/canonical CSV fixtures, not qualified as a
particular CMM vendor adapter. Unit conversion, coordinate alignment/fitting,
uncertainty rules and additional GD&T solvers remain outside this selection.

## Verification

Final integrated local verification on 2026-10-03 passed **756 tests**, with
native CAD required, strict markers and no skips:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest tests -q --require-native-cad --strict-markers --junitxml=.tolforge/i09-i11-f02-tests.xml
.\launch.ps1 -SelfCheckJson .tolforge/i09-i11-f02-source-cad-smoke.json -IncludeCad
```

The full suite passed in 39.28 seconds using the local Python 3.10 runtime.
Source/CAD launcher smoke passed GUI/numerical imports, scalar clearance, 24
bundled GD&T SVGs and a generated cylinder STEP round-trip with analytic
recognition. Machine-local XML and smoke JSON remain in ignored `.tolforge/`.

Required native tests exercise real STEP extraction cancellation and real
QThread-to-GUI verified-hash handoff. Controlled viewport tests exercise stale
result suppression, stage/progress delivery, rapid replacement and deferred
close. Domain/GUI tests cover relinking conflicts and revision gates, portable
paths, unresolved rows/IDs, mapped import validation and provenance, cancel,
failure rollback, legacy restoration and combined save/recovery/report export.
Delayed initial-load tests verify that untouched saved projects remain clean
and partial edits made while CAD loads survive. The existing recovery-save
regression now checks a portable relative CAD path and its resolved physical
target. An observed intermittent rapid-replacement teardown abort prompted the
nonblocking join guard; deterministic ownership tests, repeated targeted
replacement checks and the final integrated run passed after that repair.

Hosted workflows, frozen executable/native viewport and clean-machine
qualification were not performed. No source synchronization or release build
is implied. Historical test counts in earlier implementation notes remain dated
evidence rather than being overwritten by this run.
