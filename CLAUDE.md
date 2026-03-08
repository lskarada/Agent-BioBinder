# ycbio — Agent Binder

## Project
Next.js 15 (App Router) + TypeScript + Tailwind CSS hackathon project.
App lives in `agent-binder/`. Always work from that directory.

## Stack
- Framework: Next.js 15 App Router (`agent-binder/app/`)
- Language: TypeScript (strict)
- Styling: Tailwind CSS
- Package manager: npm

## Key Commands
```bash
cd agent-binder
npm run dev      # Start dev server (localhost:3000)
npm run build    # Production build
npm run lint     # ESLint
npx tsc --noEmit # Type check without building
```

## Architecture Conventions
- Server Components by default; use `"use client"` only for interactivity
- Co-locate components with their pages unless reused 3+ times
- No `any` types — use `unknown` + narrowing
- Prefer `async/await` over `.then()` chains
- API routes in `app/api/[route]/route.ts`

## Development Approach
- Write the simplest thing that works first, optimize later
- Use `/tdd` for new features, `/code-review` before committing
- Use `/plan` before any feature >30min of work
- Run `npx tsc --noEmit` before every commit

## ECC Agents Available (global — ~/.claude/agents/)
planner, architect, tdd-guide, code-reviewer, security-reviewer, build-error-resolver,
database-reviewer, e2e-runner, refactor-cleaner, doc-updater, chief-of-staff,
harness-optimizer, loop-operator, python-reviewer, go-reviewer, go-build-resolver

## ECC Commands to Use
/plan — before starting a feature
/tdd — when writing new components/functions
/code-review — before git commit
/build-fix — when tsc or build fails
/multi-plan + /multi-execute — for parallel feature work
