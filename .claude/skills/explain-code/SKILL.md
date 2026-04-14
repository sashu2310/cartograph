---
name: explain-code
description: Explain Cartograph code with full codebase context — architecture, data flow, and framework patterns.
---

# Explain Code

Explain a module, function, or concept with full project context.

## Input

$ARGUMENTS — file path, function name, module name, or concept (e.g., "call resolution", "framework detectors")

## Steps

1. **Locate the code** — find the target using Grep/Glob.

2. **Read the code** — read the full file and any related files.

3. **Trace dependencies:**
   - What calls this code? (Grep for function name)
   - What does this code call? (Read imports and function body)
   - What protocols/contracts does it implement?

4. **Explain with context** from `reference.md`:
   - Where it fits in the architecture
   - How data flows through it
   - Key design decisions and trade-offs
   - How to modify or extend it

5. **Keep it concise** — focus on the non-obvious. Don't explain what the code literally does line-by-line.
