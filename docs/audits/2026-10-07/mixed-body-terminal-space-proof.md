# Mixed-body terminal word spaces

Scope is actual question prose. No notice or masthead changes are included.
The temporary actual high3 Q21/Q24 experiment translates only 5 / 1
regular-Times ASCII spaces in the terminal source row. It leaves italic and
nonterminal spaces on their existing path.

The source proof reopens the original PDF and proves the complete actual
instruction/body band, every supplied raw row/span/character and canonical
typography. The terminal font has one actual Type0 Identity-H resource,
U+0020 CID/GID 3, explicit PDF width 250, identity CID-to-GID mapping and
the referenced embedded TrueType hmtx advance 512 / 2048. Each selected
space must be nonsynthetic and internal, with its own matching visible
trace, quarter-em bbox and following actual origin advance. No Unicode font
fallback or question selector grants permission.

On nativecell3, the temporary clone improves Q21 body maximum X error from
13.981 px to 2.136 px (terminal 0.787 px), and Q24 from 3.744 px to 1.287 px
(terminal 1.077 px). Y is unchanged. All 27,736 glyph tuples outside the two
terminal rows are exactly identical; both documents have 8 pages and 27,781
visible glyphs. The experiment is not a whole-page quality pass.

Independent review passes two actual-source positives and 36 altered-source,
font-resource and trace cases. Temporary Q21/Q24 public add_run, save,
reopen and resave preserve complete original text, every resolved style and
paragraph margin. Following choices advance 196.373 / 180.013 px; both edited
documents have 9 pages and every reopened page SVG is identical. Reports:

- `tmp/september-audit/mixed-body-terminal-space-ab/report.json`
- `tmp/september-audit/mixed-body-terminal-space-ab/public-independent-c/report.json`
- `tmp/september-audit/mixed-body-terminal-space-ab/public-independent-c/source-proof-report.json`

The product integration keeps the original regular-body maps and Q23
terminal branch intact. Its mixed source branch independently rederives
canonical typography, including width/tracking/sample-count fields. The
producer's complete-text source restyler may consume this source-only map.
A consumer supplies the current paragraph, header and page width; the new
gate then verifies every current native character against the actual source,
all seven language font references, exact native height, bold/italic,
ratio/tracking, relative size/offset, font-space/kerning/symbol modes and
unsupported effects. It rejects unknown controls and empty native runs.
The body-right entrypoint additionally checks all seven font references for
every run. Rejection precedes header or paragraph mutation.

Dedicated product guard and final native/public results are recorded by
`scripts/verify_native_mixed_terminal_source_body_spaces.py`. Fresh product
writer/native/public proof is still required after the runtime is frozen;
the temporary prototype results above do not imply that completion.

The final source/current-native guard run passes 473 checks, including 142
existing body-right entrypoint negative requests. Additional selected-space
cases cover all seven nonspace font references, exact height, effects and
metrics, unknown controls, styled empty runs, duplicate styles, doubled
whitespace and separately forged synthetic flags in only the record or only
the body proof. All rejected entrypoint requests leave the wrapper and header
byte-identical. Reports are under
`tmp/september-exam-matrix/mixed-terminal-source-body-regression/guards-final`.

`scripts/verify_mixed_terminal_source_font_guards.py` additionally passes two
actual-source positives and 28 product-path resource/program/trace negatives.
The original regular-body producer/idempotence and 33 malformed source/native
cases also pass, preserving the 107 / 139 / 164 maps. Q23 still has exactly
one terminal-space cursor.

The actual production source-run restyler additionally passes 45 component
checks (`--producer-only`). One-run and per-character inputs translate exactly
5 / 1 spaces. Their full text and every nonspace resolved style equal the
same source restyler with space translation disabled. Doubled spaces, actual
NBSP and TAB characters receive no translated runs; empty, changed-text and
equation inputs reject without mutation or style allocation. This is a source
restyler component result, not a fresh complete writer or renderer result.

Frozen app files:

| File | SHA256 |
|---|---|
| `app/pdf_source_body_spaces.py` | `53105b545754de8d2ce26cc893d7699d813bf30e6af6d35686bb8e743b2f41ab` |
| `app/pdf_source_question_body.py` | `c9237bab4b1a71a9a5629d73ffcb8e38699f9a271629f03218749d3d0ffae31c` |

The strict native gate currently supports the original source wrap and ordinary
native body styles only. A public edit loses eligibility for source cache
restoration and uses ordinary native paragraph reflow, preserving its run
styles and semantic paragraph margins. It must not refresh provenance from
an edited paragraph or a recalculated metadata digest.

## Isolated nativecell4 result

The fresh production writer produced 8 pages, all 45 questions and source text
preservation 1.0 using the explicitly isolated candidate Pyd SHA256
`84f935f6eb3c98bdd9886d2f9f69ae7c820bde1bfba48495f9162e79d7d0ebb1`.
The product native/source/producer/public suite passes 521 checks; the
unchanged Q23 terminal path passes 46, and the actual font/resource/trace
suite passes 30. Q21/Q24 additions preserve styles, margins and full text;
each reopened/resaved document has identical page SVGs. App hashes remain
frozen. Reports are under `tmp/september-exam-matrix/mixed-terminal-nativecell4`.

The same-runtime historical matrix-c comparison measures Q21 whole-body
maximum X residual 13.981311 → 2.135890 px (terminal 0.787214), and Q24
3.743511 → 1.286755 px (terminal 1.076844). Their Y residuals are exactly
unchanged. Its outside-terminal equality assertion **fails** with 32 glyph
tuple changes, owned by TAB choice rows Q08 (1), Q17 (13), Q42 (9), Q44 (9).
That baseline's caches were generated with nativecell3, whereas the fresh
producer used nativecell4. This comparison cannot establish an isolated
mixed-terminal invariance claim. The failure report is retained unchanged;
nativecell5 qualification uses two fresh same-producer outputs, disabling
only the mixed-terminal branch in the baseline process.

## Nativecell5 fresh producer A/B

Two complete fresh writers use the same frozen app and isolated nativecell5
Pyd `864c06ff8a30a9c15dd60d2042d8cc3ce4a24bb77920965da78aae336914ef88`.
The baseline process disables only `_mixed_terminal_spaces`; the original
regular-body branch remains enabled. Both outputs have 8 pages, 45 questions,
full source text preservation and no full-page/text/math overlays. Each loaded
module/Pyd path, package checksum and measured writer-PDF checksum is recorded.

Q21 whole-body maximum X error is 13.981311 → 2.135890 px and its terminal
row is 0.787214 px. Q24 is 3.743511 → 1.286755 px with terminal 1.076844 px.
Y errors are exactly unchanged (maxima 0.040844 / 0.044848 px). The complete
27,781 visible-glyph Unicode sequence is identical, and all **27,736** glyph
tuples outside the two terminal lines are exactly equal. Unlike the historical
comparison, this supplies the isolated branch invariance proof.

The fresh nativecell5 product/source/producer/public verification passes 521
checks, the unchanged Q23 path passes 46 and the source font/resource/trace
suite passes 30. Q21/Q24 public add/save/reopen/resave preserve complete text,
resolved styles and margins; all reopened page SVGs are exact. App hashes are
stable. Evidence is in `tmp/september-exam-matrix/mixed-terminal-nativecell5`,
especially `measure-worker.json`, `verify-worker.json`, `verified/report.json`,
`old-q23-verified/report.json` and `font-guards/report.json`.
