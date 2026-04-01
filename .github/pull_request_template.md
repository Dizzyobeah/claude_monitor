## Summary

<!-- What changed and why? -->

## Test Plan

<!-- How was this tested? -->

## Checklist

- [ ] Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, etc.)
- [ ] Tests pass (`cd daemon && uv run pytest`)
- [ ] Lint passes (`cd daemon && uv run ruff check .`)
- [ ] Firmware builds (`cd firmware && pio run -e e32r28t`) — if firmware was changed
