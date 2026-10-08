# High3 English raster heading: read-only font inspection

This inspection used the frozen final4 native package, with no application or
renderer changes. It concerns the English-area heading on source page3, rather
than a general heading-font policy.

The actual source page3 `영어 영역` is an image: xref60, bbox
`[365.2200012,111.9610596,477.0939941,140.3410645]`. It has no English-area
glyphs in either the raw text dictionary or actual PDF text traces. The native
page number `3` uses recovered source font `*신명-견명조`; that does not identify
the face inside the separate heading image. Other font resources on the page
also cannot identify the raster heading's original font.

`pdf_masthead_typography.py` deliberately assigns `Malgun Gothic` to this
unlabelled official mock's proved image geometry. This occurs for the running
heading as well as the larger first-page heading; it is not restricted to the
first page. Geometry is source-derived, while the editable font remains a
fallback because the source image supplies no font metadata.

The final4 HWPX running heading's actual inner text style133 has height2006,
horizontal ratio88, tracking0 and bold enabled. All seven language fontRefs
select `Malgun Gothic`. The outer table paragraph's Myeongjo style does not
paint the inner heading characters. The native SVG requests the Korean/English
Malgun family names, and native PDF text traces select `MalgunGothicBold` for
all four nonspace heading characters. Windows contains registered Malgun
regular/bold fonts; the existing Windows Skia probe resolves the regular family
to `MalgunGothic`. Thus the observed Gothic heading is the selected fallback,
not evidence that a requested source Myeongjo heading failed alias resolution.

A bounded A/B probe changed only the running heading style's fontRefs in five
temporary HWPX copies. Text, height, ratio, tracking, bold flag, line cache and
table geometry stayed identical. Candidates were installed Malgun Gothic,
HYMyeongJo-Extra, HYSinMyeongJo-Medium, HCR Batang and Batang. The source page
was rendered at the native canvas scale, and the same fixed clip
`[330,100,465,135]` was used without translation or glyph fitting. The clip
excludes the separate header rule. Black-ink masks use the same threshold128
for every image; the numbers are descriptive comparisons, not pass criteria.

| Native candidate | Fixed-canvas source ink IoU | Native black pixels |
|---|---:|---:|
| Malgun Gothic | 0.4155 | 901 |
| HYMyeongJo-Extra | 0.2559 | 731 |
| HYSinMyeongJo-Medium | 0.2239 | 472 |
| HCR Batang | 0.1814 | 605 |
| Batang | 0.2048 | 478 |

Malgun Gothic is the closest of these five under this fixed comparison, and
the native shape still differs visibly from the source raster. None identifies
the original face. Each candidate retains eight pages, identical page3 SVG
text outside the heading, and zero changed native PNG pixels outside the
heading clip. This is local page3 invariance, not a whole-document glyph audit.

Reproduction and evidence:

- `tmp/september-audit/high3-heading-font-ab.py`
- `tmp/september-audit/high3-heading-font-ab/report.json`
- `tmp/september-audit/high3-heading-font-ab/comparison.png`
- `tmp/september-audit/high3-heading-font-ab/native-p3-header-font-traces.json`

The original final4 package remains unchanged (SHA-256
`bcdf7f91283ff5264a8abe5a153134e45f0adc61cd0ecb97f284441fcb33632f`).
No application/runtime edit, source font guess, premium path, image overlay,
quality threshold change or whole-document quality claim follows from this
probe.
