---
type: recommendation-list
project_id: tolforge
status: proposed
implemented_items: [UI01, UI02, UI03, UI04, UI05]
proposed_items: [UI06, UI07, UI08, UI09, UI10, UI11, UI12]
assessment_date: 2026-10-09
scope: GUI layout and aesthetics
---

# GUI layout and aesthetics recommendations

Items are ordered by visual impact. The user selected **UI01–UI05** for implementation on 2026-10-09; these are now implemented in the local source. **UI06–UI12 remain proposals.** Effort is a relative estimate: **small** means a contained presentation change; **medium** means coordinating several layouts or visual states. See [implementation and verification](implementation-gui-high-priority-2026-10-09.md) for the delivered scope.

The recommended direction is to refine the existing graphite surfaces, blue accents, TolForge branding, and Qt desktop layout. The assessment covers the current working tree on `main`, based on revision `4d5cd908237ab472c4066668b92e6f167052d33f`, including uncommitted GUI changes. Fresh offscreen renders at 1300 × 800 and 1024 × 768 were reviewed with Windows fonts loaded and the CAD renderer disabled. This establishes panel layout evidence; it does not establish the appearance of a loaded native CAD scene or behavior at other display scales.

The October 3 memory notes describe an earlier source snapshot. Their clean-source and outstanding-work statements are not used as current GUI evidence. The broader September 30 backlog remains separate; this list adds no engineering capability, calculation, architecture, performance, persistence, or packaging work.

1. **UI01 — Make forms fit the workspace pane.** Priority: **high**. Effort: **medium**. Status: **implemented in source**.

   Projected interference currently clips Cpk fields, measured-value buttons, and units controls at the default 450 px pane width, even in a 1300 × 800 window. Reflow each tolerance card into two rows or a compact labeled grid; allow Mode and Units to stack at narrow widths. Size wrapped explanatory text to the available pane width. **Complete when:** every form label, field, and button fits without horizontal page scrolling at both reviewed window sizes. Horizontal scrolling may remain inside wide tables. Evidence: `Code/gui/app.py:421`, `:449`, `:465`, `:1023`; fresh projected-interference render.

2. **UI02 — Give tables and results more horizontal room.** Priority: **high**. Effort: **medium**. Status: **implemented in source**.

   The initial split assigns 450 px to every workspace while the CAD viewport occupies most of the window. Keep the existing draggable divider and give table-heavy Study, Stack, and GD&T pages a wider presentation; let Results expand when its chart or summary needs room. Use layout sizes that still keep the viewport useful when geometry is relevant. **Complete when:** core table columns and result labels have a readable default presentation, and either pane can be resized without clipped form controls. Evidence: `Code/gui/app.py:1015`, `:1020`, `:1023`; fresh Stack and Results renders.

3. **UI03 — Make results visually scannable.** Priority: **high**. Effort: **medium**. Status: **implemented in source**.

   Stack results currently appear as one small monospace block beneath a tall settings card. Present the response name as a heading, place nominal/range/tolerance values in aligned rows, emphasize the existing fit or acceptance outcome, and place contributor details below in quieter text. Apply a shared caption/value alignment to Measure, GD&T, and projected-interference summaries. Preserve all values, units, assumptions, and distinctions between reported outcomes. **Complete when:** the main outcome and range are immediately identifiable, values align, and long details wrap cleanly. Evidence: `Code/gui/app.py:286`, `:352`, `:533`, `:752`; `Code/gui/analysis_mixin.py:239`; fresh populated Results render.

4. **UI04 — Give Study clear visual sections.** Priority: **high**. Effort: **medium**. Status: **implemented in source**.

   Study places references, confirmations, explanations, and two wide tables in one long column; its section labels have little visual distinction. Group the existing content under consistent headings for references, alignment, drawing controls, measurements, and results. Use the same page padding and section rhythm as the other workspaces, with muted supporting text and wrapping confirmation labels. **Complete when:** section boundaries are apparent at a glance, and the first table is reached with less visual clutter while all scope statements remain available. Evidence: `Code/gui/study_mixin.py:27`, `:41`, `:63`, `:90`, `:115`; `Code/gui/app.py:1027`; fresh Study render.

5. **UI05 — Make every table look like part of the same application.** Priority: **high**. Effort: **medium**. Status: **implemented in source**.

   Stack already uses alternating fills, restrained grid treatment, and 36 px rows; other tables use different local defaults. Standardize row height, header padding, selection treatment, and numeric alignment across Stack, Study, GD&T, import, and relinking tables. Bound long text-column widths and reserve table-level scrolling for genuinely wide data. **Complete when:** tables share one visual treatment, signs and units remain legible, and long feature names do not stretch the entire page. Evidence: `Code/gui/app.py:181`; `Code/gui/study_mixin.py:73`, `:91`, `:166`, `:208`; `Code/gui/theme.py:223`.

