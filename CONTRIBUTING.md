# Contributing to Claude Monitor

## Getting Started

1. **Fork** the repository on GitHub
2. **Clone** your fork:
   ```bash
   git clone https://github.com/<your-username>/claude_monitor.git
   cd claude_monitor
   ```
3. **Create a branch** from `main`:
   ```bash
   git checkout -b feat/my-feature
   ```

## Branch Naming

Use a prefix that matches the change type:

- `feat/description` — new feature
- `fix/description` — bug fix
- `docs/description` — documentation only
- `refactor/description` — code restructure without behavior change

## Conventional Commits

This project uses [Conventional Commits](https://www.conventionalcommits.org/). A CI check enforces this on pull requests.

Format: `type: short description`

| Prefix | When to use | Version bump |
|--------|------------|--------------|
| `feat:` | New feature | Minor (0.x.0) |
| `fix:` | Bug fix | Patch (0.0.x) |
| `docs:` | Documentation only | None |
| `refactor:` | Code restructure, no behavior change | None |
| `test:` | Adding or updating tests | None |
| `chore:` | Build, CI, tooling changes | None |
| `perf:` | Performance improvement | Patch (0.0.x) |

For breaking changes, add `BREAKING CHANGE:` in the commit body or use `feat!:` / `fix!:` — this triggers a major version bump.

## Development Setup

### Daemon (Python)

```bash
cd daemon
uv sync --all-extras
```

### Firmware (ESP32)

```bash
cd firmware
pio run -e e32r28t
```

See `platformio.ini` for other board variants: `cyd_cap`, `cyd_v2`, `cyd_standard`.

## Running Tests

```bash
cd daemon
uv run pytest
uv run ruff check .
```

## Pull Requests

- Target the `main` branch
- One logical change per PR
- Fill out the PR template
- Ensure tests and lint pass before requesting review
