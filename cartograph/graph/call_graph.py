"""Call graph builder — resolves cross-file function calls using import analysis.

Takes a ProjectIndex (all parsed modules) and builds a connected graph where
every function call is resolved to its target function's qualified name.
Unresolvable calls (external packages, dynamic dispatch) are marked explicitly.
"""

from dataclasses import dataclass, field

from cartograph.graph.models import (
    FunctionCall,
    ParsedFunction,
    ParsedModule,
    ProjectIndex,
)


@dataclass
class CallEdge:
    """A resolved edge in the call graph."""

    caller: str
    callee: str
    call: FunctionCall
    is_cross_file: bool = False
    condition: str | None = None


@dataclass
class UnresolvedCall:
    """A call that couldn't be resolved to a project function."""

    caller: str
    call: FunctionCall
    reason: str


@dataclass
class CallGraph:
    """The global call graph for a project."""

    functions: dict[str, ParsedFunction] = field(default_factory=dict)
    edges: list[CallEdge] = field(default_factory=list)
    unresolved: list[UnresolvedCall] = field(default_factory=list)

    def get_callees(self, qualified_name: str) -> list[CallEdge]:
        """Get all outgoing edges from a function."""
        return [e for e in self.edges if e.caller == qualified_name]

    def get_callers(self, qualified_name: str) -> list[CallEdge]:
        """Get all incoming edges to a function."""
        return [e for e in self.edges if e.callee == qualified_name]

    @property
    def total_resolved(self) -> int:
        return len(self.edges)

    @property
    def total_unresolved(self) -> int:
        return len(self.unresolved)


