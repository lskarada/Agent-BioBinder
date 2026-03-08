# ECC Cheat Sheet — ycbio Setup

## Section 1 — Verification Checklist

| Thing to verify | How |
|-----------------|-----|
| CLAUDE.md loaded | Open ycbio in Claude Code → Claude should describe the stack without being asked |
| MCP: memory | Ask "store that X = Y" → Claude confirms it saved |
| MCP: sequential-thinking | Tackle a multi-step problem → Claude shows structured reasoning steps |
| MCP: context7 | Type `use context7` in a prompt about Next.js → Claude fetches live docs |
| Session hooks | Start a session → should see output from session-start.js in terminal |
| Env vars | Run `echo $MAX_THINKING_TOKENS` → should print `10000` (after `source ~/.zshrc`) |
| **Plugin** | Run `/plan` in Claude Code → should work; 16 agents + 40 commands installed |
| Plugin location | `~/.claude/agents/` (16 files) and `~/.claude/commands/` (40 files) — global, not project-level |

---

## Section 2 — When to Use Each Feature

### Slash Commands (need plugin first)

| Command | When |
|---------|------|
| `/plan` | Starting any feature that'll take >30 min |
| `/tdd` | Writing a new component or function |
| `/code-review` | Before every git commit |
| `/build-fix` | TypeScript or build is broken |
| `/multi-plan` + `/multi-execute` | Building two+ features at the same time |

### Agents (invoked automatically by rules or manually)

| Agent | When |
|-------|------|
| `planner` | Need a step-by-step breakdown before coding |
| `architect` | Deciding how to structure something big |
| `tdd-guide` | Writing tests first |
| `code-reviewer` | Catching bugs before committing |
| `security-reviewer` | Before shipping anything to users |
| `build-error-resolver` | When `tsc` or `npm run build` fails |

### MCP Servers

| Server | When |
|--------|------|
| `memory` | Claude should remember something across sessions ("remember that…") |
| `sequential-thinking` | Complex problems where order of steps matters |
| `context7` | Add `use context7` to any prompt when using Next.js/React/Tailwind APIs |

### Rules (automatic — no action needed)

| Rule | What it does |
|------|-------------|
| `coding-style` | Enforces async/await, Zod, no console.log |
| `development-workflow` | Reminds Claude to search before writing new code |
| `git-workflow` | Shapes commit messages and PR format |
| `performance` | Picks the right model tier automatically |
| `security` | Blocks hardcoded secrets |
| `testing` | Wires Playwright for E2E |
| `patterns` | Standardizes API response shape and custom hooks |

### Hooks (automatic)

| Hook | What it does |
|------|-------------|
| `PostToolUse` | Reminds you to run `tsc --noEmit` after editing files |
| `SessionStart` | Loads last session's context when you open Claude Code |
| `Stop` | Saves a summary of the session when you close |

### CLAUDE.md

Gives Claude instant project context at the start of every session — keep it updated as the app grows.
