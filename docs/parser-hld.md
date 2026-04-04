# CARTOGRAPH Parser Layer — Detailed HLD

## Design Goal

Parse any programming language and produce the SAME intermediate representation. The graph layer, LLM layer, and render layer should never know which language they're working with.

---

## The Three-Layer Architecture

```
Source File (.py, .java, .go, .js, .rs)
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│  LAYER 1: SYNTAX PARSER                                      │
│  "Give me the syntax tree"                                   │
│                                                              │
│  WHO:    Tree-sitter (universal, community-maintained)       │
│  INPUT:  Raw source code + language grammar                  │
│  OUTPUT: Concrete Syntax Tree (CST)                          │
│                                                              │
│  WE DON'T WRITE THIS. Tree-sitter + community grammars.     │
│  Updated by 1000s of contributors. We just install:          │
│    pip install tree-sitter-python                            │
│    pip install tree-sitter-java                              │
│    pip install tree-sitter-go                                │
│                                                              │
│  Language updates? Community updates the grammar.            │
│  Python 3.13 adds new syntax? Grammar gets updated.          │
│  We do nothing.                                              │
└──────────────────────────┬──────────────────────────────────┘
                           │ CST (language-specific tree structure)
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  LAYER 2: LANGUAGE ADAPTER                                   │
│  "Extract what I care about from this syntax tree"           │
│                                                              │
│  WHO:    We write these. One per language. ~200-300 lines.   │
│  INPUT:  CST from Tree-sitter                                │
│  OUTPUT: ParsedModule (our uniform IR)                       │
│                                                              │
│  Uses Tree-sitter QUERIES (S-expressions) to extract:        │
│  - Function/method definitions (name, params, line, body)    │
│  - Class definitions                                         │
│  - Import statements                                         │
│  - Function calls within bodies                              │
│  - Decorator/annotation patterns                             │
│  - Conditional branches                                      │
│  - Return statements                                         │
│                                                              │
│  Each language adapter knows the SHAPE of its language:       │
│    Python: def, class, @decorator, import X from Y           │
│    Java: public void, class, @Annotation, import X.Y.Z      │
│    Go: func, type struct, go routine, import "pkg"           │
│    JS: function, class, import/require, async/await          │
│                                                              │
│  But outputs the SAME ParsedModule regardless.               │
└──────────────────────────┬──────────────────────────────────┘
                           │ ParsedModule (uniform IR)
                           │ Language-agnostic from here onward
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  LAYER 3: FRAMEWORK DETECTOR                                 │
│  "What do these patterns MEAN?"                              │
│                                                              │
│  WHO:    We write these. One per framework. ~100-200 lines.  │
│  INPUT:  ParsedModule (IR)                                   │
│  OUTPUT: Annotated ParsedModule (entry points, async         │
│          boundaries, ORM operations, signal handlers)        │
│                                                              │
│  Examines decorators, function names, call patterns:         │
│    Django Ninja: @api_controller, @route.get → API entry     │
│    Celery: @task, .delay() → async boundary                  │
│    Spring Boot: @RestController, @Async → API entry + async  │
│    Express: app.get("/path") → API entry                     │
│    Go net/http: http.HandleFunc → API entry                  │
│    gRPC: service definition → RPC entry                      │
│                                                              │
│  Framework detectors are COMPOSABLE:                         │
│    A Python file can use Django + Celery + Signals.          │
│    All three detectors run on the same ParsedModule.         │
└──────────────────────────┬──────────────────────────────────┘
                           │ Annotated ParsedModule
                           ▼
                    ┌──────────────┐
                    │  Graph Layer  │  (never knows which language)
                    └──────────────┘
```

---

## Why Three Layers, Not Two

You might ask: "Why not have the Language Adapter also detect frameworks?"

Because frameworks cross language boundaries and evolve independently:

