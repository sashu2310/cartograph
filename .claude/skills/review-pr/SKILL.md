---
name: review-pr
description: Deep multi-phase PR review for Cartograph. Fetches diff via gh, classifies changes, checks bug patterns, and outputs structured findings.
---

# Review PR

Review a pull request using multi-phase analysis.

## Input

$ARGUMENTS — PR number (e.g., `42`) or URL

## Steps

### 1. Fetch PR Context

```bash
gh pr view $PR_NUMBER --json title,body,files,additions,deletions,baseRefName,headRefName
gh pr diff $PR_NUMBER
```

### 2. Classify Changes

Build a table of all changed files:

| # | File | Type | Risk | +/- |
|---|------|------|------|-----|

Types: Parser, Graph, CLI, Web, LLM, Test, Config

Risk levels:
- **CRITICAL** — Graph model changes, call resolution logic, protocol contracts
- **HIGH** — Parser changes, framework detectors, LLM providers
- **MEDIUM** — CLI changes, web endpoints, serializers
- **LOW** — Tests, docs, config

### 3. Bug Pattern Check

Run the code-reviewer agent's Phase 2 checklist against the diff. Focus on:
- AST visitor completeness
- Call graph resolution correctness
- Mutable defaults in dataclasses
- Unbounded traversal depth
- API key exposure in LLM code

### 4. Deep Dive

For each HIGH/CRITICAL file:
- Read the full file (not just the diff) for context
- Check that changes are consistent with protocols in `cartograph/parser/protocols.py`
- Check that graph model changes don't break serializers
- Verify test coverage exists for new code paths

### 5. Cross-Codebase Impact

- Grep for callers of modified functions
- Check if test fixtures need updates
- Look for enum usage across serializers and CLI

### 6. Output

Present findings as:

| # | Severity | Category | File:Line | Finding |
|---|----------|----------|-----------|---------|

Detailed write-ups for CRITICAL/WARNING findings.

Verdict: **APPROVE** / **REQUEST CHANGES** / **NEEDS DISCUSSION**

Do NOT auto-post comments. Present findings first. Only post to GitHub when explicitly asked.
