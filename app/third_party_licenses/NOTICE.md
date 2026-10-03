# Third-party notices

## kordoc

- Source: https://github.com/chrisryugj/kordoc
- Copyright 2026 chrisryugj, MIT License (`kordoc.LICENSE`)
- Used in: `app/hancom_eqn_latex.py` (Python port of `src/hwpx/equation.ts`),
  and rules re-implemented in `app/hwpx_writer.py` (LaTeX → Hancom equation
  script) and `app/importers.py` (HWPX inline text, `hp:switch`, click-here
  fields, answer-first endnotes, merged-cell tables, section order).

## hml-equation-parser

- Source: https://github.com/OpenBapul/hml-equation-parser
- Copyright 2018 Open Bapul, Apache License 2.0 (`hml-equation-parser.LICENSE`)
- Used in: `app/hancom_eqn_latex.py`, which ports the rewrite passes
  (frac → root-of → matrix → accent → brace) of `hulkEqParser.py` /
  `hulkReplaceMethod.py` by way of kordoc's TypeScript port.
- Modifications: Python rewrite; extra tokens emitted by this app's own
  writer (`choose`, `atop`, `^3sqrt`, lowercase operator words, `rm`/`it`).