```
Python + Celery    →  Celery detector
Python + Django    →  Django detector
Python + FastAPI   →  FastAPI detector

Java + Spring      →  Spring detector
Java + Quarkus     →  Quarkus detector

Same language, different frameworks = different detectors.
Same framework concept (HTTP route), different languages = same annotation.
```

If we merge language + framework detection, adding Spring support means modifying the Java adapter. With three layers, adding Spring means writing `frameworks/spring_boot.py` — the Java adapter doesn't change.

```
                    Language Adapters          Framework Detectors
                    ────────────────          ────────────────────
                    python_adapter.py          django_ninja.py
                    java_adapter.py      ×     celery.py
                    go_adapter.py              spring_boot.py
                    js_adapter.py              express.py
                                               go_http.py
                                               grpc.py

          M languages × N frameworks = M + N files (not M × N)
```

This is the scaling property. 5 languages + 10 frameworks = 15 files, not 50.

---

## Layer 1: Tree-sitter — The Universal Syntax Parser

### What Tree-sitter Gives Us

```python
import tree_sitter_python as tspython
from tree_sitter import Language, Parser

PY_LANGUAGE = Language(tspython.language())
parser = Parser(PY_LANGUAGE)

source = b'''
@celery_app.task(queue="server")
def process_data(sensor_ids):
    """Process sensor data."""
    results = Sensor.objects.filter(id__in=sensor_ids)
    if not results:
        logger.warning("No sensors found")
        return
    for sensor in results:
        trigger_analysis.delay(sensor.id)
'''

tree = parser.parse(source)
```

Tree-sitter produces a Concrete Syntax Tree (CST):

```
module
├── decorated_definition
│   ├── decorator
│   │   └── call
│   │       ├── attribute
│   │       │   ├── identifier: "celery_app"
│   │       │   └── identifier: "task"
│   │       └── argument_list
│   │           └── keyword_argument
│   │               ├── identifier: "queue"
│   │               └── string: "server"
│   └── function_definition
│       ├── identifier: "process_data"
│       ├── parameters
│       │   └── identifier: "sensor_ids"
│       ├── string: "Process sensor data."     (docstring)
│       └── block
│           ├── assignment                      (results = ...)
│           ├── if_statement                    (if not results)
│           │   ├── not_operator
│           │   ├── block (logger.warning, return)
│           │   └── (no else)
│           └── for_statement                   (for sensor in results)
│               └── block
│                   └── expression_statement
│                       └── call
│                           ├── attribute
│                           │   ├── identifier: "trigger_analysis"
│                           │   └── identifier: "delay"
│                           └── argument_list
```

This is language-specific structure. The Java CST for similar code would look completely different (method_declaration, annotation, etc.). That's Layer 2's problem.

### Why Not Just Use AST Per Language?

| Approach | Pros | Cons |
|----------|------|------|
| Python `ast` module | Zero deps, high-level, Pythonic | Python only. Forever. |
| Java `javalang` | Easy for Java | Java only. Unmaintained. |
| Go `go/ast` | Native Go parsing | Only works from Go code |
| **Tree-sitter** | **All languages. One tool. Community-maintained. Incremental. Error-tolerant.** | Lower-level (CST not AST). Need to write queries. |

Tree-sitter also gives us:

- **Incremental parsing:** Change 1 line → re-parse only the affected region, not the whole file. Critical for editor integration.
- **Error tolerance:** Can parse broken/incomplete code (half-written function). Returns partial tree. Other parsers throw `SyntaxError`.
- **Web Assembly:** Tree-sitter runs in the browser via WASM. This means the VS Code webview can do parsing client-side in the future.

### Grammar Updates and Language Evolution

When Python 3.13 adds `match/case` improvements or Java 21 adds record patterns:

1. Tree-sitter community updates the grammar (usually within days of language release)
2. We run `pip install --upgrade tree-sitter-python`
3. Our Language Adapter queries MIGHT need updating if we want to extract the new pattern
4. The graph layer, LLM layer, render layer — untouched

If we don't update the adapter, the new syntax still parses (Tree-sitter handles it). We just don't extract semantic meaning from it yet. **Graceful degradation, not failure.**

