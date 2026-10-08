# Q27 horizontal cache diagnosis

The initial read-only diagnosis uses the actual September High2 English source and
`tmp/september-exam-matrix/q27-product-final/high2-native.hwpx`. It describes
that saved artifact, not a later final product or a quality pass. Application
and renderer source files were not edited for the experiments.

The nativecell3 renderer source used for inspection is
`tmp/rhwp_renderer_square_build/rhwp-core-patched/src/renderer/layout/`.

## Picture-wrap width and paragraph margins

The picture belongs to the introductory paragraph. The embedded-cell caller
in `table_cell_content.rs` passes a `WrapAnchorRef` to that owner and paragraphs
still beside the picture. `paragraph_layout.rs` lines 1348–1365 uses cached
`segment_width` directly as the override; lines 1407–1415 subtract only inline
and numbering widths on this path. Paragraph left/indent/right margins still
affect the start position, but are not subtracted from this overridden width.

The actual introductory paragraph has left 0, first-line indent 764, right
254 and cached width 22,430 HWP units. Its first-line extra slack is therefore
1,018/75 = 13.573 px; later lines have 254/75 = 3.387 px extra slack. This
explains the observed first-line ending error +14.235 px and subsequent
+3.812/+3.633 px. Starting glyph errors are approximately zero. Moving the
whole frame or replacing its font would not address this cache contract.

The basic-layout agent independently confirmed this branch and owns the
source-cache A/B and product implementation. Cache widths should represent the
actual remaining line interval after the applicable native paragraph margins,
with source full-frame/raw-text proof and source picture exclusion retained.
Generic non-wrap width semantics should remain unchanged.

## A source-justified field restored as left aligned

The Registration paragraph is a separate issue. The saved native paragraph is
LEFT with a -4,986-unit hanging indent. Its first-row source body spaces advance
9.958–10.080 pt (label-boundary space 10.319 pt), while continuation spaces
advance 4.918–5.039 pt. Their ordinary raw space bboxes are only 3.60–3.68 pt.
Native word-start errors increase in steps at each space; the first-row ending
is -30.481 px, while the continuation ending is only -0.880 px. This is lost
source word-space expansion, not a constant frame offset.

ZIP-only copies isolate the native paragraph property:

| Copy | First-row ending error | First-row maximum error | Continuation maximum error | Pages |
|---|---:|---:|---:|---:|
| Existing LEFT | -30.481 px | 30.481 px | 1.032 px | 8 |
| JUSTIFY only | +4.586 px | 5.040 px | 4.624 px | 8 |
| JUSTIFY plus measured source right ink | +1.199 px | 1.653 px | 0.601 px | 8 |

The last copy's 254-unit right margin is measured, not a page-specific tuning
constant: the available cache width minus the source first-ink-to-last-ink
extent gives 253.64 units, rounded once. The source raw line box ends at
754.278 pt because it includes a trailing space; the last nonspace glyph bbox
ends at 750.695 pt. Keeping that invisible trailing width as justification
space over-expands visible words.

Even the continuation changes when JUSTIFY is enabled. The renderer's
`paragraph_layout.rs` line 1804 branch expands a non-LEFT cell line when it has
negative tracking, its tracked width is below the interval and its natural
width is above it. Thus alignment alone is insufficient; the measured usable
source interval must accompany the property. Remaining ~1.65 px is reported,
not hidden with a fitted threshold or font substitution.

## Narrow producer evidence and negatives

An alignment recovery can use a complete, independently matched source frame
and a semantic paragraph with at least two source rows. Compare several
interior ASCII spaces within the same actual font/size span, excluding label
boundaries. Consistent nonlast-row space advances substantially above the
last-row advance distribution, beyond coordinate uncertainty and normal
within-row spread, are evidence for source justification. Common source ink
rails and complete raw characters must also prove the paragraph and usable
right extent. A colon or field name is not evidence.

Abstain for missing/mismatched raw characters or bboxes, nonfinite geometry,
single-row labels, only one large label-to-value gap, inconsistent or
nonuniform spacing, equations, answer blanks and controls outside the already
proved wrapped-frame contract. Preserve source spaces and semantic paragraphs;
do not introduce one paragraph or cell per printed line.

Raw origins, per-word residuals and isolated copies are in
`tmp/september-exam-matrix/q27-registration-horizontal-readonly.json` and
`q27-registration-justify-ab/report.json`. The reproducible scratch script is
`q27-registration-horizontal-readonly.py` in the same directory. These are
geometry experiments; they do not assert semantic or whole-document quality.

## Implemented source proof and final7 result

`app/pdf_source_justification.py` now reopens the actual PDF after the complete
wrapped-frame proof. Every supplied source span and raw character must exactly
match actual text, font, size, flags, origin and bbox. The resulting decision uses
actual PDF glyphs; changing metadata coordinates cannot induce justification.
It requires at least three eligible interior ASCII spaces in every source row,
a common actual face/size, uniformly greater advances on all nonlast rows and a
consistent visible right-ink boundary. Comparison noise is bounded by float32
coordinate precision or one output HWP coordinate, rather than a fitted visual
threshold. Repeated interior spaces and other interior whitespace abstain.

The wrapped-frame caller supplies its real usable cell width and source text
rail. The helper returns only alignment and right margin, without mutating text,
XML, native paragraphs or source files. It neither searches for a field name nor
uses punctuation, question numbers or file names as source evidence.

The dedicated regression is reproducible with:

```powershell
python -X utf8 scripts/verify_native_source_justification.py tmp/september-exam-matrix/source-justification tmp/september-exam-matrix/q27-product-final7/high2-native.hwpx
```

The standalone helper regression needs the actual source PDF, but no previous
native artifact; the second argument enables the optional integration check.
It covers 29 missing, forged, malformed and nonfinite metadata negatives plus
seven actual synthetic PDFs. A generic multiword paragraph with uniform PDF
word-space expansion is accepted. Ordinary spacing, one label-like large gap,
nonuniform gaps, different actual fonts/sizes and missing frame rules abstain.
All inputs and actual source bytes remain unchanged.

With the integrated final7 source-cache changes, the actual 8-page native
artifact retains all 14 semantic prose paragraphs and the source text. The real
cell supplies right margin 254 and JUSTIFY. Source-to-painted glyph residuals
are:

| Row | First glyph | Last glyph | Maximum absolute glyph error |
|---|---:|---:|---:|
| First source row | -0.003 px | +0.699 px | 1.208 px |
| Continuation | -0.002 px | +0.677 px | 0.782 px |

These measurements use the current nativecell3 runtime and the fresh artifact
`tmp/september-exam-matrix/q27-product-final7/high2-native.hwpx` (SHA-256
`1779adad6b50702e02c6d2c79ed6a963b98dbe43d33f1f379333a516d1d7b5e3`).
They supersede the isolated ZIP experiment for the final product, while
remaining a local geometry result, not a whole-document quality pass. Detailed
evidence is in `tmp/september-exam-matrix/source-justification/report.json` and
`tmp/september-exam-matrix/source-justification.log`.
