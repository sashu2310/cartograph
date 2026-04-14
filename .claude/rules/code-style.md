# Code Style

## Formatter & Linter

Ruff handles both. Config lives in `pyproject.toml`:

```toml
[tool.ruff]
line-length = 88
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "SIM", "RUF"]
ignore = ["E501", "N802"]
```

- **E501 ignored** — line length is soft (88 target, not enforced)
- **N802 ignored** — `ast.NodeVisitor` methods use camelCase (`visit_Call`, `visit_If`)

## Import Order

isort via ruff. First-party package: `cartograph`.

```python
import ast                              # stdlib
from pathlib import Path                # stdlib

from click import command               # third-party

from cartograph.graph.models import Node  # first-party
```

## Type Annotations

Python 3.11+ — use modern syntax:

```python
# Yes
def parse(path: Path) -> list[ParsedModule]: ...
def find(name: str) -> ParsedFunction | None: ...

# No
from typing import List, Optional
def parse(path: Path) -> List[ParsedModule]: ...
```

Use `Optional` only when imported from typing is already in scope. Prefer `X | None`.

## Naming

- Functions, methods, variables: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- Private helpers: `_leading_underscore`
- Protocol methods: descriptive verbs (`parse_file`, `detect_entry_points`)

## Enums

Use `str, Enum` pattern:

```python
class NodeType(str, Enum):
    FUNCTION = "function"
    METHOD = "method"
```

## Dataclasses

Use `@dataclass` for data models, `field(default_factory=...)` for mutable defaults:

```python
@dataclass
class ParsedFunction:
    name: str
    qualified_name: str
    calls: list[FunctionCall] = field(default_factory=list)
```

## Comments

No comments for obvious code. Only comment non-obvious decisions or workarounds.