class CallGraphBuilder:
    """Builds a call graph from a ProjectIndex.

    Three-step process:
    1. Build global function registry (qualified_name → ParsedFunction)
    2. Build per-module import index (local_name → qualified_name)
    3. Resolve every FunctionCall to a qualified name using the import index
    """

    def __init__(self, index: ProjectIndex):
        self._index = index
        self._function_registry: dict[str, ParsedFunction] = {}
        self._import_index: dict[str, dict[str, str]] = {}

    def build(self) -> CallGraph:
        graph = CallGraph()

        self._build_function_registry()
        graph.functions = dict(self._function_registry)

        self._build_import_index()
        self._resolve_all_calls(graph)

        return graph

    def _build_function_registry(self) -> None:
        """Step 1: Register every function by its qualified name."""
        for module in self._index.modules.values():
            for func in module.functions:
                self._function_registry[func.qualified_name] = func

    def _build_import_index(self) -> None:
        """Step 2: For each module, map imported names to qualified names.

        Given:
            # In worker.py
            from .processor import transform, validate

        Produces:
            import_index["fixtures.multifile.worker"] = {
                "transform": "fixtures.multifile.processor.transform",
                "validate": "fixtures.multifile.processor.validate",
            }
        """
        for module_path, module in self._index.modules.items():
            local_names: dict[str, str] = {}

            for imp in module.imports:
                resolved_qname = self._resolve_import_to_qualified_name(imp, module)
                if resolved_qname:
                    local_names[imp.alias or imp.name] = resolved_qname

            # Also include functions defined in this module
            for func in module.functions:
                local_name = func.name.split(".")[-1] if "." in func.name else func.name
                local_names[local_name] = func.qualified_name

            self._import_index[module_path] = local_names

    def _resolve_import_to_qualified_name(
        self, imp, module: ParsedModule
    ) -> str | None:
        """Resolve an import to a qualified name in the function registry."""
        # Try direct qualified name: "from x.y import z" → "x.y.z"
        if imp.is_relative:
            # Relative import: resolve based on module path
            parts = module.module_path.split(".")
            levels_up = imp.level
            if levels_up > len(parts):
                return None
            base_parts = parts[:-levels_up] if levels_up else parts
            if imp.module:
                base = ".".join(base_parts) + "." + imp.module
            else:
                base = ".".join(base_parts)
        else:
            base = imp.module

        candidate = f"{base}.{imp.name}"

        # Check if it's a function/class in the registry
        if candidate in self._function_registry:
            return candidate

        # Check if the imported name is a module, and look for functions inside it
        for qname in self._function_registry:
            if qname.startswith(candidate + "."):
                # The import is a module/class, not a function directly
                return candidate

        # Check if the import resolves to a module that contains the name
        # e.g., "from .models import Store" where Store is a class
        for module_path in self._index.modules:
            if module_path in (base, candidate):
                # Found the module, look for the name inside
                target_module = self._index.modules[module_path]
                for func in target_module.functions:
                    if func.name == imp.name or func.name.endswith(f".{imp.name}"):
                        return func.qualified_name

        # Check if the imported name is a module-level instance
        # e.g., "from x.service import user_service" where user_service = UserService()
        # Resolve to the class so that user_service.method() → UserService.method
        target_module = self._index.modules.get(base)
        if target_module and imp.name in target_module.module_types:
            type_name = target_module.module_types[imp.name]
            type_base = type_name.split(".")[0]
            # Resolve the type through the target module's own context
            type_candidate = f"{base}.{type_name}"
            if type_candidate in self._function_registry:
                return type_candidate
            # Type might be imported in the target module — check its imports
            for target_imp in target_module.imports:
                local = target_imp.alias or target_imp.name
                if local == type_base:
                    imp_qname = self._resolve_import_to_qualified_name(
                        target_imp, target_module
                    )
                    if imp_qname:
                        if "." in type_name:
                            rest = type_name.split(".", 1)[1]
                            imp_qname = f"{imp_qname}.{rest}"
                        if imp_qname in self._function_registry:
                            return imp_qname

        return None

    def _resolve_all_calls(self, graph: CallGraph) -> None:
        """Step 3: Resolve every call in every function."""
        for module_path, module in self._index.modules.items():
            local_names = self._import_index.get(module_path, {})

            for func in module.functions:
                self._resolve_function_calls(func, module, local_names, graph)

    def _resolve_function_calls(
        self,
        func: ParsedFunction,
        module: ParsedModule,
        local_names: dict[str, str],
        graph: CallGraph,
    ) -> None:
        """Resolve all calls within a single function."""
        # Top-level calls (not inside any branch)
        for call in func.calls:
            self._resolve_and_add(
                call, func, module, local_names, graph, condition=None
            )

        # Branch calls — preserve the condition context
        for branch in func.branches:
            condition = branch.condition
            if branch.is_else:
                condition = "else"
            for call in branch.calls:
                self._resolve_and_add(
                    call, func, module, local_names, graph, condition=condition
                )

    def _resolve_and_add(
        self,
        call: FunctionCall,
        func: ParsedFunction,
        module: ParsedModule,
        local_names: dict[str, str],
        graph: CallGraph,
        condition: str | None,
    ) -> None:
        """Resolve a single call and add it to the graph."""
        resolved = self._resolve_single_call(call, func, module, local_names)

        if resolved:
            is_cross_file = not resolved.startswith(module.module_path + ".")
            graph.edges.append(
                CallEdge(
                    caller=func.qualified_name,
                    callee=resolved,
                    call=call,
                    is_cross_file=is_cross_file,
                    condition=condition,
                )
            )
        else:
            graph.unresolved.append(
                UnresolvedCall(
                    caller=func.qualified_name,
                    call=call,
                    reason=self._guess_unresolved_reason(call),
                )
            )

    def _resolve_single_call(
        self,
        call: FunctionCall,
        caller: ParsedFunction,
        module: ParsedModule,
        local_names: dict[str, str],
    ) -> str | None:
        """Resolve a single call to a qualified name."""

        if call.is_method_call and call.receiver:
            # Method call: obj.method()
            receiver_parts = call.receiver.split(".")
            base_receiver = receiver_parts[0]

            # Special case: async dispatch (.delay(), .apply_async(), .s(), .si())
            # The callee is the RECEIVER (the task function), not receiver.delay
            if call.is_async_dispatch and base_receiver in local_names:
                return local_names[base_receiver]

            # self.method() → resolve to CurrentClass.method
            if base_receiver == "self" and caller.class_name:
                candidate = f"{module.module_path}.{caller.class_name}.{call.name}"
                if candidate in self._function_registry:
                    return candidate
                # Don't brute-force suffix match — without inheritance
                # tracking, we'd match the wrong class (e.g., Cassandra
                # calling Elasticsearch's decode instead of Base's).

            if base_receiver in local_names:
                receiver_qname = local_names[base_receiver]
                # Try: receiver.method as qualified name
                candidate = f"{receiver_qname}.{call.name}"
                if candidate in self._function_registry:
                    return candidate

                # Try with the receiver chain: obj.sub.method
                if len(receiver_parts) > 1:
                    rest = ".".join(receiver_parts[1:])
                    candidate = f"{receiver_qname}.{rest}.{call.name}"
                    if candidate in self._function_registry:
                        return candidate

            # Type inference: resolve obj.method() via tracked local types
            # e.g., registry = LanguageRegistry() → registry.register()
            #        resolves to LanguageRegistry.register
            resolved = self._resolve_via_local_types(call, caller, module, local_names)
            if resolved:
                return resolved

        else:
            # Plain function call: foo()
            if call.name in local_names:
                return local_names[call.name]

            # Try: builtin or same-module function
            same_module = f"{module.module_path}.{call.name}"
            if same_module in self._function_registry:
                return same_module

            # Try: method call on self (within a class)
            if caller.class_name:
                class_method = f"{module.module_path}.{caller.class_name}.{call.name}"
                if class_method in self._function_registry:
                    return class_method

        return None

    def _resolve_via_local_types(
        self,
        call: FunctionCall,
        caller: ParsedFunction,
        module: ParsedModule,
        local_names: dict[str, str],
    ) -> str | None:
        """Resolve obj.method() using type info from constructor assignments.

        If caller has `x = Foo()` tracked in local_types, and we see `x.bar()`,
        resolve Foo through imports → try QualifiedFoo.bar in the registry.
        """
        if not call.receiver:
            return None

        base_receiver = call.receiver.split(".")[0]
        type_name = caller.local_types.get(base_receiver)
        if not type_name:
            return None

        # Resolve the type name through imports (same as resolving a function call)
        type_base = type_name.split(".")[0]
        if type_base in local_names:
            type_qname = local_names[type_base]
            # If type_name has dots (module.Foo), append the rest
            if "." in type_name:
                rest = type_name.split(".", 1)[1]
                type_qname = f"{type_qname}.{rest}"
        else:
            # Try same-module class
            type_qname = f"{module.module_path}.{type_name}"

        # Now try type_qname.method_name
        candidate = f"{type_qname}.{call.name}"
        if candidate in self._function_registry:
            return candidate

        # Try without module prefix (type_name might already be qualified)
        for qname in self._function_registry:
            if qname.endswith(f".{type_name}.{call.name}"):
                return qname

        return None

    def _guess_unresolved_reason(self, call: FunctionCall) -> str:
        """Guess why a call couldn't be resolved."""
        builtins = {
            "print",
            "len",
            "range",
            "str",
            "int",
            "float",
            "list",
            "dict",
            "set",
            "tuple",
            "isinstance",
            "type",
            "super",
            "next",
            "iter",
            "enumerate",
            "zip",
            "map",
            "filter",
            "sorted",
            "reversed",
            "hasattr",
            "getattr",
            "setattr",
            "max",
            "min",
            "sum",
            "abs",
            "any",
            "all",
            "open",
            "format",
        }
        if call.name in builtins:
            return "builtin"

        common_methods = {
            "append",
            "extend",
            "pop",
            "get",
            "update",
            "items",
            "keys",
            "values",
            "strip",
            "split",
            "join",
            "replace",
            "format",
            "startswith",
            "endswith",
            "lower",
            "upper",
            "encode",
            "decode",
            "copy",
            "clear",
            "add",
            "remove",
            "discard",
        }
        if call.name in common_methods:
            return "builtin_method"

        logging_names = {"info", "debug", "warning", "error", "critical", "exception"}
        if call.name in logging_names:
            return "logging"

        return "not_in_project"
