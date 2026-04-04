"""Core AST parser — extracts functions, calls, decorators, branches from Python files."""

import ast
import hashlib
from pathlib import Path
from typing import Optional

from cartograph.graph.models import (
    AsyncBoundaryType,
    ConditionalBranch,
    FunctionCall,
    NodeType,
    ParsedFunction,
    ParsedImport,
    ParsedModule,
)


ASYNC_DISPATCH_METHODS = {
    "delay": AsyncBoundaryType.CELERY_DELAY,
    "apply_async": AsyncBoundaryType.CELERY_APPLY_ASYNC,
}

CELERY_ORCHESTRATION = {
    "chain": AsyncBoundaryType.CELERY_CHAIN,
    "chord": AsyncBoundaryType.CELERY_CHORD,
    "group": AsyncBoundaryType.CELERY_GROUP,
}

ORM_READ_METHODS = {"filter", "get", "all", "values", "values_list", "first", "last",
                     "exists", "count", "aggregate", "annotate", "select_related",
                     "prefetch_related", "order_by", "distinct", "exclude"}

ORM_WRITE_METHODS = {"create", "save", "bulk_create", "bulk_update", "update",
                      "delete", "get_or_create", "update_or_create"}


class FunctionCallExtractor(ast.NodeVisitor):
    """Extracts all function/method calls from a function body."""

    def __init__(self):
        self.calls: list[FunctionCall] = []
        self.branches: list[ConditionalBranch] = []
        self._current_branch: Optional[ConditionalBranch] = None

    def visit_Call(self, node: ast.Call) -> None:
        call = self._extract_call(node)
        if call:
            if self._current_branch is not None:
                self._current_branch.calls.append(call)
            else:
                self.calls.append(call)
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        condition = self._get_source_segment(node.test)

        if_branch = ConditionalBranch(
            condition=condition,
            line=node.lineno,
        )
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

    def _extract_call(self, node: ast.Call) -> Optional[FunctionCall]:
        if isinstance(node.func, ast.Name):
            name = node.func.id
            if name in CELERY_ORCHESTRATION:
                return FunctionCall(
                    name=name,
                    line=node.lineno,
                    is_async_dispatch=True,
                    async_type=CELERY_ORCHESTRATION[name],
                    args_count=len(node.args),
                )
            return FunctionCall(
                name=name,
                line=node.lineno,
                args_count=len(node.args),
            )

        elif isinstance(node.func, ast.Attribute):
            method_name = node.func.attr
            receiver = self._get_receiver_name(node.func.value)

            is_async = method_name in ASYNC_DISPATCH_METHODS
            async_type = ASYNC_DISPATCH_METHODS.get(method_name)

            is_s_call = method_name == "s" or method_name == "si"

            return FunctionCall(
                name=method_name,
                line=node.lineno,
                is_method_call=True,
                receiver=receiver,
                is_async_dispatch=is_async or is_s_call,
                async_type=async_type,
                args_count=len(node.args),
            )

        return None

    def _get_receiver_name(self, node: ast.expr) -> Optional[str]:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            parent = self._get_receiver_name(node.value)
            if parent:
                return f"{parent}.{node.attr}"
            return node.attr
        elif isinstance(node, ast.Call):
            return self._get_receiver_name(node.func)
        return None

    def _get_source_segment(self, node: ast.expr) -> Optional[str]:
        try:
            return ast.dump(node)
        except Exception:
            return None