---

## Layer 2: Language Adapters — CST to Uniform IR

### The Protocol

```python
from typing import Protocol

class LanguageAdapter(Protocol):
    """Extracts structured data from a Tree-sitter CST."""

    language_id: str                    # "python", "java", "go", "javascript"
    file_extensions: set[str]           # {".py"}, {".java"}, {".go"}, {".js", ".ts"}

    def extract_functions(self, tree, source: bytes) -> list[ParsedFunction]:
        """Extract all function/method definitions."""
        ...

    def extract_classes(self, tree, source: bytes) -> list[str]:
        """Extract all class definitions."""
        ...

    def extract_imports(self, tree, source: bytes) -> list[ParsedImport]:
        """Extract all import statements."""
        ...

    def extract_calls(self, node, source: bytes) -> list[FunctionCall]:
        """Extract all function calls within a given node (function body)."""
        ...

    def extract_decorators(self, node, source: bytes) -> list[dict]:
        """Extract decorators/annotations from a definition node."""
        ...

    def extract_branches(self, node, source: bytes) -> list[ConditionalBranch]:
        """Extract conditional branches (if/else/switch/match)."""
        ...

    def resolve_import_path(self, imp: ParsedImport, project_root: str) -> Optional[str]:
        """Resolve an import to a file path."""
        ...
```

### Tree-sitter Queries (The Extraction Engine)

Tree-sitter has a query language using S-expressions. This is how we extract patterns WITHOUT walking the tree manually:

**Python adapter queries:**

```scheme
;; Find all function definitions
(function_definition
  name: (identifier) @func.name
  parameters: (parameters) @func.params
  body: (block) @func.body
) @func.def

;; Find all decorated functions
(decorated_definition
  (decorator) @decorator
  definition: (function_definition
    name: (identifier) @func.name
  ) @func.def
) @decorated

;; Find all method calls: something.method(args)
(call
  function: (attribute
    object: (_) @call.receiver
    attribute: (identifier) @call.method
  )
  arguments: (argument_list) @call.args
) @method_call

;; Find all plain function calls: func(args)
(call
  function: (identifier) @call.name
  arguments: (argument_list) @call.args
) @func_call

;; Find imports: from X import Y
(import_from_statement
  module_name: (dotted_name) @import.module
  name: (dotted_name (identifier) @import.name)
) @import

;; Find if/else branches
(if_statement
  condition: (_) @if.condition
  consequence: (block) @if.body
  alternative: (else_clause (block) @else.body)?
) @if_stmt
```

**Java adapter queries:**

```scheme
;; Find all method declarations
(method_declaration
  (modifiers)? @method.modifiers
  type: (_) @method.return_type
  name: (identifier) @method.name
  parameters: (formal_parameters) @method.params
  body: (block) @method.body
) @method.def

;; Find annotations (Java's version of decorators)
(annotation
  name: (identifier) @annotation.name
  arguments: (annotation_argument_list)? @annotation.args
) @annotation

;; Find method invocations
(method_invocation
  object: (_)? @call.receiver
  name: (identifier) @call.method
  arguments: (argument_list) @call.args
) @method_call

;; Find imports
(import_declaration
  (scoped_identifier) @import.path
) @import
```

**Go adapter queries:**

```scheme
;; Find function declarations
(function_declaration
  name: (identifier) @func.name
  parameters: (parameter_list) @func.params
  body: (block) @func.body
) @func.def

;; Find method declarations (with receiver)
(method_declaration
  receiver: (parameter_list) @method.receiver
  name: (field_identifier) @method.name
  parameters: (parameter_list) @method.params
  body: (block) @method.body
) @method.def

;; Find go routines (async boundary)
(go_statement
  (call_expression
    function: (_) @goroutine.func
  )
) @goroutine

;; Find imports
(import_spec
  path: (interpreted_string_literal) @import.path
) @import
```

### What Each Adapter Produces

