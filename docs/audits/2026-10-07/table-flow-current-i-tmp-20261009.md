# Current I contiguous table flow — TMP qualification

This is a TMP experiment, not an applied product change. It removes only independently proved object-after reserves between consecutive source frames. It keeps every cell's source-derived height, text, style and local layout.

The actual I package is `tmp/september-exam-matrix/basic-english-native5-20261008-i/cases/2027_kice_september_high3__eng_1_32a2ddb4/structured/engine/exports/pdf_layout/20261008_230112_english/english_structured_native.hwpx` (SHA `126da140c5fdecb73878c9caae913c05961bbd8c782912f77dc8e8d2be6ef4d2`). The original PDF is SHA `745d64d94e0719735b88a10802fbbd5053b4982c855199396e58fe2f53b81cf0`; actual producer items are SHA `6c493b8dc7366faee3a474af5ad152f4f8d847818b18e130295d747948d2fb6a`. Installed native5 is SHA `864c06ff8a30a9c15dd60d2042d8cc3ce4a24bb77920965da78aae336914ef88`.

## Observed cause

The helper discovers all 45 source/native owners and selects two complete questions with consecutive table-only paragraphs. The selected questions happen to be Q27/Q28; those numbers are report identifiers, not selectors or permission.

Actual source frame edges touch with zero gap. Both producer and public flow currently reserve an additional 400 HWP units after each table. The public ruled-grid helper also regenerates the owner cache as `table height + 400`, so changing only the producer does not persist after editing. Current canonical position replay reproduces the original serialized paragraph positions exactly.

Cell heights and local text baselines were already accurate. The measured problem is the world position of the whole frame chain. Q28 also inherits displacement from the preceding question. The experiment derives the recovered inter-question gap from actual same-column source frame anchors and current canonical flow; it does not copy an old wrapper or cache height.

## Frozen implementation and permission

`tmp/september-audit/table-flow-current-i/native_contiguous_frame_flow.py` is frozen at SHA `2c5316de4e9753236213084b75945fcb9af9cdeb1f909ca181ba961090c58461`.

The helper rebinds complete actual numbered source bands through the fifth physical choice, current named native owners and native painted semantic segments. It replays actual source columns, frame backgrounds, raw glyphs, text traces, fonts, frame/grid rules, cell dimensions and canonical caches before staging a byte reconstruction. The table-only blank cache is generated from the current native blank document and current writer cache constructor. Saved dummy cache values do not grant permission. Unsupported input returns its exact original package bytes.

The `public_adapter` is an explicit TMP live context derived from those source-proved groups. It checks current paragraph ownership, used style bytes, unchanged prose cells and the grid's source baseline state. It installs scoped flow/grid callbacks only for the verified live table nodes and restores the original callbacks on exit. It is not a serialized source-context contract and does not activate automatically after reopening a document.

## Actual I result

`geometry-ab.json` proves identical 8 pages and 27,781 painted nonspace glyph inventory/order. All glyph X coordinates are unchanged. The two target owners contain 1,428 glyphs; all other 43 owners' 26,353 world glyph tuples remain exact.

| Actual region | Mean source Y error before | After |
| --- | ---: | ---: |
| First question grid | +5.334309 px | +0.000976 px |
| Second question prefix frame | +3.555734 px | +0.009068 px |
| Second question grid | +8.871965 px | −0.008035 px |
| Second question suffix frame | +14.215999 px | +0.002666 px |

Outside the complete target column bands, every page PNG is exact after explicitly excluding 33 actual native section-separator pixels on page 4. The separator follows content height and is outside the requested question fidelity gate. No question glyphs are excluded from the world-coordinate comparison.

Ordinary choice paragraph leading is a separate remaining problem. For example, final-choice mean Y error falls from +15.76850 to +10.43517 px in the first question and from +20.76444 to +6.55111 px in the second. This experiment does not claim complete question alignment.

## Guards and public editing

`guards.json` records 21/21 checks under Python `-O -B`, with input/helper/app/vendor/runtime fingerprints stable. They cover incomplete source choices/frame rows, changed source geometry/column/literal permission, native table dimensions/position, cache origin/height, source-native frame font height/bold, grid baseline state, duplicate styles/owners, unsupported controls and four unsupported live public contexts. Every reconstruction negative returns the exact mutant input bytes; rejected public contexts retain the original callbacks.

`public-utf8/report.json` records six actual public modes: small edit, long growth, restoration, empty content, restoration from empty, and a space boundary. Source transition gaps remain zero after every edit. The long edit grows the grid from 5,593 to 12,775 HWP units and moves to 9 pages. All six reopen/resave pairs have exact SVGs. Both restoration cases recover all original 8 SVG pages exactly. The complete 45 named question texts are checked in each case, with only the intended cell text changed.

The public driver does not independently measure every edited glyph ink bounding box. Initial complete-question native paint is measured; public checks establish grow-only geometry, exact text, cache persistence, reopening and restoration.

## Preserved failures and remaining integration work

The first TMP public serialization failed editor safety because the XML declaration used `utf8` instead of `utf-8`. Failure artifacts remain in `public/failure.json` and `public/failed-section0.xml`; the corrected candidate is SHA `d0f556247a8214979e3f16c0b0c1fecfc2757487791e06ed6580bebf963424e5`. Product files were not changed.

An earlier helper accepted a harmless-looking forged table-owner cache height because position replay alone preserved it. The current helper reconstructs the producer-native blank envelope and the negative now rejects. The old helper hash was `4574a4fcabbc36f26724a5d458594e35305024766ce0cd4916bfac300b60493d`; no old proof is attributed to the frozen current helper.

Before production integration, current J must be rebound independently; I evidence cannot silently inherit J ownership. The TMP native-painted owner routine must be ported or replaced. Non-table prompt/choice raw-versus-native font agreement currently exists as a separate 12-paragraph, zero-mismatch diagnostic, rather than a reconstruction permission guard. The live public source context needs a persisted, revalidated contract. Independent review is pending; no app/vendor/runtime changes are authorized by this audit.

Independent review subsequently closed at **19/25**, so the frozen helper has failed arbitrary-current-context qualification and remains unsuitable for product integration. The original positive and six functional public cases remain valid for their original inputs. Before live-context activation, table width/height, vertical offset, flow properties and wrapper width were not all revalidated. A duplicated table ID also allowed the transition map to remove the terminal grid-to-choice reserve without source permission. The concrete duplicate-ID fixture moved the first choice from 24,849 to 24,449 HWP units and changed the recovered gap from 134 to 534. Saving an actual grid edit without the explicit TMP context reintroduced the 400-unit gap. These findings are preserved separately in `tmp/september-audit/table-flow-independent-2c5316de/final-report.json` and `assessment.md`; neither the helper nor its original reports were changed.

Any later v2 needs unique native owner/paragraph/table IDs, full current outer geometry and flow-envelope checks before activation, and a persisted source-context contract. Initial source geometry improvement alone does not establish those permissions.

Exact original files, SHA values, scopes and minimal commands are recorded in `tmp/september-audit/table-flow-current-i/freeze-manifest.json`.
