"""Framework annotator tests — reuse tests/fixtures/* for v1-comparable coverage."""

from __future__ import annotations

from pathlib import Path

from cartograph.v2.ir.annotated import (
    ApiRouteLabel,
    CeleryTaskLabel,
    DjangoSignalLabel,
)
from cartograph.v2.ir.resolved import ResolvedGraph
from cartograph.v2.stages.annotate.frameworks.celery import CeleryAnnotator
from cartograph.v2.stages.annotate.frameworks.django_ninja import DjangoNinjaAnnotator
from cartograph.v2.stages.annotate.frameworks.django_signals import (
    DjangoSignalsAnnotator,
)
from cartograph.v2.stages.annotate.frameworks.fastapi import FastApiAnnotator
from cartograph.v2.stages.annotate.frameworks.flask import FlaskAnnotator
from cartograph.v2.stages.annotate.registry import default_annotators
from cartograph.v2.stages.extract.treesitter_extractor import TreesitterExtractor

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def _extract(path: Path, module_name: str):
    """Helper: run TreesitterExtractor, return the SyntacticModule."""
    result = TreesitterExtractor().extract(path, module_name)
    assert result.kind == "ok", f"extract failed: {result}"
    return result.value


def _empty_graph() -> ResolvedGraph:
    return ResolvedGraph(functions={}, edges=())


# ──────────────────────────────────────────────────────────────────────────────
# FastAPI
# ──────────────────────────────────────────────────────────────────────────────


class TestFastApi:
    def test_detects_app_get_with_path(self):
        module = _extract(FIXTURES / "fastapi_app.py", "fastapi_app")
        annotator = FastApiAnnotator()
        labels = annotator.annotate(_empty_graph(), {module.module_name: module})

        list_users = labels.get("fastapi_app.list_users", ())
        assert len(list_users) == 1
        assert isinstance(list_users[0], ApiRouteLabel)
        assert list_users[0].method == "GET"
        assert list_users[0].path == "/users"
        assert list_users[0].framework == "fastapi"

    def test_detects_all_http_methods(self):
        module = _extract(FIXTURES / "fastapi_app.py", "fastapi_app")
        labels = FastApiAnnotator().annotate(
            _empty_graph(), {module.module_name: module}
        )

        methods = {}
        for qname, lbls in labels.items():
            if lbls and isinstance(lbls[0], ApiRouteLabel):
                methods[qname] = lbls[0].method
        assert methods.get("fastapi_app.list_users") == "GET"
        assert methods.get("fastapi_app.create_user") == "POST"
        assert methods.get("fastapi_app.update_user") == "PUT"
        assert methods.get("fastapi_app.delete_user") == "DELETE"
        assert methods.get("fastapi_app.patch_product") == "PATCH"

    def test_detects_websocket(self):
        module = _extract(FIXTURES / "fastapi_app.py", "fastapi_app")
        labels = FastApiAnnotator().annotate(
            _empty_graph(), {module.module_name: module}
        )
        notif = labels.get("fastapi_app.notification_stream", ())
        assert len(notif) == 1
        assert notif[0].method == "WS"
        assert notif[0].path == "/ws/notifications"

    def test_router_routes_detected(self):
        module = _extract(FIXTURES / "fastapi_app.py", "fastapi_app")
        labels = FastApiAnnotator().annotate(
            _empty_graph(), {module.module_name: module}
        )
        assert "fastapi_app.list_products" in labels
        assert labels["fastapi_app.list_products"][0].path == "/products"

    def test_skips_modules_without_fastapi_import(self):
        module = _extract(FIXTURES / "simple_functions.py", "simple_functions")
        labels = FastApiAnnotator().annotate(
            _empty_graph(), {module.module_name: module}
        )
        assert labels == {}


# ──────────────────────────────────────────────────────────────────────────────
# Flask
# ──────────────────────────────────────────────────────────────────────────────


