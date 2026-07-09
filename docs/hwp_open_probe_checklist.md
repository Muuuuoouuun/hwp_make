# HWP Open Probe Checklist

Updated: 2026-07-09

Use this checklist only for Hancom GUI/open behavior. It is a supporting gate, not the primary layout or equation quality gate.

## What The App Can Control

- HWPX package structure and XML validity
- Document protection flags written by our generator
- Read-only file attribute on generated outputs
- Output path under the local app export directory
- Whether the file is still locked by a running process
- Mark-of-the-Web or zone metadata when present on files copied from browser/download paths

## What The App Usually Cannot Control

- Hancom advertisement tabs
- Account/login prompts
- Viewer/free-edition upsell prompts
- Product update notices
- License/channel-specific start pages

These are environment-level prompts. They can block Computer Use automation, but they should not be treated as a generated HWPX content failure unless the document itself opens read-only, protected, corrupted, or non-editable.

## Manual/Computer Use Probe

Record these fields when GUI behavior matters:

- Sample file name
- Generated path
- Hancom product/version if visible
- Opens editable: yes/no
- Read-only/protected view: yes/no
- Permission/editing tab: yes/no
- Ad/account/update tab: yes/no
- File opened from `data/exports` or another trusted local path: yes/no
- File has read-only attribute: yes/no
- Mark-of-the-Web present: yes/no/unknown
- Notes and screenshot path if needed

## Preferred Debug Order

1. Run XML/package verification first.
2. Run rhwp/render verification when available.
3. Check generated file attributes and output path.
4. Use `scripts/probe_hwp_open.ps1` for limited-time open probing.
5. Use Computer Use only for final diagnosis or screenshots of Hancom-specific prompts.

## Pass/Fail Interpretation

- PASS: generated HWPX opens editable, or script/render gates pass and any remaining prompt is clearly ad/account/update related.
- ACTIONABLE: read-only/protected/edit-permission prompt appears because of file metadata, document protection flags, locked path, or Mark-of-the-Web.
- ENVIRONMENT: ad/account/update prompt appears but the document itself is editable after closing the prompt.
- FAIL: Hancom reports the document as corrupt, non-editable due to document content, or consistently crashes on the generated file.
