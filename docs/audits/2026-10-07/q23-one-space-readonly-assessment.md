# Q23 terminal space: read-only font-program assessment

A narrowly proved one-space terminal row can justify Q23's quarter-em word
space in a future change. Simply reducing the current three-advance threshold
to one for every paragraph would weaken the proof. No helper, product code or
test expectation was changed for this assessment.

## Actual original PDF evidence

Source: `data/external_exam_qa/2027_kice_september_high3/english.pdf`

SHA-256: `745d64d94e0719735b88a10802fbbd5053b4982c855199396e58fe2f53b81cf0`

- Page 3 uses Type0 font xref84, `ODBEAE+TimesNewRoman`, with resource `C2_0`.
  Its descendant CID font is xref117; `/CIDToGIDMap /Identity` binds CID3 to
  GID3. ToUnicode stream xref85 maps CID3 to U+0020. The descendant `/W` array
  gives CID3 width 250 in 1000 text-space units.
- FontDescriptor xref116 identifies Times New Roman, weight400, italic angle0,
  and FontFile2 xref115. The extracted embedded TrueType program is 98,476
  bytes, SHA-256
  `bdb6cf628048fbea993ab0a24eef3325a46428531c20df0938bdbbcf65651e0f`.
- In that extracted font byte array, the `head` table starts at 98,420;
  `unitsPerEm` is the big-endian uint16 at offset98,438 and equals2048.
  The `hmtx` table starts at7,104. GID3's big-endian advanceWidth is at
  offset7,116 and equals512. Thus the actual program's U+0020 advance is
  512/2048 = 0.25 em. The `hhea` metric count is4684, so this is a full
  advanceWidth entry rather than the trailing sidebearing-only region.
- Q23's actual final source row is `with potential.`. It is horizontal
  (`wmode=0`, direction `(1,0)`), uses regular TimesNewRoman flags4 and
  size12.180000305 points. Its one space has bbox width0.250001096 em and
  next-glyph origin advance0.2489011605 em.

The font program proves the natural glyph width. It does not by itself prove
effective PDF word spacing, which may be affected by text state or individual
text positioning. The actual terminal-row advance supplies that missing
effective-spacing evidence for this row.

## Required proof for a future one-space branch

Reopen the actual PDF and bind the same embedded font program, space code/CID,
glyph, scale and transform to every actual body span. Retain the complete
raw row/span/character/font/flags/size/origin/bbox/text proof and semantic body
boundary. Explicitly establish that the measured row is the actual terminal
row of the complete body, rather than a supplied truncated subset or a
justified nonfinal row. Require the actual effective advance to agree with
the independently proved natural program width within a justified numerical
tolerance. A matching glyph bbox without the actual advance is insufficient.

Native text must remain exactly matched, and correction must be restricted to
an ordinary single ASCII space at the proved cursor position. Retain the
native half-em/clamp calculation: `(ratio80, spacing-15)` yields0.25 em.
Reject font/program/code/CID mismatches, nonregular fonts, synthetic spaces,
unsupported direction/transform, changed raw glyph geometry or text, missing
or substituted terminal rows, partial/reordered bodies, equations, tables,
inline labels, answer blanks, and double/NBSP/tab/split-boundary spaces.

This evidence supports a future narrow source-font-backed branch. The current
frozen helper still has three actual positive bodies, Q19/Q20/Q22. It does not
yet apply to Q23; this report does not change the current quality result.
