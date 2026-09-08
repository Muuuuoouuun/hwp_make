# Premium Studio — three-view design QA

final result: passed

Verified 2026-09-07–08, Windows, local browser app at http://127.0.0.1:8791/.
Scope: integrate the three selected directions into one existing, authenticated editor. The user selected all three for different situations; this is an integrated implementation, not a pixel-exact reproduction of three incompatible navigation shells.

## Visual truth and evidence

Source directory: C:/Users/aaaha/.codex/generated_images/01a07ae5-d15e-7ae1-9612-03f60c04ed30/
- Edit: exec-06fd1eee-30ab-47dc-8871-5e16e5d2a965.png
- Paper: exec-792ee0d5-7102-460c-8349-d90e4404bd6f.png
- Order: exec-f32f3fd3-53ab-4400-978a-e8c73d874437.png

Implementation screenshot directory: C:/Users/aaaha/.codex/visualizations/2026/09/07/01a07ae5-d15e-7ae1-9612-03f60c04ed30/
- studio-edit.png, studio-paper.png, studio-order.png
- studio-paper-detail.png (100% paper zoom)
- studio-mobile-edit.png, studio-mobile-paper.png, studio-mobile-order.png
- studio-mobile-menu.png, studio-tablet-order.png

Source images are 1487 × 1058 pixels. Desktop captures are 1440 × 1024 pixels / CSS viewport, DPR 1. Their aspect ratios differ by less than 0.1%; full compositions were compared proportionally, not with a pixel-difference claim. Mobile is 390 × 844, tablet 900 × 900, DPR 1. Temporary viewport overrides are reset after testing.

State: local test account, five synthetic math questions, original numbers 27/18/12/33/41, sequential output 1–5, first question selected. Desktop paper uses the existing 평가원 수학 template. Reference question text differs; matching business meaning and output-number hierarchy is the comparison basis. No production data was used.

All three source images and corresponding rendered captures were opened together in the same comparison input. Paper typography was additionally compared with the source and a full screenshot at 100% paper zoom in the same input. An initial clipped screenshot from the browser adapter was unsuitable and replaced with the full 100% capture; no conclusions rely on that discarded capture.

## Findings and comparison history

No remaining actionable P0/P1/P2 findings in the implemented scope.

- P2, edit: the initial choices field cut off the fifth choice. Increased its height to 180px; desktop studio-edit.png shows all five. Longer lists remain editable by scrolling.
- P2, paper: legacy responsive sizing overrode the new paper canvas and made fit inconsistent. Set a stable 720px paper base and fit against both stage dimensions. studio-paper.png shows the portrait sheet, and studio-paper-detail.png verifies readable content at 100%. Small screens retain deliberate canvas scrolling and zoom.
- P2, order: the initial list repeated output mapping in small text, weakening the reference's number hierarchy. Added a separate 26px output-number anchor and retained original-number metadata. studio-order.png shows distinct 01–05 anchors and matching settings.
- P2, mobile: the actual render action could be hidden in the compact header. Move the same action into More on narrow screens. Existing mobile CSS also hid the shortcut label; added a scoped override. Post-fix studio-mobile-menu.png shows HWPX 렌더 보기 and 단축키.
- P2, copy: the inherited paper caption described a list rather than the new composition preview. Replaced it with an explicit estimate caption; the final paper captures show the corrected wording. Empty order copy now points to 자료 추가.
- Functional blocker found during browser validation: a page-less question saved once, then failed with HTTP 422 because storage changed null source_page to an empty string. Preserve nullable storage and normalize legacy empty values in the editor payload. Browser save, view transition, real export, and repeated-save API regression now pass.

## Required fidelity surfaces

- Typography: retain the app's existing Korean sans UI and serif math content. Strong title, large output numbers, restrained metadata, readable line heights. Paper detail at 100% is readable. The mock's individual choice rows remain the existing multiline editable field; changing the question schema/editor is outside this presentation change.
- Spacing/layout: shared top navigation and title bar, 280px desktop question navigation, centered editing column, paper canvas, 340px order inspector. The order view deliberately uses flat separators rather than repeated outlined cards. Header/footer actions stay reachable at desktop, tablet and mobile sizes; root width equals viewport width in tested responsive states.
- Colors/tokens: white surfaces, pale gray canvas, subtle separators, indigo selection/action color. Existing HWP Make brand mark and icon set retained. No decorative imagery or substitute artwork added.
- Image/asset quality: no new raster assets are needed by these views. The original app brand and mathematical toolbar remain live controls. The paper is real DOM content, not a mockup image. Uploaded problem images/tables are rendered from existing records; this session's visual fixture contains text questions only.
- Copy/content: 편집 / 시험지 / 순서 explain the three tasks. Advanced metadata, recognition details and AI tools use disclosures; source import and output controls use existing dialogs. The paper view explicitly says its layout is estimated. Local account/billing disclosure remains available.

Expected integration differences: one shared navigation instead of three separate mock navigation systems; a stable portrait paper at fit zoom rather than the mock's shorter page; existing math editing controls, template metadata and output actions. These preserve actual app behavior. The paper DOM uses a simple continuous column flow and ordinary choice markers; it does not reproduce final HWPX pagination or equation typesetting.

## Validation

- Browser: edited a question and switched to paper; confirmed saved text; restored it. Changed starting number to 21 and reordered, confirmed 21–25 in navigation and paper. Restored fixture to 1–5.
- Browser: real HWPX generation completed with download status; real renderer opened one page. The existing renderer warns that multicolumn layout/page count can differ in Hancom.
- Browser: three views, source dialog, settings dialog, mobile More menu, tablet layout, 100% zoom and fit. Reload starts at basic file input; explicitly reopening previous work restores the last view and saved basket/number policy. Title/template are not newly persisted across reload.
- Latest browser console error log: empty.
- Nine frontend checks passed: workbench, premium, progressive entry, accessibility, studio recovery, new studio views, layout, conversion behavior, simple converter.
- Premium API check passed, including repeated page-less saves, real HWPX/DOCX content, numbering parity and source preservation. Optional preview renderer is stubbed in that automated check; actual browser render was separately exercised.
- JavaScript syntax and git diff whitespace checks passed.

## Remaining limits / follow-up polish

P3: consider a dedicated row editor for choices and a template-aware paginated composition preview in a later change. Existing HWPX renderer and export are the output checks today. New typography was verified on this Windows installation; other operating-system font fallbacks and very long image/table-heavy documents were not visually sampled here.

Implementation checklist: shared view state complete; save boundary and failure retention complete; responsive controls complete; real output checks complete; source/render visual comparison complete.
