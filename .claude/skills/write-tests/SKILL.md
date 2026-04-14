---
name: write-tests
description: Generate pytest unit tests for Cartograph following project conventions — fixtures, class grouping, and assertion patterns.
---

# Write Tests

Generate tests for a given module or function.

## Input

$ARGUMENTS — file path or function name to test

## Steps

1. **Read the target code** — understand what it does, its inputs, outputs, and edge cases.

2. **Read existing tests** — check `tests/` for existing test patterns, especially:
   - `tests/conftest.py` for available fixtures
   - Existing test files for the same module

3. **Identify test cases:**
   - Happy path
   - Edge cases (empty input, None, missing data)
   - Error conditions
   - For parsers: different AST node patterns
   - For graph: cycle detection, cross-file resolution
   - For web: missing parameters, invalid qnames

4. **Write tests** following conventions in `reference.md`

5. **Run tests** to verify they pass:
   ```bash
   pytest tests/test_<module>.py -v
   ```

6. **Run linter:**
   ```bash
   ruff check tests/test_<module>.py --fix
   ruff format tests/test_<module>.py
   ```