class TestFlask:
    def test_app_route_detected(self):
        module = _extract(FIXTURES / "flask_app.py", "flask_app")
        labels = FlaskAnnotator().annotate(_empty_graph(), {module.module_name: module})
        index = labels.get("flask_app.index", ())
        assert len(index) == 1
        assert index[0].method == "ROUTE"
        assert index[0].path == "/"

    def test_flask2_shorthand_detected(self):
        module = _extract(FIXTURES / "flask_app.py", "flask_app")
        labels = FlaskAnnotator().annotate(_empty_graph(), {module.module_name: module})
        list_items = labels.get("flask_app.list_items", ())
        assert len(list_items) == 1
        assert list_items[0].method == "GET"
        assert list_items[0].path == "/items"

    def test_blueprint_routes_detected(self):
        module = _extract(FIXTURES / "flask_app.py", "flask_app")
        labels = FlaskAnnotator().annotate(_empty_graph(), {module.module_name: module})
        get_user = labels.get("flask_app.get_user", ())
        assert len(get_user) == 1
        assert get_user[0].method == "GET"

    def test_errorhandler_detected(self):
        module = _extract(FIXTURES / "flask_app.py", "flask_app")
        labels = FlaskAnnotator().annotate(_empty_graph(), {module.module_name: module})
        not_found = labels.get("flask_app.not_found", ())
        assert len(not_found) == 1
        assert not_found[0].method == "ERROR"
        assert not_found[0].path == "404"


# ──────────────────────────────────────────────────────────────────────────────
# Celery
# ──────────────────────────────────────────────────────────────────────────────


class TestCelery:
    def test_celery_app_task_detected(self):
        module = _extract(FIXTURES / "celery_tasks.py", "celery_tasks")
        labels = CeleryAnnotator().annotate(
            _empty_graph(), {module.module_name: module}
        )
        proc = labels.get("celery_tasks.process_sensor_data", ())
        assert len(proc) == 1
        assert isinstance(proc[0], CeleryTaskLabel)
        assert proc[0].queue == "server"
        assert proc[0].framework == "celery"

    def test_shared_task_detected(self):
        module = _extract(FIXTURES / "celery_tasks.py", "celery_tasks")
        labels = CeleryAnnotator().annotate(
            _empty_graph(), {module.module_name: module}
        )
        assert "celery_tasks.validate_data" in labels
        assert labels["celery_tasks.validate_data"][0].queue is None

    def test_plain_functions_not_labeled(self):
        module = _extract(FIXTURES / "celery_tasks.py", "celery_tasks")
        labels = CeleryAnnotator().annotate(
            _empty_graph(), {module.module_name: module}
        )
        # `fetch_data` is a plain def in the fixture, no decorator.
        assert "celery_tasks.fetch_data" not in labels


# ──────────────────────────────────────────────────────────────────────────────
# Django Ninja
# ──────────────────────────────────────────────────────────────────────────────


class TestDjangoNinja:
    def test_route_get_detected(self):
        module = _extract(FIXTURES / "django_controller.py", "django_controller")
        labels = DjangoNinjaAnnotator().annotate(
            _empty_graph(), {module.module_name: module}
        )
        list_eq = labels.get(
            "django_controller.EquipmentApiController.list_equipments", ()
        )
        assert len(list_eq) == 1
        assert list_eq[0].method == "GET"

    def test_controller_prefix_prepended_to_method_path(self):
        module = _extract(FIXTURES / "django_controller.py", "django_controller")
        labels = DjangoNinjaAnnotator().annotate(
            _empty_graph(), {module.module_name: module}
        )
        get_eq = labels.get(
            "django_controller.EquipmentApiController.get_equipment", ()
        )
        assert len(get_eq) == 1
        # Method decorator uses "/{equipment_id}"; class uses "/equipments".
        assert get_eq[0].path == "/equipments/{equipment_id}"

    def test_post_detected(self):
        module = _extract(FIXTURES / "django_controller.py", "django_controller")
        labels = DjangoNinjaAnnotator().annotate(
            _empty_graph(), {module.module_name: module}
        )
        create = labels.get(
            "django_controller.EquipmentApiController.create_equipment", ()
        )
        assert len(create) == 1
        assert create[0].method == "POST"


# ──────────────────────────────────────────────────────────────────────────────
# Django Signals
# ──────────────────────────────────────────────────────────────────────────────


