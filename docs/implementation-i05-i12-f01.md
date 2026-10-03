# I05, I12 and F01 implementation

These user-selected backlog items extend the primary Git checkout on `main`,
based on `49459f8c688a39c87928e9b2516156bb0977ef17`. They preserve the earlier
I06/I04/I07 working changes. The original source workspace and external memory
vault are separate; no source synchronization, commit or release is implied.

## I05 — Unsaved work and incomplete recovery

Project state fingerprints include domain definitions, raw editor inputs,
persistent IDs, source descriptors and partial datum selections. They exclude
report/status columns and transient previews. The title marks unsaved changes.
New/Open/previous-version/draft recovery/Close offer Save, Discard and Cancel.
Invalid targets are checked first; canceled or failed saves veto replacement.

Recovery drafts have a separate versioned strict-JSON schema and atomic writes.
They retain a validated domain snapshot plus incomplete raw inputs, exact
numeric editor text and unresolved links. No calculated results are restored.
Draft recovery remains unsaved and requires review, source reattachment and
frame reconstruction before evaluation. Normal Project validation remains
unchanged. File-menu manual save/recover complements debounced automatic drafts.
Automatic files live in ignored checkout `.tolforge/drafts` or the frozen
application's per-user data directory. Successful project save/deliberate
discard cleans up associated automatic files, preserving manual drafts.

Close during a STEP read retains the worker/window until completion. Inputs
are disabled after the close decision, preventing edits during deferred close.
Cancel preserves ongoing editing and preview/recovery timers.

## I12 — Evaluation-time report evidence

Scalar, measured inspection and CAD-position reports capture evidence before
numerical evaluation. A common envelope owns a detached JSON snapshot with
report/input IDs, UTC time, schemas, project/study identity, exact inputs,
settings, units, scope, canonical input SHA256, runtime versions and software
revision/dirty state. Export copies existing evidence and result summaries.
Mutable caller inputs, results or a later source-file edit cannot rewrite an
already-exported report identity.

Referenced files have evaluation-time hashes or explicit missing/unreadable/
unspecified-path status. CSV descriptors preserve their import digest and show
whether current file bytes match those used during import. Human drawing
references retain explicit unavailable hashes. Exact submitted measurements
and effective per-control inputs both remain available in inspection reports.
CAD reports retain actual frame vectors, datum assignments and control values;
a referenced STEP hash alone does not verify the revision of loaded geometry.
No load-time CAD revision equivalence is claimed by these source hashes.

Numerical source-file hashes identify available source bytes; frozen source
manifests can be unavailable and are distinct from executable build evidence.
Changing scalar acceptance bounds creates new report/snapshot IDs and a new
digest while retaining the captured sources and original result-evaluation
time. Existing samples are reassessed without resampling.

## F01 — Requested drawing controls and coverage

The Study inventory records stable control ID, balloon, drawing/revision,
characteristic, specification, datum references and measured-feature link.
Position uses a finite nonnegative diametral limit; size uses positive ordered
`minimum:maximum`. Unsupported callouts retain their descriptive specification.
Definitions persist in the optional schema-1 Study block; statuses do not.

Each supported control uses its own specification and disposition, even when
multiple controls reference the same measurement. Position material-condition
bonus still uses the row's size definition. Missing links and missing/differing
position datum references remain unevaluated. Unsupported characteristics are
explicitly counted. Every requested control appears in the report alongside
evaluated/requested, pass/fail and gap counts. Coverage applies only to the
recorded inventory; unsupported/gap controls never imply complete conformance.
An empty inventory retains the older combined size/position row behavior with
drawing coverage unknown.

## Verification

The final local offscreen suite passed **642 tests**, with
`--require-native-cad --strict-markers` and no skips. It ran in the installed
Python 3.10 source environment. The checkout-relative launcher smoke returned
`status: ok`, `frozen: false`, successful GUI/numerical imports, scalar clearance,
all 24 bundled SVGs and a cylinder STEP round-trip with analytic recognition.
The command was `./launch.ps1 -SelfCheckJson
.tolforge/i05-i12-f01-source-smoke.json -IncludeCad`; the report is private local
verification output, outside source control.

Tests cover every Save/Discard/Cancel boundary, failed saves,
raw recovery and identity/precision, source reattachment, worker close,
independent control limits, alignment gaps, unsupported profile coverage,
source mutations during evaluation and immutable export evidence.

Hosted CI, frozen builds, native viewport interaction and clean-machine package
qualification are separate checks. No measured datum fitting, general form/
orientation solver, uncertainty rule, full drawing assessment or Eclipse
report export is added by these items.