Regardless of language, every adapter outputs the SAME `ParsedModule`:

```
Python: def process_data(ids):        →  ParsedFunction(name="process_data", ...)
Java:   public void processData(ids)  →  ParsedFunction(name="processData", ...)
Go:     func ProcessData(ids []int)   →  ParsedFunction(name="ProcessData", ...)

Python: from tasks import run         →  ParsedImport(module="tasks", name="run")
Java:   import com.tasks.Run          →  ParsedImport(module="com.tasks", name="Run")
Go:     import "myapp/tasks"          →  ParsedImport(module="myapp/tasks", name="tasks")

Python: task.delay(id)                →  FunctionCall(name="delay", receiver="task",
                                                       is_async_dispatch=True)
Java:   executor.submit(task)         →  FunctionCall(name="submit", receiver="executor",
                                                       is_async_dispatch=True)
Go:     go processItem(id)            →  FunctionCall(name="processItem",
                                                       is_async_dispatch=True)
```

The graph layer sees `ParsedFunction`, `FunctionCall`, `ParsedImport` — never Python AST nodes, Java method declarations, or Go function signatures.

---

## Layer 3: Framework Detectors — What Patterns Mean

### The Protocol

```python
class FrameworkDetector(Protocol):
    """Detects framework-specific patterns in parsed modules."""

    framework_id: str                   # "django_ninja", "celery", "spring_boot"
    languages: set[str]                 # {"python"}, {"java"}, {"python", "javascript"}

    def detect_entry_points(self, module: ParsedModule) -> list[EntryPoint]:
        """Find framework-specific entry points in a module."""
        ...

    def detect_async_boundaries(self, call: FunctionCall) -> Optional[AsyncBoundaryType]:
        """Check if a function call is an async dispatch."""
        ...

    def annotate_operations(self, call: FunctionCall) -> Optional[dict]:
        """Annotate calls with framework-specific metadata (ORM ops, etc.)."""
        ...
```

### How Detectors Work

Detectors examine the IR (ParsedModule), not the source code. They look at decorators, function names, and call patterns:

```python
class CeleryDetector:
    framework_id = "celery"
    languages = {"python"}

    TASK_DECORATORS = {"celery_app.task", "shared_task", "app.task"}
    ASYNC_METHODS = {"delay": AsyncBoundaryType.CELERY_DELAY,
                     "apply_async": AsyncBoundaryType.CELERY_APPLY_ASYNC}
    ORCHESTRATION = {"chain": AsyncBoundaryType.CELERY_CHAIN,
                     "chord": AsyncBoundaryType.CELERY_CHORD,
                     "group": AsyncBoundaryType.CELERY_GROUP}

    def detect_entry_points(self, module: ParsedModule) -> list[EntryPoint]:
        entries = []
        for func in module.functions:
            for dec in func.decorators:
                if dec in self.TASK_DECORATORS:
                    entries.append(EntryPoint(
                        node_id=func.qualified_name,
                        type=EntryPointType.CELERY_TASK,
                        trigger=f"Celery task: {func.name}",
                    ))
        return entries
```

```python
class SpringBootDetector:
    framework_id = "spring_boot"
    languages = {"java"}

    CONTROLLER_ANNOTATIONS = {"RestController", "Controller"}
    ROUTE_ANNOTATIONS = {"GetMapping", "PostMapping", "PutMapping",
                         "DeleteMapping", "RequestMapping"}
    ASYNC_ANNOTATIONS = {"Async"}

    def detect_entry_points(self, module: ParsedModule) -> list[EntryPoint]:
        entries = []
        for func in module.functions:
            for dec in func.decorators:
                if dec in self.ROUTE_ANNOTATIONS:
                    http_method = dec.replace("Mapping", "").upper()
                    entries.append(EntryPoint(
                        node_id=func.qualified_name,
                        type=EntryPointType.API_ROUTE,
                        trigger=f"{http_method} {self._extract_path(func)}",
                    ))
        return entries
```