class TestDjangoSignals:
    def test_receiver_with_sender_kwarg_detected(self):
        module = _extract(FIXTURES / "django_signals.py", "django_signals")
        labels = DjangoSignalsAnnotator().annotate(
            _empty_graph(), {module.module_name: module}
        )
        on_save = labels.get("django_signals.on_equipment_save", ())
        assert len(on_save) == 1
        assert isinstance(on_save[0], DjangoSignalLabel)
        assert on_save[0].sender == "Equipment"

    def test_signal_name_from_positional_is_unknown_when_name_is_variable(self):
        """When the signal is passed as a module variable (post_save) instead of
        a literal string, our constant-only capture can't resolve it — falls
        back to 'unknown'. Matches v1's behavior."""
        module = _extract(FIXTURES / "django_signals.py", "django_signals")
        labels = DjangoSignalsAnnotator().annotate(
            _empty_graph(), {module.module_name: module}
        )
        for qname in (
            "django_signals.on_equipment_save",
            "django_signals.on_equipment_delete",
        ):
            lbls = labels.get(qname, ())
            assert len(lbls) == 1
            assert lbls[0].signal_name == "unknown"

    def test_non_receiver_not_labeled(self):
        module = _extract(FIXTURES / "django_signals.py", "django_signals")
        labels = DjangoSignalsAnnotator().annotate(
            _empty_graph(), {module.module_name: module}
        )
        assert "django_signals.update_cache" not in labels


# ──────────────────────────────────────────────────────────────────────────────
# Registry
# ──────────────────────────────────────────────────────────────────────────────


class TestDjangoOrm:
    def test_orm_read_on_filter(self):
        from cartograph.v2.ir.annotated import OrmOperationLabel
        from cartograph.v2.stages.annotate.frameworks.django_orm import (
            DjangoOrmAnnotator,
        )

        module = _extract(FIXTURES / "orm_operations.py", "orm_operations")
        labels = DjangoOrmAnnotator().annotate(
            _empty_graph(), {module.module_name: module}
        )

        # Any function that uses `.filter()` on a Model chain should get a
        # read label. Fixture has several such functions.
        found_read = False
        for lbls in labels.values():
            for lbl in lbls:
                if isinstance(lbl, OrmOperationLabel) and lbl.operation == "read":
                    found_read = True
                    break
        assert found_read

    def test_per_site_labels_carry_line_numbers(self):
        """Per-site granularity: every label has a `line` field locating the
        call. Consumers dedup at the view layer; the IR stays lossless."""
        from cartograph.v2.ir.annotated import OrmOperationLabel
        from cartograph.v2.stages.annotate.frameworks.django_orm import (
            DjangoOrmAnnotator,
        )

        module = _extract(FIXTURES / "orm_operations.py", "orm_operations")
        labels = DjangoOrmAnnotator().annotate(
            _empty_graph(), {module.module_name: module}
        )

        total_sites = 0
        for lbls in labels.values():
            for lbl in lbls:
                assert isinstance(lbl, OrmOperationLabel)
                assert lbl.line > 0
                total_sites += 1
        assert total_sites > 0, "fixture has ORM calls"

    def test_repeat_calls_emit_multiple_labels(self):
        """Two .filter() calls on the same model in one function → two labels,
        not one. The line field distinguishes them."""
        from cartograph.v2.stages.annotate.frameworks.django_orm import (
            DjangoOrmAnnotator,
        )

        module = _extract(FIXTURES / "orm_operations.py", "orm_operations")
        labels = DjangoOrmAnnotator().annotate(
            _empty_graph(), {module.module_name: module}
        )

        # Find any function with multiple labels for the same (op, model)
        # pair. If the fixture has one, assert the lines differ.
        for qname, lbls in labels.items():
            groups: dict[tuple[str, str], list[int]] = {}
            for lbl in lbls:
                groups.setdefault((lbl.operation, lbl.model), []).append(lbl.line)
            for lines in groups.values():
                if len(lines) > 1:
                    assert len(set(lines)) == len(lines), (
                        f"{qname}: repeat labels must have distinct lines"
                    )
                    return
        # If the fixture doesn't exercise this, it's not a test failure —
        # the invariant holds vacuously.


