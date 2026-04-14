# Claude Code Project Setup Prompt

Copy the prompt below into Claude Code in a new project to generate a complete `.claude/` configuration.

---

## Prompt

```
Set up a complete Claude Code project configuration for this codebase. Analyse the repo thoroughly first — read the project structure, framework, dependencies, settings, test setup, CI/CD, and deployment config before generating anything.

## What to generate

### 1. `.claude/CLAUDE.md` — Project instructions

Structure it as:

- **Project Overview** — One paragraph: what this project is, what it does, who uses it.
- **Commands** — Grouped by purpose (Development, Testing, Linting, Deployment). Only include commands that actually work in this repo. Read package.json / pyproject.toml / Makefile / Dockerfile to find them.
- **Architecture** — Framework stack (be specific: "django-ninja-extra, not DRF" level of specificity), key dependencies, app/module map with one-line descriptions.
- **Settings & Environments** — How environments are selected, key env vars, DB differences between dev/test/prod.
- End with `@rules/<name>.md` references for each rules file you create.

Keep it factual. Don't describe what Claude Code is. Don't add generic instructions. Every line should be specific to THIS codebase.

### 2. `.claude/rules/` — One file per concern

Create separate rules files for each major area. Only create rules files for areas that are relevant to this project. Common areas:

- **code-style.md** — Formatter, linter, import order, type annotation conventions, naming patterns. Read existing code to determine what's actually used, don't prescribe.
- **security.md** — Auth patterns, input validation approach, secrets handling, SQL safety, any automated security tooling (Snyk, SonarCloud, etc). Read CI workflows to find these.
- **api-patterns.md** — How endpoints are structured, auth/permission patterns, schema conventions, how to register new endpoints. Include a realistic code example from the actual codebase.
- **testing.md** — Test runner, base classes, fixtures, factories, mocking patterns, how to run tests. Read existing test files to extract the actual patterns.
- **permissions.md** — Only if the project has a permission/RBAC system. Document how permissions are applied.
- **audit-logging.md** — Only if the project has audit logging. Document what's tracked and how.

Rules for writing rules files:
- Every pattern must be derived from reading the actual code, not assumed.
- Include code examples taken from or modelled on the real codebase.
- Include "Never" / "Always" directives only when the codebase has a clear convention.
- Skip any area that doesn't have enough convention to document.

### 3. `.claude/settings.json` — Permissions and hooks

```json
{
  "permissions": {
    "allow": [
      "Edit",
      "Write",
      // Auto-allow: formatter, test runner, package manager, read-only git
      // Read the project to determine: pytest/jest/go test, black/prettier/rustfmt, etc.
    ],
    "deny": [
      // Block destructive ops:
      "Bash(git push:*)",
      "Bash(rm -rf /)",
      // Add infra-specific denials based on what's in the project:
      // kubectl delete, terraform destroy, aws destructive ops, etc.
      // Block writing secrets files:
      "Write(.env)"
    ]
  },
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "// Auto-format on save — detect the formatter from the project (black, prettier, rustfmt, gofmt, etc.)"
          }
        ]
      }
    ]
  }
}
```

Detect the actual formatter and test commands from the project config. Don't hardcode black/pytest if the project uses something else.

### 4. `.claude/agents/code-reviewer.md` — Deep code reviewer

Create a code-reviewer agent tailored to this project. Structure:

```markdown
---
name: code-reviewer
description: Multi-phase deep code reviewer for <project>. Performs breadth-first scan, then targeted deep dives on critical areas.
model: sonnet
tools: ["Read", "Grep", "Glob", "Bash", "Agent"]
---
```

The agent must perform these phases:

**Phase 1: Breadth Scan** — Classify every changed file by type (Model/API/Task/Logic/Config) and risk level. Output as a table.

**Phase 2: Critical Bug Patterns** — Build a checklist of bug patterns specific to this project's tech stack. Examples:
- Python/Django: mutable defaults, transaction.atomic + async dispatch, bare except, N+1 queries, missing auth
- Go: unchecked errors, goroutine leaks, race conditions, context cancellation
- Node/TS: unhandled promise rejections, callback hell, missing error middleware
- General: division by zero, SQL injection via string formatting, hardcoded secrets

Read the codebase history (recent bug fixes, hotfixes) to find patterns that have actually occurred. Include those specifically.

**Phase 3: Contextual Deep Dive** — Per file type: model (migration safety, cascades, indexes), API (auth, permissions, schema leaks), tasks (idempotency, timeout, error handling), business logic (edge cases).

**Phase 4: Traceability** — For pipeline/task changes: correlation IDs, state transition logging, debuggability at 3am.

**Phase 5: Cross-Codebase Impact** — Grep for callers, check for tests, find related copies of fixed bugs, verify domain boundaries.

**Output format**: Summary table (# | Severity | Category | File:Line | Finding), detailed write-ups for CRITICAL/WARNING, verdict (APPROVE / REQUEST CHANGES / NEEDS DISCUSSION).

**Rules**: Don't nitpick formatting. Don't repeat what code does. Verify critical findings by reading actual source files. Keep findings short.

### 5. `.claude/skills/` — Use skills, NOT commands

**Do NOT create a `.claude/commands/` directory.** Skills are the current format. They support reference docs, frontmatter metadata, and richer configuration. Create skills only.

For each skill, create a directory with `SKILL.md` and optionally a `reference.md` for codebase-specific context.

**Required skills:**

**`review-pr/SKILL.md`** — Takes a PR number, fetches diff via `gh`, runs the same multi-phase review as the code-reviewer agent but on a specific PR. Include steps to fetch PR context, classify changes, check bug patterns, deep dive, cross-codebase impact, and output findings. Do NOT auto-post comments — present findings first, post only when asked.

Add a **`review-pr/review-gaps-reference.md`** if you can find patterns in recent PRs (check git log for fix-on-fix chains, PRs merged without tests, etc.).

**`write-tests/SKILL.md`** + **`reference.md`** — Unit test generator following project conventions. The reference.md must include: test runner command, base classes, fixture/factory locations, mocking patterns, and a complete test skeleton. Read existing test files to extract these.

**`explain-code/SKILL.md`** + **`reference.md`** — Code explainer with codebase context. The reference.md must include: tech stack table, app/module map, API patterns, auth patterns, and key conventions.

**Optional skills (create only if relevant):**

- `run-tests/SKILL.md` — If the test command has project-specific nuances (env vars, paths, parallel flags)
- `make-migration/SKILL.md` — If the project uses Django or similar ORM with migrations
- `new-controller/SKILL.md` — If the project has a scaffolding pattern for new API endpoints/routes

**Do NOT create skills with `disable-model-invocation: true`** — either the skill is ready to use or don't create it.

### 6. `.gitignore` additions

Add these entries to the project's `.gitignore`:

```
# Claude Code local files
.claude/settings.local.json
.claude/worktrees/
```

`settings.local.json` accumulates per-session permission approvals. `worktrees/` is created by agent isolation mode. Neither should be committed.

## What NOT to do

- Don't create a `.claude/memory/` directory with reference links — that's personal memory, not project config.
- Don't create `.claude/commands/` — use `.claude/skills/` instead.
- Don't add generic Claude Code instructions to CLAUDE.md — it's for project-specific knowledge.
- Don't create skills you mark as disabled.
- Don't assume patterns — read the actual code, tests, and CI config first.
- Don't add a `.claude/settings.local.json` — that's auto-generated per user.

## Process

1. First, explore the codebase structure: directory layout, framework, dependencies, settings, test files, CI workflows.
2. Then generate each file, using actual code examples and patterns from the repo.
3. Show me the full file tree and a summary of what each file contains before writing.
4. Write all files.
5. Verify: run the formatter and test commands you put in settings.json to confirm they actually work.
```