Notice: both detectors produce the same `EntryPoint` type. The graph layer doesn't know if it came from a `@route.get` or a `@GetMapping`.

### Composability

Multiple detectors run on the same module:

```python
def analyze_module(module: ParsedModule, detectors: list[FrameworkDetector]):
    all_entry_points = []
    for detector in detectors:
        if module.language in detector.languages:
            all_entry_points.extend(detector.detect_entry_points(module))
    return all_entry_points

# A Python/Django/Celery file gets analyzed by all three
detectors = [DjangoNinjaDetector(), CeleryDetector(), DjangoSignalDetector()]
entry_points = analyze_module(module, detectors)
```

---

## Registration & Auto-Discovery

### Language Registry

```python
class LanguageRegistry:
    """Maps file extensions to language adapters."""

    _adapters: dict[str, LanguageAdapter] = {}

    def register(self, adapter: LanguageAdapter):
        for ext in adapter.file_extensions:
            self._adapters[ext] = adapter

    def get_adapter(self, file_path: str) -> Optional[LanguageAdapter]:
        ext = Path(file_path).suffix
        return self._adapters.get(ext)

# Registration happens at startup
registry = LanguageRegistry()
registry.register(PythonAdapter())
registry.register(JavaAdapter())       # When we add Java
registry.register(GoAdapter())         # When we add Go
```

### Framework Registry

```python
class FrameworkRegistry:
    """Manages framework detectors."""

    _detectors: list[FrameworkDetector] = []

    def register(self, detector: FrameworkDetector):
        self._detectors.append(detector)

    def get_detectors(self, language: str) -> list[FrameworkDetector]:
        return [d for d in self._detectors if language in d.languages]

# Registration
fw_registry = FrameworkRegistry()
fw_registry.register(DjangoNinjaDetector())
fw_registry.register(CeleryDetector())
fw_registry.register(DjangoSignalDetector())
fw_registry.register(DjangoORMDetector())
# Future:
fw_registry.register(SpringBootDetector())
fw_registry.register(ExpressDetector())
```

### Auto-Discovery (Future)

Instead of manual registration, scan for plugins:

```python
# cartograph/parser/languages/python_adapter.py
class PythonAdapter:
    language_id = "python"
    file_extensions = {".py"}
    ...

# At startup, scan cartograph/parser/languages/ for all classes
# implementing LanguageAdapter and register them automatically.
# Same for frameworks/.
```

---

## The Parse Pipeline

```python
def parse_project(root_path: str, config: CartographConfig) -> ProjectIndex:
    """Full parse pipeline: files → CST → IR → annotated IR."""

    lang_registry = LanguageRegistry()
    lang_registry.register(PythonAdapter())
    # Future: register more languages

    fw_registry = FrameworkRegistry()
    fw_registry.register(DjangoNinjaDetector())
    fw_registry.register(CeleryDetector())
    fw_registry.register(DjangoSignalDetector())
    fw_registry.register(DjangoORMDetector())

    index = ProjectIndex(root_path=root_path)

    for file_path in discover_files(root_path, config.exclude_dirs):
        # Layer 1 + 2: Parse file with appropriate language adapter
        adapter = lang_registry.get_adapter(file_path)
        if not adapter:
            continue  # Unknown language, skip

        module = adapter.parse_file(file_path)
        if not module:
            continue  # Parse error, skip (graceful degradation)

        # Layer 3: Run framework detectors
        detectors = fw_registry.get_detectors(adapter.language_id)
        for detector in detectors:
            entry_points = detector.detect_entry_points(module)
            index.entry_points.extend(entry_points)

            # Annotate calls with async boundaries and ORM ops
            for func in module.functions:
                for call in func.calls:
                    async_type = detector.detect_async_boundaries(call)
                    if async_type:
                        call.is_async_dispatch = True
                        call.async_type = async_type

                    orm_annotation = detector.annotate_operations(call)
                    if orm_annotation:
                        func.annotations.update(orm_annotation)

        index.modules[module.module_path] = module

    return index
```