6. **UI06 — Fit long navigation captions within the rail.** Priority: **medium**. Effort: **small**.

   The 144 px rail cannot fully show “Projected interference” at the reviewed default size. Give that caption a deliberate two-line treatment or a shorter rail label while retaining the full workspace title. Match its alignment and active-state treatment to the other items; allow the rail to accommodate enlarged text. Retain the existing logo. **Complete when:** every navigation caption is fully readable at normal and enlarged text sizes, with consistent spacing and no clipped lettering. Evidence: `Code/gui/app.py:783`, `:821`; fresh projected-interference render.

7. **UI07 — Standardize typography and spacing.** Priority: **medium**. Effort: **small**.

   The theme defines 20 px page headings and 12 px body text, while individual pages add their own bold, 16 px, and monospace treatments. Establish consistent page-heading, section-heading, body, hint, and numeric-value styles. Use a small spacing scale, such as 8/12/16/24 logical pixels, for related controls, cards, and section breaks. **Complete when:** headings communicate a clear hierarchy and corresponding sections align across workspaces; enlarged text retains readable spacing. Evidence: `Code/gui/theme.py:41`, `:52`; `Code/gui/app.py:110`, `:286`, `:857`, `:1027`; `Code/gui/study_mixin.py:63`.

8. **UI08 — Apply one action-button hierarchy.** Priority: **medium**. Effort: **small**.

    Analyze and projected-interference Run use the primary blue style, while Study Evaluate resembles adjacent export and editing actions. Apply the existing primary treatment to each section's main action, use quieter secondary buttons, and keep remove/clear actions visually distinct without making them dominate. Standardize action-row spacing and button heights. **Complete when:** the principal action is easy to spot on every page, and long captions remain readable within their rows. Evidence: `Code/gui/theme.py:178`; `Code/gui/app.py:522`, `:980`; `Code/gui/study_mixin.py:98`, `:107`.

9. **UI09 — Reduce scrolling in projected interference.** Priority: **medium**. Effort: **medium**.

   Four tolerance cards and explanatory text occupy almost the entire first screen; the nominal preview starts near the bottom and the run controls follow it. Compact the existing input groups, place the simulation action before the large preview, and use a side-by-side input/preview arrangement when the pane is wide enough. Give secondary settings and explanatory notes less visual weight. **Complete when:** the primary action is reachable without scrolling through the preview, and inputs, nominal geometry, and results have clear visual boundaries. Evidence: `Code/gui/app.py:439`, `:449`, `:495`, `:498`; `Code/gui/projected_preview.py:24`; fresh projected-interference render.

10. **UI10 — Polish chart guides and preview legends.** Priority: **medium**. Effort: **small**.

    Keep the existing dark charts. Label acceptance-boundary lines directly and distinguish them from histogram bars with consistent line styles. Present cross-section legends with matching color swatches and dashed-line samples, and separate nominal measurements from pan/zoom instructions. Keep existing geometry, datum, sign, and result meanings distinct. **Complete when:** legends visibly match the rendered marks, lower and upper bounds are identifiable, and chart labels remain readable in the default pane. Evidence: `Code/gui/analysis_mixin.py:292`; `Code/gui/projected_preview.py:128`, `:144`; `Code/gui/theme.py:348`. This item is source-derived; native CAD appearance was not assessed.

11. **UI11 — Improve dialog composition on laptop screens.** Priority: **medium**. Effort: **medium**.

    CSV import starts at 1050 × 820 and feature relinking at 1040 × 680. Size dialogs against available screen space, retain an always-visible action footer, use clear section headings, and let tables share flexible space. Keep source paths and hashes selectable and visually bounded so they cannot stretch the dialog. **Complete when:** the full frame and footer fit a 1366 × 768 display, content scrolls within the dialog, and the same layout remains readable at enlarged display scales. Evidence: `Code/gui/inspection_import_dialog.py:18`, `:33`, `:65`, `:94`, `:98`; `Code/gui/feature_relinking.py:21`, `:23`, `:53`. This item is based on source sizing; these dialogs were not freshly rendered.

12. **UI12 — Finish control glyphs and scrollbar styling.** Priority: **polish**. Effort: **small**.

    Fresh renders show checked boxes as filled squares and spinner/drop-down areas with weak visual cues. Provide clearly visible checkmarks, arrows, hover states, and focus outlines that match the dark theme. Give horizontal scrollbars the same restrained treatment as the already-styled vertical scrollbars. **Complete when:** checked, unchecked, enabled, disabled, focused, and hovered states remain visually distinct, including at enlarged display scales. Evidence: `Code/gui/theme.py:200`, `:212`, `:265`, `:310`; fresh Stack, Study, and Results renders. Confirm glyph appearance in a normal desktop launch before selecting the exact styling fix.
