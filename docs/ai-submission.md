# AI-assisted work: what to include in your submission

We allow AI tools. We still need evidence of **your** engineering judgment.

## Required when AI was used

Add a section to `SUBMISSION.md` (or attach separate files) with:

1. **Tooling:** Which product(s) (for example ChatGPT, Claude, Cursor, Copilot) and approximate share of AI-generated vs hand-edited lines.
2. **Prompts summary:** The *intent* of major prompts (not full logs unless you already have them), especially for refactors and tests.
3. **What you rejected:** At least one AI suggestion you **did not** take, and why.
4. **Verification:** Commands you ran locally (`pytest`, `ruff`, manual `curl`) after AI edits.

## Optional but helpful

- Export or paste a `CLAUDE.md` / `AGENTS.md` / `.cursor/rules` style file if you used project-specific AI instructions — this helps reviewers separate intentional constraints from model drift.
- If you used IDE inline completions only, say so explicitly.

## Integrity

Paste-polished code you cannot explain in review is a strong negative signal. Prefer smaller, understandable diffs you own end-to-end.