---

## Migration Path: Current AST → Tree-sitter

We don't rewrite today. We migrate incrementally:

```
Phase 1 (NOW):
  PythonAdapter uses stdlib `ast` module internally
  Implements the LanguageAdapter protocol
  Framework detectors already work on ParsedModule IR

Phase 2 (when adding second language):
  Install tree-sitter + tree-sitter-java
  Write JavaAdapter using Tree-sitter queries
  JavaAdapter implements same LanguageAdapter protocol
  Framework detectors for Spring Boot work on same IR

Phase 3 (optional, when needed):
  Migrate PythonAdapter from stdlib `ast` to Tree-sitter
  Benefits: incremental parsing, error tolerance, WASM for browser
  Risk: low — IR doesn't change, only internal extraction method

The graph layer never changes. The LLM layer never changes.
The CLI never changes. The VS Code extension never changes.
```

---

## Scaling Scenarios

### Scenario 1: "Add Java support"

```
Write: languages/java_adapter.py (~300 lines)
Write: frameworks/spring_boot.py (~150 lines)
Install: pip install tree-sitter-java
Change: Nothing else. Zero modifications to existing code.
```

### Scenario 2: "Python 3.14 adds new syntax"

```
Update: pip install --upgrade tree-sitter-python
Maybe update: languages/python_adapter.py (only if we want to extract the new pattern)
Change: Nothing else.
```

### Scenario 3: "Django 6 changes decorator API"

```
Update: frameworks/django_ninja.py (update decorator patterns)
Change: Nothing else. Language adapter, graph layer untouched.
```

### Scenario 4: "Add gRPC support across all languages"

```
Write: frameworks/grpc.py (~150 lines)
  - Detects service definitions, RPC methods
  - Works on ParsedModule from ANY language adapter
  - One file handles Python gRPC, Java gRPC, Go gRPC
Change: Nothing else.
```

### Scenario 5: "10,000 file monorepo is slow"

```
Fix: Cache layer (file hash based)
Fix: Parallel parsing (each file is independent)
Fix: Incremental Tree-sitter (re-parse only changed regions)
Change: Parse pipeline, not adapters or detectors.
```

---

## What Can Go Wrong (And Why It Won't Kill Us)

| Risk | Impact | Why It's Contained |
|------|--------|-------------------|
| Tree-sitter grammar has a bug | One language's parsing breaks | Other languages unaffected. Downgrade grammar version. |
| Language adapter query misses a pattern | Some functions not extracted | Graceful degradation. Graph is incomplete, not wrong. |
| Framework detector has false positive | Wrong entry point detected | User can exclude via config. Doesn't corrupt graph structure. |
| New language has paradigm we didn't anticipate (e.g., Haskell pattern matching) | Adapter can't express it in current IR | Extend IR (add new fields to ParsedFunction). Existing adapters ignore new fields. |
| Tree-sitter WASM doesn't work in VS Code webview | Client-side parsing fails | Fall back to server-side parsing. The backend already does this. |

The architecture's resilience comes from the IR boundary. Everything above it (language-specific) can break without affecting everything below it (universal graph logic). And everything below it can evolve without changing what's above.

---

## Summary

```
STABLE (universal, rarely changes):
  ├── ParsedModule, ParsedFunction, FunctionCall (IR)
  ├── CallGraph, FlowDAG (graph models)
  ├── Graph Builder, DAG Builder (graph algorithms)
  ├── Serializer (JSON, Mermaid)
  ├── CLI, VS Code Extension, Web UI (consumers)
  └── LLM Layer (story generation, annotation)

PLUGGABLE (per-language, per-framework):
  ├── Language Adapters (Python, Java, Go, JS, ...)
  ├── Framework Detectors (Django, Celery, Spring, Express, ...)
  └── Tree-sitter Grammars (community-maintained packages)

The rule: adding a language = adding a plugin.
The rule: updating a language = updating a package.
The rule: the graph layer never knows which language it's working with.
```