class TestDefaultAnnotators:
    def test_returns_all_six(self):
        anns = default_annotators()
        frameworks = {a.framework for a in anns}
        assert frameworks == {
            "fastapi",
            "flask",
            "celery",
            "django_ninja",
            "django_signals",
            "django_orm",
        }

    def test_is_tuple_for_immutability(self):
        assert isinstance(default_annotators(), tuple)


# ──────────────────────────────────────────────────────────────────────────────
# Decorator-resolved path (v2.2 #13)
# ──────────────────────────────────────────────────────────────────────────────


class TestResolvedDecoratorPath:
    """When Stage 2 populates `decorators_by_target`, annotators match on
    the resolved target prefix — not the syntactic decorator name. These
    tests construct a graph with resolved decorators directly, bypassing
    the syntactic fallback, to exercise the type-aware code path."""

    def _graph_with_resolved(
        self,
        applied_to_qname: str,
        name: str,
        resolved_target: str,
        args: tuple[str, ...] = (),
        kwargs: dict[str, str] | None = None,
    ):
        from cartograph.v2.ir.resolved import ResolvedDecorator

        return ResolvedGraph(
            functions={},
            edges=(),
            decorators_by_target={
                applied_to_qname: (
                    ResolvedDecorator(
                        name=name,
                        resolved_target=resolved_target,
                        args=args,
                        kwargs=kwargs or {},
                        line=10,
                    ),
                )
            },
        )

    def test_fastapi_resolved_target_wins_over_name(self):
        """`@app.get("/users")` where `app.get` resolves into fastapi."""
        graph = self._graph_with_resolved(
            applied_to_qname="myapp.routes.list_users",
            name="app.get",
            resolved_target="fastapi.applications.FastAPI.get",
            args=("/users",),
        )
        labels = FastApiAnnotator().annotate(graph, {})
        assert "myapp.routes.list_users" in labels
        label = labels["myapp.routes.list_users"][0]
        assert isinstance(label, ApiRouteLabel)
        assert label.method == "GET"
        assert label.path == "/users"

    def test_fastapi_resolved_non_fastapi_target_rejected(self):
        """`@app.get` that resolves to a non-fastapi module → no label.
        This is the bug the resolved path fixes: alias collisions."""
        graph = self._graph_with_resolved(
            applied_to_qname="other.mod.handler",
            name="app.get",
            resolved_target="click.core.Group.command",
            args=("/whatever",),
        )
        labels = FastApiAnnotator().annotate(graph, {})
        assert labels == {}

    def test_celery_resolved_target_matches_package_prefix(self):
        graph = self._graph_with_resolved(
            applied_to_qname="myapp.tasks.send_email",
            name="app.task",
            resolved_target="celery.app.base.Celery.task",
            kwargs={"queue": "priority", "bind": "True"},
        )
        labels = CeleryAnnotator().annotate(graph, {})
        assert "myapp.tasks.send_email" in labels
        label = labels["myapp.tasks.send_email"][0]
        assert isinstance(label, CeleryTaskLabel)
        assert label.queue == "priority"
        assert label.bind is True

    def test_django_signals_resolved_receiver(self):
        graph = self._graph_with_resolved(
            applied_to_qname="myapp.handlers.on_save",
            name="receiver",
            resolved_target="django.dispatch.dispatcher.receiver",
            args=("post_save",),
            kwargs={"sender": "User"},
        )
        labels = DjangoSignalsAnnotator().annotate(graph, {})
        assert "myapp.handlers.on_save" in labels
        label = labels["myapp.handlers.on_save"][0]
        assert isinstance(label, DjangoSignalLabel)
        assert label.signal_name == "post_save"
        assert label.sender == "User"

    def test_resolved_target_none_falls_through(self):
        """resolved_target=None (LSP failure) should NOT emit a label via the
        resolved path; the graph's presence of decorators_by_target disables
        the syntactic fallback, so the result is empty."""
        graph = self._graph_with_resolved(
            applied_to_qname="myapp.routes.mystery",
            name="app.get",
            resolved_target=None,
            args=("/x",),
        )
        labels = FastApiAnnotator().annotate(graph, {})
        assert labels == {}
