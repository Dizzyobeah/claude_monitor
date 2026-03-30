---
name: code-review-to-fix
description: Streamlined workflow to take review findings (code review, lint output, audit results) and execute fixes efficiently. Skips plan mode -- executes directly. (user)
allowed-tools: Read, Bash, Grep, Glob, Edit, Write, Agent
---

# Code Review to Fix - Execute Known Fix Lists

Take a list of known issues (from code review, lint, audit, etc.) and fix them efficiently without entering plan mode.

## Instructions

### When to Use

- You have a concrete list of issues to fix (review comments, lint errors, audit findings)
- Each issue is well-defined with a clear fix
- This is NOT for exploratory/architectural work -- use plan mode for that

### Workflow

1. **Parse the fix list**: Extract each issue into a numbered list with file + description
2. **Batch reads**: Read ALL affected files in parallel (one round of reads, not sequential)
3. **Prioritize**: Fix in this order:
   - Security issues first
   - Correctness bugs second
   - Style/quality last
4. **Execute fixes**: Make edits directly. No re-reading files you already read. No subagents for trivial fixes.
5. **Verify**: Run relevant build/test commands ONCE after all fixes are applied
6. **Report**: Brief summary of what was fixed, one line per item

### Anti-Patterns to Avoid

- **Do NOT** enter plan mode -- the plan is the fix list itself
- **Do NOT** re-read files you already read in step 2
- **Do NOT** launch subagents for single-line fixes
- **Do NOT** ask the user to confirm each fix individually -- batch them
- **Do NOT** over-scope by "noticing" unrelated improvements while fixing

### Proactive Scanning

When fixing a class of issue (e.g., "missing null check"), scan for other instances of the same pattern across the codebase:

```
"While fixing the 6 issues from the review, I found 2 more instances of the same missing-null-check pattern. Want me to fix those too?"
```

### Verification

After all fixes:
- **Python daemon**: `uv run pytest`
- **ESP32 firmware**: `pio run -e esp32dev`
- **General**: `git diff --stat` to confirm only expected files changed

## Usage Examples

```
/code-review-to-fix
/code-review-to-fix fix the 5 issues from the security audit
/code-review-to-fix apply lint fixes from ruff output
```