class ModuleParser(ast.NodeVisitor):
    """Parses a Python module and extracts all relevant information."""

    def __init__(self, file_path: str, module_path: str):
        self.file_path = file_path
        self.module_path = module_path
        self.functions: list[ParsedFunction] = []
        self.classes: list[str] = []
        self.imports: list[ParsedImport] = []
        self._current_class: Optional[str] = None
        self._source_lines: list[str] = []

    def parse(self, source: str) -> ParsedModule:
        self._source_lines = source.splitlines()
        tree = ast.parse(source, filename=self.file_path)
        self.visit(tree)

        file_hash = hashlib.md5(source.encode()).hexdigest()

        return ParsedModule(
            file_path=self.file_path,
            module_path=self.module_path,
            functions=self.functions,
            classes=self.classes,
            imports=self.imports,
            file_hash=file_hash,
        )

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(ParsedImport(
                module=alias.name,
                name=alias.name.split(".")[-1],
                alias=alias.asname,
            ))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for alias in node.names:
            self.imports.append(ParsedImport(
                module=module,
                name=alias.name,
                alias=alias.asname,
                is_relative=node.level > 0,
                level=node.level,
            ))

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.classes.append(node.name)
        self._current_class = node.name

        decorators = self._extract_decorators(node)
        decorator_details = self._extract_decorator_details(node)

        class_func = ParsedFunction(
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
        self.functions.append(class_func)

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

        call_extractor = FunctionCallExtractor()
        for stmt in node.body:
            call_extractor.visit(stmt)

        func = ParsedFunction(
            name=name,
            qualified_name=qualified_name,
            file_path=self.file_path,
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
            type=node_type,
            docstring=ast.get_docstring(node),
            decorators=decorators,
            decorator_details=decorator_details,
            calls=call_extractor.calls,
            branches=call_extractor.branches,
            class_name=self._current_class,
            module_path=self.module_path,
        )
        self.functions.append(func)

    def _extract_decorators(self, node) -> list[str]:
        decorators = []
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name):
                decorators.append(dec.id)
            elif isinstance(dec, ast.Attribute):
                decorators.append(self._get_attribute_name(dec))
            elif isinstance(dec, ast.Call):
                if isinstance(dec.func, ast.Name):
                    decorators.append(dec.func.id)
                elif isinstance(dec.func, ast.Attribute):
                    decorators.append(self._get_attribute_name(dec.func))
        return decorators

    def _extract_decorator_details(self, node) -> list[dict]:
        details = []
        for dec in node.decorator_list:
            detail = {"raw": ast.dump(dec)}

            if isinstance(dec, ast.Call):
                if isinstance(dec.func, ast.Name):
                    detail["name"] = dec.func.id
                elif isinstance(dec.func, ast.Attribute):
                    detail["name"] = self._get_attribute_name(dec.func)

                detail["args"] = []
                for arg in dec.args:
                    if isinstance(arg, ast.Constant):
                        detail["args"].append(arg.value)

                detail["kwargs"] = {}
                for kw in dec.keywords:
                    if kw.arg and isinstance(kw.value, ast.Constant):
                        detail["kwargs"][kw.arg] = kw.value.value

            elif isinstance(dec, ast.Name):
                detail["name"] = dec.id
            elif isinstance(dec, ast.Attribute):
                detail["name"] = self._get_attribute_name(dec)

            details.append(detail)
        return details

    def _get_attribute_name(self, node: ast.Attribute) -> str:
        if isinstance(node.value, ast.Name):
            return f"{node.value.id}.{node.attr}"
        elif isinstance(node.value, ast.Attribute):
            return f"{self._get_attribute_name(node.value)}.{node.attr}"
        return node.attr


def parse_file(file_path: str, module_path: str) -> Optional[ParsedModule]:
    """Parse a single Python file and return structured data."""
    path = Path(file_path)
    if not path.exists() or not path.suffix == ".py":
        return None

    try:
        source = path.read_text(encoding="utf-8")
        parser = ModuleParser(file_path=str(path), module_path=module_path)
        return parser.parse(source)
    except SyntaxError:
        return None


def parse_directory(
    root_path: str,
    exclude_dirs: Optional[set[str]] = None,
) -> list[ParsedModule]:
    """Parse all Python files in a directory tree."""
    if exclude_dirs is None:
        exclude_dirs = {
            "__pycache__", ".git", ".venv", "venv", "node_modules",
            ".eggs", "dist", "build", ".tox", ".mypy_cache",
            "migrations", ".claude",
        }

    root = Path(root_path)
    modules = []

    for py_file in root.rglob("*.py"):
        if any(excluded in py_file.parts for excluded in exclude_dirs):
            continue

        relative = py_file.relative_to(root)
        module_path = str(relative.with_suffix("")).replace("/", ".")

        parsed = parse_file(str(py_file), module_path)
        if parsed:
            modules.append(parsed)

    return modules
