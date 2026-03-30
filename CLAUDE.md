## Workflow Orchestration

### 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity
- **Exception**: When you already have a concrete list of known fixes (from a review, lint output, etc.), skip plan mode and execute directly. Plan mode is for uncertain/architectural work, not for applying a known checklist.

### 2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution

### 3. Self-Improvement Loop
- After ANY correction from the user: update tasks/lessons.md with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project

### 4. Verification Before Done
- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

#### CLI-First Verification
- Before writing scripts, docs, or install instructions that invoke CLI commands, run `--help` to verify the command exists and understand its syntax
- Never write installation/setup documentation based on assumed CLI interfaces
- Test the happy path yourself before presenting it to the user

#### Build-Test-Build Loop
- After any code change to firmware or daemon, run the build/test command yourself
- Do not wait for the user to paste errors -- catch cascading failures proactively
- For ESP32 firmware: `pio run -e esp32dev` after edits
- For Python daemon: `uv run pytest` after edits

### 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes -- don't over-engineer
- Challenge your own work before presenting it

### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests -- then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how
- When fixing a class of problem (e.g., removing build artifacts), proactively scan for all instances of the same class -- don't make the user ask for each one individually
- "While fixing X, I noticed Y and Z have the same issue -- want me to fix those too?"

## Task Management

1. **Plan First**: Write plan to tasks/todo.md with checkable items
2. **Verify Plan**: Check in before starting implementation
3. **Track Progress**: Mark items complete as you go
4. **Explain Changes**: High-level summary at each step
5. **Document Results**: Add review section to tasks/todo.md
6. **Capture Lessons**: Update tasks/lessons.md after corrections
7. **Never offer to commit**: Present results and wait. The user will commit when ready.

## Core Principles

- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact**: Only touch what's necessary. No side effects with new bugs.
- **Read Once, Act Decisively**: When a fix is visible from the first file read, make the edit immediately. Do not re-read, grep, and re-read the same file looking for confirmation. If the fix spans multiple files, batch all reads in parallel.
- **Prevent Recurrence**: If an operation has a known side effect (e.g., filter-repo deletes uncommitted files), take the preventive step before repeating the operation. Don't just warn -- act.
- **Match Scope to Request**: If the user asks for a document, plan, or reference artifact -- produce that, not an implementation. Ask before escalating from "create a plan" to "implement the plan."

## Platform Notes

### ESP32/Arduino
- Never use bare names that collide with Arduino macros: `DEFAULT`, `HIGH`, `LOW`, `INPUT`, `OUTPUT`, `LED_BUILTIN`, etc. Prefix enum values (e.g., `THEME_DEFAULT`)
- Use `which pio` to find the PlatformIO binary path -- don't guess `~/.platformio/penv/bin/pio`
- Flash upload failures are hardware/connection issues -- don't make code changes for them
