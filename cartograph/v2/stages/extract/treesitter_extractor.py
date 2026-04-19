"""Tree-sitter-backed Extractor — alternative to AstExtractor.

Error-tolerant (partial syntax still yields extracted functions) at the cost
of branch-condition tracking, which this extractor omits — all call sites
come back with condition=None.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import tree_sitter_python
from tree_sitter import Language, Node, Parser

from cartograph.v2.ir.base import Err_, Ok
from cartograph.v2.ir.errors import (
    EncodingExtractError,
    ExtractError,
    IoExtractError,
)
from cartograph.v2.ir.syntactic import (
    AsyncDispatchCall,
    AsyncFunction,
    AsyncOrchestrationCall,
    CallSite,
    DecoratorSpec,
    ImportStmt,
    MethodCall,
    PlainCall,
    SyncFunction,
    SyntacticClass,
    SyntacticFunction,
    SyntacticModule,
)

_DISPATCH_METHODS = {"delay", "apply_async"}
_ORCHESTRATION_NAMES = {"chain", "chord", "group"}


class TreesitterExtractor:
    language_id: str = "python"
    file_extensions: frozenset[str] = frozenset({".py"})

    def __init__(self) -> None:
        self._language = Language(tree_sitter_python.language())
        self._parser = Parser(self._language)

    def extract(
        self, path: Path, module_name: str
    ) -> Ok[SyntacticModule] | Err_[ExtractError]:
        try:
            source = path.read_bytes()
        except FileNotFoundError:
            return Err_(error=IoExtractError(path=path, detail="file not found"))
        except OSError as exc:
            return Err_(error=IoExtractError(path=path, detail=str(exc)))

        try:
            source.decode("utf-8")
        except UnicodeDecodeError as exc:
            return Err_(error=EncodingExtractError(path=path, detail=str(exc)))

        tree = self._parser.parse(source)
        walker = _Walker(source, module_name)
        walker.walk_module(tree.root_node)

        return Ok(
            value=SyntacticModule(
                path=path,
                module_name=module_name,
                content_hash=hashlib.sha256(source).hexdigest(),
                imports=tuple(walker.imports),
                classes=tuple(walker.classes),
                functions=tuple(walker.functions),
            )
        )


class _Walker:
    def __init__(self, source: bytes, module_name: str) -> None:
        self._source = source
        self.module_name = module_name
        self.imports: list[ImportStmt] = []
        self.classes: list[SyntacticClass] = []
        self.functions: list[SyntacticFunction] = []
        self._current_class: str | None = None

    def walk_module(self, root: Node) -> None:
        for child in root.children:
            self._dispatch(child)

    def _dispatch(self, node: Node) -> None:
        t = node.type
        if t == "import_statement":
            self._extract_import(node, is_from=False)
        elif t == "import_from_statement":
            self._extract_import(node, is_from=True)
        elif t == "class_definition":
            self._extract_class(node, decorators=())
        elif t in ("function_definition", "async_function_definition"):
            self._extract_function(
                node, decorators=(), is_async=(t == "async_function_definition")
            )
        elif t == "decorated_definition":
            self._extract_decorated(node)
        # Other top-level statements (assignments, expressions) are ignored.

    def _extract_import(self, node: Node, *, is_from: bool) -> None:
        if is_from:
            module_name = self._child_text_by_field(node, "module_name") or ""
            # Relative import level: count leading dots in the module name.
            level = 0
            for ch in module_name:
                if ch == ".":
                    level += 1
                else:
                    break
            is_relative = level > 0
            module = module_name.lstrip(".")
            for dotted_name in self._iter_dotted_names(node, field="name"):
                name, alias = self._name_and_alias(dotted_name)
                self.imports.append(
                    ImportStmt(
                        module=module,
                        name=name,
                        alias=alias,
                        is_relative=is_relative,
                        level=level,
                    )
                )
        else:
            for dotted_name in self._iter_dotted_names(node, field="name"):
                name, alias = self._name_and_alias(dotted_name)
                self.imports.append(
                    ImportStmt(
                        module=name or "",
                        name=None,
                        alias=alias,
                        is_relative=False,
                        level=0,
                    )
                )

    def _iter_dotted_names(self, node: Node, *, field: str):
        """Yield nodes under a repeated field (import names are comma-separated)."""
        for i in range(node.named_child_count):
            child = node.named_child(i)
            if child is None:
                continue
            # Tree-sitter doesn't expose field names per-child directly without
            # cursor; we inspect by type. Import names appear as dotted_name or
            # aliased_import.
            if child.type in ("dotted_name", "aliased_import"):
                yield child

    def _name_and_alias(self, node: Node) -> tuple[str, str | None]:
        if node.type == "aliased_import":
            name_node = node.child_by_field_name("name")
            alias_node = node.child_by_field_name("alias")
            name = self._text(name_node) if name_node else ""
            alias = self._text(alias_node) if alias_node else None
            return (name, alias)
        return (self._text(node), None)

    def _extract_class(
        self, node: Node, *, decorators: tuple[DecoratorSpec, ...]
    ) -> None:
        name_node = node.child_by_field_name("name")
        name = self._text(name_node) if name_node else ""
        qname = f"{self.module_name}.{name}"
        bases: list[str] = []
        args_node = node.child_by_field_name("superclasses")
        if args_node is not None:
            for i in range(args_node.named_child_count):
                child = args_node.named_child(i)
                if child is None:
                    continue
                bases.append(self._text(child))

        line_start = node.start_point[0] + 1
        line_end = node.end_point[0] + 1
        self.classes.append(
            SyntacticClass(
                qname=qname,
                name=name,
                bases=tuple(bases),
                decorators=decorators,
                line_start=line_start,
                line_end=line_end,
            )
        )

        # Recurse into class body for methods.
        body = node.child_by_field_name("body")
        if body is None:
            return
        prev = self._current_class
        self._current_class = name
        for child in body.children:
            if child.type == "decorated_definition":
                self._extract_decorated(child)
            elif child.type in ("function_definition", "async_function_definition"):
                self._extract_function(
                    child,
                    decorators=(),
                    is_async=(child.type == "async_function_definition"),
                )
            elif child.type == "class_definition":
                # Nested classes — rare but valid.
                self._extract_class(child, decorators=())
        self._current_class = prev

    def _extract_decorated(self, node: Node) -> None:
        """decorated_definition wraps (decorator*, function_definition | class_definition)."""
        decorators: list[DecoratorSpec] = []
        target: Node | None = None
        for child in node.children:
            if child.type == "decorator":
                spec = self._decorator_spec(child)
                if spec is not None:
                    decorators.append(spec)
            elif child.type in (
                "function_definition",
                "async_function_definition",
                "class_definition",
            ):
                target = child

        if target is None:
            return

        if target.type == "class_definition":
            self._extract_class(target, decorators=tuple(decorators))
        else:
            self._extract_function(
                target,
                decorators=tuple(decorators),
                is_async=(target.type == "async_function_definition"),
            )

    def _extract_function(
        self,
        node: Node,
        *,
        decorators: tuple[DecoratorSpec, ...],
        is_async: bool,
    ) -> None:
        name_node = node.child_by_field_name("name")
        name = self._text(name_node) if name_node else ""
        if self._current_class:
            qname = f"{self.module_name}.{self._current_class}.{name}"
        else:
            qname = f"{self.module_name}.{name}"

        line_start = node.start_point[0] + 1
        line_end = node.end_point[0] + 1

        body = node.child_by_field_name("body")
        call_sites: list[CallSite] = []
        docstring: str | None = None
        if body is not None:
            self._collect_calls(body, qname, call_sites)
            docstring = self._extract_docstring(body)

        ctor = AsyncFunction if is_async else SyncFunction
        self.functions.append(
            ctor(
                qname=qname,
                name=name,
                class_name=self._current_class,
                decorators=decorators,
                line_start=line_start,
                line_end=line_end,
                docstring=docstring,
                call_sites=tuple(call_sites),
            )
        )

    def _extract_docstring(self, body: Node) -> str | None:
        """Python docstring convention: the function body's first statement,
        if it's a bare string literal, is the docstring."""
        first = next(iter(body.named_children), None)
        if first is None or first.type != "expression_statement":
            return None
        expr = next(iter(first.named_children), None)
        if expr is None or expr.type != "string":
            return None
        parts = [
            self._text(c) for c in expr.named_children if c.type == "string_content"
        ]
        text = "".join(parts).strip()
        return text or None

    def _collect_calls(
        self, node: Node, caller_qname: str, out: list[CallSite]
    ) -> None:
        """Depth-first walk; every `call` node becomes a CallSite.

        Branch condition tracking is not implemented in this first cut — all
        calls are attributed at the function body level. AstExtractor's
        condition-stack approach can be ported later if tree-sitter output
        becomes canonical.
        """
        if node.type == "call":
            classified = self._classify_call(node)
            if classified is not None:
                out.append(
                    CallSite(
                        caller_qname=caller_qname,
                        call=classified,
                        condition=None,
                    )
                )
        for child in node.children:
            self._collect_calls(child, caller_qname, out)

    def _classify_call(self, node: Node):
        """Return a CallKind variant for a `call` node, or None if unparseable."""
        func_node = node.child_by_field_name("function")
        if func_node is None:
            return None
        line = node.start_point[0] + 1
        col = node.start_point[1]

        if func_node.type == "identifier":
            name = self._text(func_node)
            if name in _ORCHESTRATION_NAMES:
                return AsyncOrchestrationCall(
                    name=name,  # type: ignore[arg-type]
                    line=line,
                    col=col,
                )
            return PlainCall(name=name, line=line, col=col)

        if func_node.type == "attribute":
            chain = self._attribute_chain(func_node)
            if not chain:
                return None
            method_name = chain[-1]
            receiver = chain[0]
            full_chain = tuple(chain)

            if method_name in _DISPATCH_METHODS:
                return AsyncDispatchCall(
                    name=method_name,
                    receiver=".".join(chain[:-1]),
                    receiver_chain=full_chain,
                    dispatch_kind="delay" if method_name == "delay" else "apply_async",
                    line=line,
                    col=col,
                )

            return MethodCall(
                name=method_name,
                receiver=receiver,
                receiver_chain=full_chain,
                line=line,
                col=col,
            )
        # Other shapes (subscript, lambda, call-returning-callable) skipped.
        return None

    def _attribute_chain(self, node: Node) -> list[str]:
        """Flatten `a.b.c` into ['a', 'b', 'c']. Returns [] if the base isn't
        a simple identifier."""
        parts: list[str] = []
        cur: Node | None = node
        while cur is not None and cur.type == "attribute":
            attr_node = cur.child_by_field_name("attribute")
            if attr_node is None:
                return []
            parts.append(self._text(attr_node))
            cur = cur.child_by_field_name("object")
        if cur is None or cur.type != "identifier":
            return []
        parts.append(self._text(cur))
        parts.reverse()
        return parts

    def _decorator_spec(self, node: Node) -> DecoratorSpec | None:
        """Parse a `decorator` node into a DecoratorSpec."""
        # Decorator body is after the `@`. Structure depends on tree-sitter grammar:
        # decorator → `@` (identifier | attribute | call) newline
        body = None
        for child in node.named_children:
            body = child
            break
        if body is None:
            return None

        if body.type == "identifier":
            return DecoratorSpec(name=self._text(body))

        if body.type == "attribute":
            chain = self._attribute_chain(body)
            if not chain:
                return None
            return DecoratorSpec(name=".".join(chain))

        if body.type == "call":
            func_node = body.child_by_field_name("function")
            if func_node is None:
                return None
            if func_node.type == "identifier":
                name = self._text(func_node)
            elif func_node.type == "attribute":
                chain = self._attribute_chain(func_node)
                if not chain:
                    return None
                name = ".".join(chain)
            else:
                return None
            args, kwargs = self._parse_call_arguments(body)
            return DecoratorSpec(name=name, args=args, kwargs=kwargs)

        return None

    def _parse_call_arguments(
        self, call_node: Node
    ) -> tuple[tuple[str, ...], dict[str, str]]:
        """Extract literal-constant args and kwargs from a call node."""
        arg_list = call_node.child_by_field_name("arguments")
        if arg_list is None:
            return ((), {})
        args: list[str] = []
        kwargs: dict[str, str] = {}
        for i in range(arg_list.named_child_count):
            child = arg_list.named_child(i)
            if child is None:
                continue
            if child.type == "keyword_argument":
                name_node = child.child_by_field_name("name")
                value_node = child.child_by_field_name("value")
                if name_node is None or value_node is None:
                    continue
                literal = self._literal_text(value_node)
                if literal is not None:
                    kwargs[self._text(name_node)] = literal
            else:
                literal = self._literal_text(child)
                if literal is not None:
                    args.append(literal)
        return (tuple(args), kwargs)

    def _literal_text(self, node: Node) -> str | None:
        """Return the stringified value of a literal node, or None if non-constant."""
        if node.type == "string":
            raw = self._text(node)
            # Strip quotes. Tree-sitter gives us the surface form incl. quotes.
            if len(raw) >= 2 and raw[0] in {"'", '"'} and raw[-1] in {"'", '"'}:
                return raw[1:-1]
            return raw
        if node.type == "integer":
            return self._text(node)
        if node.type == "float":
            return self._text(node)
        if node.type == "true":
            return "True"
        if node.type == "false":
            return "False"
        if node.type == "none":
            return "None"
        return None

    def _text(self, node: Node | None) -> str:
        if node is None:
            return ""
        return self._source[node.start_byte : node.end_byte].decode(
            "utf-8", errors="replace"
        )

    def _child_text_by_field(self, node: Node, field: str) -> str | None:
        child = node.child_by_field_name(field)
        if child is None:
            return None
        return self._text(child)
