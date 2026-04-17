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

    Five-step process:
    1. Build global function registry (qualified_name → ParsedFunction)
    2. Build class hierarchy index (class_qname → [base_qnames])
    3. Build return type index (func_qname → return_type)
    4. Build per-module import index (local_name → qualified_name)
    5. Resolve every FunctionCall using the unified type resolution pipeline
    """

    def __init__(self, index: ProjectIndex):
        self._index = index
        self._function_registry: dict[str, ParsedFunction] = {}
        self._import_index: dict[str, dict[str, str]] = {}
        self._class_hierarchy: dict[str, list[str]] = {}
        self._return_types: dict[str, str] = {}

    def build(self) -> CallGraph:
        graph = CallGraph()

        self._build_function_registry()
        self._build_class_hierarchy()
        self._build_return_type_index()
        graph.functions = dict(self._function_registry)

        self._build_import_index()
        self._resolve_all_calls(graph)

        return graph

    def _build_function_registry(self) -> None:
        """Step 1: Register every function by its qualified name."""
        for module in self._index.modules.values():
            for func in module.functions:
                self._function_registry[func.qualified_name] = func

    def _build_class_hierarchy(self) -> None:
        """Step 2: Build class hierarchy for MRO walking."""
        for module in self._index.modules.values():
            local_classes = {
                c.name: c.qualified_name for c in module.parsed_classes.values()
            }
            for cls in module.parsed_classes.values():
                resolved_bases = []
                for base_name in cls.bases:
                    # Try local class in same module
                    if base_name in local_classes:
                        resolved_bases.append(local_classes[base_name])
                        continue
                    # Try through imports
                    for imp in module.imports:
                        local = imp.alias or imp.name
                        if local == base_name.split(".")[0]:
                            qname = self._resolve_import_to_qualified_name(imp, module)
                            if qname:
                                resolved_bases.append(qname)
                                break
                self._class_hierarchy[cls.qualified_name] = resolved_bases

    def _build_return_type_index(self) -> None:
        """Step 3: Index function return types for return-value inference."""
        for module in self._index.modules.values():
            for func in module.functions:
                if func.return_type:
                    self._return_types[func.qualified_name] = func.return_type

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
        """Resolve a single call using the unified type resolution pipeline.

        Priority order for method calls (receiver.method()):
            P0: Async dispatch — task.delay() → the task function
            P1: self.method() — current class, then walk MRO
            P2: Import lookup — imported_name.method()
            P3: Parameter types — def f(x: Foo): x.method() → Foo.method
            P4: Local types — x = Foo(); x.method() (includes factory calls)
            P5: Return types — x = foo(); x.method() where foo() -> Foo
            P6: ORM pattern — Model.objects.filter()
        """
        if call.is_method_call and call.receiver:
            receiver_parts = call.receiver.split(".")
            base_receiver = receiver_parts[0]

            # P0: Async dispatch (.delay(), .apply_async())
            if call.is_async_dispatch and base_receiver in local_names:
                return local_names[base_receiver]

            # P1: self.method() → current class + MRO
            if base_receiver == "self" and caller.class_name:
                resolved = self._resolve_self_method(call, caller, module)
                if resolved:
                    return resolved

            # P2: Direct import lookup
            if base_receiver in local_names:
                resolved = self._resolve_via_import(
                    call, base_receiver, receiver_parts, local_names
                )
                if resolved:
                    return resolved

            # P3: Parameter type annotations
            resolved = self._resolve_via_param_types(call, caller, module, local_names)
            if resolved:
                return resolved

            # P4: Local type inference (constructors + factories)
            resolved = self._resolve_via_local_types(call, caller, module, local_names)
            if resolved:
                return resolved

            # P5: Return type inference
            resolved = self._resolve_via_return_types(call, caller, module, local_names)
            if resolved:
                return resolved

            # P6: ORM pattern (Model.objects.method())
            resolved = self._resolve_orm_pattern(call, module, local_names)
            if resolved:
                return resolved

        else:
            # Plain function call: foo()
            if call.name in local_names:
                return local_names[call.name]

            same_module = f"{module.module_path}.{call.name}"
            if same_module in self._function_registry:
                return same_module

            if caller.class_name:
                class_method = f"{module.module_path}.{caller.class_name}.{call.name}"
                if class_method in self._function_registry:
                    return class_method

        return None

    # ── Resolution strategies ─────────────────────────────────

    def _resolve_self_method(
        self,
        call: FunctionCall,
        caller: ParsedFunction,
        module: ParsedModule,
    ) -> str | None:
        """P1: Resolve self.method() — current class, then walk MRO."""
        class_qname = f"{module.module_path}.{caller.class_name}"

        # Try current class
        candidate = f"{class_qname}.{call.name}"
        if candidate in self._function_registry:
            return candidate

        # Walk MRO (BFS up base classes)
        return self._walk_mro_for_method(class_qname, call.name)

    def _resolve_via_import(
        self,
        call: FunctionCall,
        base_receiver: str,
        receiver_parts: list[str],
        local_names: dict[str, str],
    ) -> str | None:
        """P2: Resolve imported_name.method() via import index."""
        receiver_qname = local_names[base_receiver]
        candidate = f"{receiver_qname}.{call.name}"
        if candidate in self._function_registry:
            return candidate

        # Try with receiver chain: obj.sub.method
        if len(receiver_parts) > 1:
            rest = ".".join(receiver_parts[1:])
            candidate = f"{receiver_qname}.{rest}.{call.name}"
            if candidate in self._function_registry:
                return candidate

        return None

    def _resolve_via_param_types(
        self,
        call: FunctionCall,
        caller: ParsedFunction,
        module: ParsedModule,
        local_names: dict[str, str],
    ) -> str | None:
        """P3: Resolve via function parameter type annotations."""
        if not call.receiver:
            return None
        base_receiver = call.receiver.split(".")[0]
        type_name = caller.parameter_types.get(base_receiver)
        if not type_name:
            return None
        return self._resolve_type_to_method(type_name, call.name, module, local_names)

    def _resolve_via_local_types(
        self,
        call: FunctionCall,
        caller: ParsedFunction,
        module: ParsedModule,
        local_names: dict[str, str],
    ) -> str | None:
        """P4: Resolve via local type inference (constructors + factories)."""
        if not call.receiver:
            return None
        base_receiver = call.receiver.split(".")[0]
        type_name = caller.local_types.get(base_receiver)
        if not type_name:
            return None
        return self._resolve_type_to_method(type_name, call.name, module, local_names)

    def _resolve_via_return_types(
        self,
        call: FunctionCall,
        caller: ParsedFunction,
        module: ParsedModule,
        local_names: dict[str, str],
    ) -> str | None:
        """P5: Resolve via return type of assigned function call.

        When we see: x = get_user(); x.validate()
        And get_user() -> User, resolve to User.validate
        """
        if not call.receiver:
            return None
        base_receiver = call.receiver.split(".")[0]

        func_name = caller.call_assignments.get(base_receiver)
        if not func_name:
            return None

        # Resolve function name to qualified name
        func_qname = local_names.get(func_name)
        if not func_qname:
            func_qname = f"{module.module_path}.{func_name}"

        ret_type = self._return_types.get(func_qname)
        if not ret_type:
            return None

        return self._resolve_type_to_method(ret_type, call.name, module, local_names)

    def _resolve_orm_pattern(
        self,
        call: FunctionCall,
        module: ParsedModule,
        local_names: dict[str, str],
    ) -> str | None:
        """P6: Resolve Model.objects.method() ORM pattern."""
        if not call.receiver:
            return None
        parts = call.receiver.split(".")
        if len(parts) >= 2 and parts[1] == "objects":
            model_name = parts[0]
            model_qname = local_names.get(model_name)
            if not model_qname:
                model_qname = f"{module.module_path}.{model_name}"
            if model_qname in self._function_registry:
                return model_qname
        return None

    # ── Shared helpers ────────────────────────────────────────

    def _resolve_type_to_method(
        self,
        type_name: str,
        method_name: str,
        module: ParsedModule,
        local_names: dict[str, str],
    ) -> str | None:
        """Shared: resolve Type.method — used by P3, P4, P5.

        Resolves the type through imports, tries direct match,
        then walks MRO for inherited methods.
        """
        type_base = type_name.split(".")[0]
        if type_base in local_names:
            type_qname = local_names[type_base]
            if "." in type_name:
                rest = type_name.split(".", 1)[1]
                type_qname = f"{type_qname}.{rest}"
        else:
            type_qname = f"{module.module_path}.{type_name}"

        # Direct match
        candidate = f"{type_qname}.{method_name}"
        if candidate in self._function_registry:
            return candidate

        # Walk MRO for inherited methods
        resolved = self._walk_mro_for_method(type_qname, method_name)
        if resolved:
            return resolved

        # Suffix fallback (handles cases where qualified path differs)
        for qname in self._function_registry:
            if qname.endswith(f".{type_name}.{method_name}"):
                return qname

        return None

    def _walk_mro_for_method(self, class_qname: str, method_name: str) -> str | None:
        """BFS up the class hierarchy to find an inherited method."""
        visited: set[str] = set()
        to_check = list(self._class_hierarchy.get(class_qname, []))
        while to_check:
            base_qname = to_check.pop(0)
            if base_qname in visited:
                continue
            visited.add(base_qname)
            candidate = f"{base_qname}.{method_name}"
            if candidate in self._function_registry:
                return candidate
            to_check.extend(self._class_hierarchy.get(base_qname, []))
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
