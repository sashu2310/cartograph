"""Python language adapter — uses stdlib ast module.

This adapter knows Python syntax (def, class, import, decorators, if/else)
but knows NOTHING about frameworks (Django, Celery, Flask). Framework-specific
pattern detection lives in the frameworks/ subdirectory.

Migration path: when we need incremental parsing or error tolerance,
swap ast module for Tree-sitter internally. The LanguageAdapter protocol
and all consumers remain unchanged.
"""

import ast
import hashlib
from pathlib import Path

from cartograph.graph.models import (
    ConditionalBranch,
    FunctionCall,
    NodeType,
    ParsedFunction,
    ParsedImport,
    ParsedModule,
)


class _CallExtractor(ast.NodeVisitor):
    """Extracts function/method calls and conditional branches from a function body."""

    def __init__(self):
        self.calls: list[FunctionCall] = []
        self.branches: list[ConditionalBranch] = []
        self.local_types: dict[str, str] = {}
        self._current_branch: ConditionalBranch | None = None

    def visit_Assign(self, node: ast.Assign) -> None:
        """Track variable types from constructor calls: x = Foo() → x: Foo."""
        if (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
        ):
            var_name = node.targets[0].id
            call_func = node.value.func
            if isinstance(call_func, ast.Name):
                # x = Foo()
                self.local_types[var_name] = call_func.id
            elif isinstance(call_func, ast.Attribute) and isinstance(
                call_func.value, ast.Name
            ):
                # x = module.Foo()
                self.local_types[var_name] = f"{call_func.value.id}.{call_func.attr}"
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Track type annotations: x: Foo = ... → x: Foo."""
        if isinstance(node.target, ast.Name) and isinstance(node.annotation, ast.Name):
            self.local_types[node.target.id] = node.annotation.id
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        call = self._extract_call(node)
        if call:
            if self._current_branch is not None:
                self._current_branch.calls.append(call)
            else:
                self.calls.append(call)
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        condition = self._unparse_condition(node.test)

        # Extract calls from the condition expression (e.g., "if validate(data):")
        self.visit(node.test)

        if_branch = ConditionalBranch(condition=condition, line=node.lineno)
        self._current_branch = if_branch
        for stmt in node.body:
            self.visit(stmt)
        self._current_branch = None
        self.branches.append(if_branch)

        if node.orelse:
            else_branch = ConditionalBranch(
                condition=f"not ({condition})" if condition else None,
                line=node.lineno,
                is_else=True,
            )
            self._current_branch = else_branch
            for stmt in node.orelse:
                self.visit(stmt)
            self._current_branch = None
            self.branches.append(else_branch)

    def _extract_call(self, node: ast.Call) -> FunctionCall | None:
        if isinstance(node.func, ast.Name):
            return FunctionCall(
                name=node.func.id,
                line=node.lineno,
                args_count=len(node.args),
            )

        elif isinstance(node.func, ast.Attribute):
            method_name = node.func.attr
            receiver = self._get_receiver(node.func.value)

            return FunctionCall(
                name=method_name,
                line=node.lineno,
                is_method_call=True,
                receiver=receiver,
                args_count=len(node.args),
            )

        return None

    def _get_receiver(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            parent = self._get_receiver(node.value)
            return f"{parent}.{node.attr}" if parent else node.attr
        elif isinstance(node, ast.Call):
            return self._get_receiver(node.func)
        return None

    def _unparse_condition(self, node: ast.expr) -> str | None:
        try:
            return ast.unparse(node)
        except Exception:
            try:
                return ast.dump(node)
            except Exception:
                return None


class _ModuleVisitor(ast.NodeVisitor):
    """Visits a Python module AST and extracts structured data."""

    def __init__(self, file_path: str, module_path: str):
        self.file_path = file_path
        self.module_path = module_path
        self.functions: list[ParsedFunction] = []
        self.classes: list[str] = []
        self.imports: list[ParsedImport] = []
        self._current_class: str | None = None

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(
                ParsedImport(
                    module=alias.name,
                    name=alias.name.split(".")[-1],
                    alias=alias.asname,
                )
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for alias in node.names:
            self.imports.append(
                ParsedImport(
                    module=module,
                    name=alias.name,
                    alias=alias.asname,
                    is_relative=node.level > 0,
                    level=node.level,
                )
            )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.classes.append(node.name)
        self._current_class = node.name

        decorators = self._extract_decorators(node)
        decorator_details = self._extract_decorator_details(node)

        self.functions.append(
            ParsedFunction(
                name=node.name,
                qualified_name=f"{self.module_path}.{node.name}",
                file_path=self.file_path,
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                type=NodeType.CLASS,
                docstring=ast.get_docstring(node),
                decorators=decorators,
                decorator_details=decorator_details,
                module_path=self.module_path,
            )
        )

        self.generic_visit(node)
        self._current_class = None

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._parse_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._parse_function(node)

    def _parse_function(self, node) -> None:
        decorators = self._extract_decorators(node)
        decorator_details = self._extract_decorator_details(node)

        if self._current_class:
            name = f"{self._current_class}.{node.name}"
            qualified_name = f"{self.module_path}.{self._current_class}.{node.name}"
            node_type = NodeType.METHOD
        else:
            name = node.name
            qualified_name = f"{self.module_path}.{node.name}"
            node_type = NodeType.FUNCTION

        extractor = _CallExtractor()
        for stmt in node.body:
            extractor.visit(stmt)

        self.functions.append(
            ParsedFunction(
                name=name,
                qualified_name=qualified_name,
                file_path=self.file_path,
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                type=node_type,
                docstring=ast.get_docstring(node),
                decorators=decorators,
                decorator_details=decorator_details,
                calls=extractor.calls,
                branches=extractor.branches,
                class_name=self._current_class,
                module_path=self.module_path,
                local_types=extractor.local_types,
            )
        )

    def _extract_decorators(self, node) -> list[str]:
        decorators = []
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name):
                decorators.append(dec.id)
            elif isinstance(dec, ast.Attribute):
                decorators.append(self._attr_name(dec))
            elif isinstance(dec, ast.Call):
                if isinstance(dec.func, ast.Name):
                    decorators.append(dec.func.id)
                elif isinstance(dec.func, ast.Attribute):
                    decorators.append(self._attr_name(dec.func))
        return decorators

    def _extract_decorator_details(self, node) -> list[dict]:
        details = []
        for dec in node.decorator_list:
            detail: dict = {}

            if isinstance(dec, ast.Call):
                if isinstance(dec.func, ast.Name):
                    detail["name"] = dec.func.id
                elif isinstance(dec.func, ast.Attribute):
                    detail["name"] = self._attr_name(dec.func)
                detail["args"] = [
                    arg.value for arg in dec.args if isinstance(arg, ast.Constant)
                ]
                detail["kwargs"] = {
                    kw.arg: kw.value.value
                    for kw in dec.keywords
                    if kw.arg and isinstance(kw.value, ast.Constant)
                }
            elif isinstance(dec, ast.Name):
                detail["name"] = dec.id
            elif isinstance(dec, ast.Attribute):
                detail["name"] = self._attr_name(dec)

            if detail:
                details.append(detail)
        return details

    def _attr_name(self, node: ast.Attribute) -> str:
        if isinstance(node.value, ast.Name):
            return f"{node.value.id}.{node.attr}"
        elif isinstance(node.value, ast.Attribute):
            return f"{self._attr_name(node.value)}.{node.attr}"
        return node.attr


class PythonAdapter:
    """Python language adapter using stdlib ast module.

    Implements the LanguageAdapter protocol. Extracts functions, classes,
    imports, calls, decorators, and conditional branches from Python files.
    Framework-specific semantics (Celery tasks, Django routes) are NOT
    handled here — those are in frameworks/*.py detectors.
    """

    language_id: str = "python"
    file_extensions: set[str] = frozenset({".py"})

    def parse_file(self, file_path: str, module_path: str) -> ParsedModule | None:
        path = Path(file_path)
        if not path.exists() or path.suffix != ".py":
            return None

        try:
            source = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return None

        try:
            visitor = _ModuleVisitor(file_path=str(path), module_path=module_path)
            tree = ast.parse(source, filename=file_path)
            visitor.visit(tree)

            return ParsedModule(
                file_path=str(path),
                module_path=module_path,
                functions=visitor.functions,
                classes=visitor.classes,
                imports=visitor.imports,
                file_hash=hashlib.md5(source.encode()).hexdigest(),
            )
        except SyntaxError:
            return None

    def resolve_import(
        self, imp: ParsedImport, source_file: str, project_root: str
    ) -> str | None:
        root = Path(project_root)

        if imp.is_relative:
            source_dir = Path(source_file).parent
            levels_up = imp.level - 1
            base = source_dir
            for _ in range(levels_up):
                base = base.parent

            target = base / imp.module.replace(".", "/") if imp.module else base
        else:
            target = root / imp.module.replace(".", "/")

        # Check: package/module.py
        module_file = target.with_suffix(".py")
        if module_file.exists():
            return str(module_file)

        # Check: package/__init__.py (it's a package, look for name inside)
        init_file = target / "__init__.py"
        if init_file.exists():
            # The imported name might be in __init__.py or a submodule
            submodule = target / f"{imp.name}.py"
            if submodule.exists():
                return str(submodule)
            return str(init_file)

        return None
