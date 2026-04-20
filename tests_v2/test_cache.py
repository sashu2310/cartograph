"""ExtractCache (Stage 1) and ResolveCache (Stage 2) — content-addressed caches."""

from __future__ import annotations

from pathlib import Path

import pytest

from cartograph.v2.cache.store import (
    ExtractCache,
    ResolveCache,
    content_hash,
    project_fingerprint,
)
from cartograph.v2.ir.resolved import Edge, FunctionRef, ResolvedGraph
from cartograph.v2.ir.syntactic import SyntacticModule


def _module(
    path: Path, *, module_name: str = "demo", hash_: str = "deadbeef"
) -> SyntacticModule:
    return SyntacticModule(
        path=path,
        module_name=module_name,
        content_hash=hash_,
    )


def _resolved_graph() -> ResolvedGraph:
    fn = FunctionRef(
        qname="m.f",
        name="f",
        module="m",
        line_start=1,
        line_end=2,
        source_path=Path("/tmp/m.py"),
    )
    return ResolvedGraph(
        functions={"m.f": fn},
        edges=(Edge(caller_qname="m.f", callee_qname="m.f", line=1),),
    )


# ──────────────────────────────────────────────────────────────────────────────
# ExtractCache
# ──────────────────────────────────────────────────────────────────────────────


def test_put_and_get_roundtrip(tmp_path):
    cache = ExtractCache(tmp_path)
    mod = _module(tmp_path / "demo.py")
    cache.put("abc123", mod)

    loaded = cache.get("abc123")
    assert loaded is not None
    assert loaded.module_name == "demo"


def test_miss_returns_none(tmp_path):
    cache = ExtractCache(tmp_path)
    assert cache.get("not-in-cache") is None


def test_malformed_json_treated_as_miss(tmp_path):
    cache = ExtractCache(tmp_path)
    cache.root.mkdir(parents=True, exist_ok=True)
    (cache.root / "corrupt.json").write_text("{ not valid json")
    assert cache.get("corrupt") is None


def test_clear(tmp_path):
    cache = ExtractCache(tmp_path)
    cache.put("a", _module(tmp_path / "a.py"))
    cache.put("b", _module(tmp_path / "b.py"))
    cache.clear()
    assert cache.get("a") is None
    assert cache.get("b") is None


def test_content_hash_is_deterministic(tmp_path):
    src = tmp_path / "x.py"
    src.write_text("x = 1\n")
    h1 = content_hash(src)
    h2 = content_hash(src)
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


# ──────────────────────────────────────────────────────────────────────────────
# ResolveCache + project_fingerprint
# ──────────────────────────────────────────────────────────────────────────────


def test_resolve_cache_roundtrip(tmp_path):
    cache = ResolveCache(tmp_path)
    cache.put("proj-fp", _resolved_graph())
    loaded = cache.get("proj-fp")
    assert loaded is not None
    assert "m.f" in loaded.functions
    assert len(loaded.edges) == 1


def test_resolve_cache_malformed_treated_as_miss(tmp_path):
    cache = ResolveCache(tmp_path)
    cache.root.mkdir(parents=True, exist_ok=True)
    (cache.root / "bad.json").write_text("not json")
    assert cache.get("bad") is None


def test_fingerprint_stable_for_same_inputs(tmp_path):
    mods = (
        _module(tmp_path / "a.py", module_name="a", hash_="h_a"),
        _module(tmp_path / "b.py", module_name="b", hash_="h_b"),
    )
    fp1 = project_fingerprint(mods, resolver_version="ty@0.0.31")
    fp2 = project_fingerprint(mods, resolver_version="ty@0.0.31")
    assert fp1 == fp2


def test_fingerprint_changes_on_content_change(tmp_path):
    m_before = _module(tmp_path / "a.py", module_name="a", hash_="h_old")
    m_after = _module(tmp_path / "a.py", module_name="a", hash_="h_new")
    fp1 = project_fingerprint((m_before,), resolver_version="ty@0.0.31")
    fp2 = project_fingerprint((m_after,), resolver_version="ty@0.0.31")
    assert fp1 != fp2


def test_fingerprint_changes_on_resolver_change(tmp_path):
    mod = _module(tmp_path / "a.py", module_name="a", hash_="h")
    fp_ty = project_fingerprint((mod,), resolver_version="ty@0.0.31")
    fp_other = project_fingerprint((mod,), resolver_version="pyrefly@0.5")
    assert fp_ty != fp_other


def test_fingerprint_order_insensitive(tmp_path):
    m_a = _module(tmp_path / "a.py", module_name="a", hash_="h_a")
    m_b = _module(tmp_path / "b.py", module_name="b", hash_="h_b")
    fp1 = project_fingerprint((m_a, m_b), resolver_version="ty@0.0.31")
    fp2 = project_fingerprint((m_b, m_a), resolver_version="ty@0.0.31")
    assert fp1 == fp2


# ──────────────────────────────────────────────────────────────────────────────
# Pipeline integration
# ──────────────────────────────────────────────────────────────────────────────


def test_pipeline_uses_cache(tmp_path):
    """Extraction runs once; a second scan reads from cache."""
    import asyncio

    from cartograph.v2.config import RunConfig
    from cartograph.v2.pipeline import Pipeline
    from cartograph.v2.stages.discover.topology import TopologyDiscoverer
    from cartograph.v2.stages.extract.treesitter_extractor import TreesitterExtractor
    from cartograph.v2.stages.present.cli import CliPresenter
    from cartograph.v2.stages.resolve.ty_resolver import TyResolver
    from tests_v2.test_ty_resolver import FakeLspServer

    (tmp_path / "app.py").write_text("def helper():\n    return 1\n")

    async def run():
        fake = FakeLspServer()
        pipeline = Pipeline(
            extractor=TreesitterExtractor(),
            resolver=TyResolver(server=fake),  # type: ignore[arg-type]
            annotators=(),
            discoverer=TopologyDiscoverer(),
            presenter=CliPresenter(),
        )
        cfg = RunConfig(project_root=tmp_path, use_cache=True)
        await pipeline.build(cfg)
        # Second run should hit both caches.
        await pipeline.build(cfg)

    asyncio.run(run())

    extract_dir = tmp_path / ".cartograph" / "v2" / "extract"
    resolve_dir = tmp_path / ".cartograph" / "v2" / "resolve"
    assert extract_dir.exists()
    assert any(p.suffix == ".json" for p in extract_dir.iterdir())
    assert resolve_dir.exists()
    assert any(p.suffix == ".json" for p in resolve_dir.iterdir())


def test_pipeline_skips_resolver_on_cache_hit(tmp_path):
    """Proof that the second run doesn't call the resolver: use a resolver that
    raises on invocation and verify it's never reached on run 2."""
    import asyncio

    from cartograph.v2.config import RunConfig
    from cartograph.v2.ir.base import Ok
    from cartograph.v2.pipeline import Pipeline
    from cartograph.v2.stages.discover.topology import TopologyDiscoverer
    from cartograph.v2.stages.extract.treesitter_extractor import TreesitterExtractor
    from cartograph.v2.stages.present.cli import CliPresenter
    from cartograph.v2.stages.resolve.ty_resolver import TyResolver
    from tests_v2.test_ty_resolver import FakeLspServer

    (tmp_path / "app.py").write_text("def helper():\n    return 1\n")

    resolver_calls = {"count": 0}

    async def run():
        fake = FakeLspServer()
        resolver = TyResolver(server=fake)  # type: ignore[arg-type]

        original_resolve = resolver.resolve

        async def counting_resolve(*args, **kwargs):
            resolver_calls["count"] += 1
            return await original_resolve(*args, **kwargs)

        resolver.resolve = counting_resolve  # type: ignore[method-assign]

        pipeline = Pipeline(
            extractor=TreesitterExtractor(),
            resolver=resolver,
            annotators=(),
            discoverer=TopologyDiscoverer(),
            presenter=CliPresenter(),
        )
        cfg = RunConfig(project_root=tmp_path, use_cache=True)
        r1 = await pipeline.build(cfg)
        r2 = await pipeline.build(cfg)
        assert isinstance(r1, Ok) and isinstance(r2, Ok)

    asyncio.run(run())
    # First run miss, second run hit → resolver called exactly once.
    assert resolver_calls["count"] == 1


class TestMtimeFastPath:
    """`hash_for(path)` short-circuits re-reading files whose mtime is unchanged."""

    def test_first_call_populates_mtime_index(self, tmp_path):
        src = tmp_path / "x.py"
        src.write_text("x = 1\n")
        cache = ExtractCache(tmp_path / "cache")

        digest = cache.hash_for(src)

        assert len(digest) == 64  # blake2b hex (256 bits)
        resolved = str(src.resolve())
        assert resolved in cache._mtime_index
        assert cache._mtime_index[resolved][1] == digest

    def test_unchanged_mtime_skips_content_read(self, tmp_path, monkeypatch):
        src = tmp_path / "x.py"
        src.write_text("x = 1\n")
        cache = ExtractCache(tmp_path / "cache")
        first = cache.hash_for(src)

        # Replace content_hash with a sentinel that raises — proves the fast
        # path isn't silently falling through to a re-read.
        from cartograph.v2.cache import store as store_mod

        def boom(_path):
            raise AssertionError("content_hash called on unchanged file")

        monkeypatch.setattr(store_mod, "content_hash", boom)

        second = cache.hash_for(src)
        assert second == first

    def test_mtime_change_forces_rehash(self, tmp_path):
        import os
        import time

        src = tmp_path / "x.py"
        src.write_text("x = 1\n")
        cache = ExtractCache(tmp_path / "cache")
        original = cache.hash_for(src)

        # Rewrite the file with fresh bytes; bump mtime to guarantee detection
        # even on filesystems with coarse mtime granularity.
        # Bump mtime past filesystem granularity so the change is detected.
        time.sleep(0.01)
        src.write_text("x = 2\n")
        new_mtime = os.stat(src).st_mtime + 1
        os.utime(src, (new_mtime, new_mtime))

        rehashed = cache.hash_for(src)
        assert rehashed != original

    def test_mtime_index_persists_across_cache_instances(self, tmp_path):
        src = tmp_path / "x.py"
        src.write_text("x = 1\n")
        cache_dir = tmp_path / "cache"

        first_cache = ExtractCache(cache_dir)
        digest = first_cache.hash_for(src)
        first_cache.save_mtime_index()

        second_cache = ExtractCache(cache_dir)
        assert str(src.resolve()) in second_cache._mtime_index
        assert second_cache._mtime_index[str(src.resolve())][1] == digest

    def test_save_is_noop_when_nothing_changed(self, tmp_path):
        cache = ExtractCache(tmp_path / "cache")
        cache.save_mtime_index()
        assert not (cache.root / cache._MTIME_INDEX_NAME).exists()


class TestPipelineStats:
    """The pipeline writes extract_hits/misses and resolve_cache_hit into
    the `stats` dict that the CLI cache footer renders."""

    def test_first_run_reports_misses_then_second_run_reports_hits(self, tmp_path):
        import asyncio

        from cartograph.v2.config import RunConfig
        from cartograph.v2.pipeline import Pipeline
        from cartograph.v2.stages.discover.topology import TopologyDiscoverer
        from cartograph.v2.stages.extract.treesitter_extractor import (
            TreesitterExtractor,
        )
        from cartograph.v2.stages.present.cli import CliPresenter
        from cartograph.v2.stages.resolve.ty_resolver import TyResolver
        from tests_v2.test_ty_resolver import FakeLspServer

        (tmp_path / "app.py").write_text("def helper():\n    return 1\n")

        async def run() -> tuple[dict, dict]:
            fake = FakeLspServer()
            pipeline = Pipeline(
                extractor=TreesitterExtractor(),
                resolver=TyResolver(server=fake),  # type: ignore[arg-type]
                annotators=(),
                discoverer=TopologyDiscoverer(),
                presenter=CliPresenter(),
            )
            cfg = RunConfig(project_root=tmp_path, use_cache=True)
            s1: dict = {}
            await pipeline.build(cfg, stats=s1)
            s2: dict = {}
            await pipeline.build(cfg, stats=s2)
            return s1, s2

        stats1, stats2 = asyncio.run(run())

        assert stats1.get("extract_misses", 0) >= 1
        assert stats1.get("resolve_cache_hit") is False

        assert stats2.get("extract_hits", 0) >= 1
        assert stats2.get("extract_misses", 0) == 0
        assert stats2.get("resolve_cache_hit") is True


@pytest.mark.integration
class TestRealTyIntegration:
    """End-to-end with real `ty`. Skipped when the binary isn't on PATH."""

    @pytest.fixture
    def ty_available(self):
        import shutil as _shutil

        if _shutil.which("ty") is None:
            pytest.skip("ty binary not on PATH")
        return True

    def _build(self, project_root: Path):
        import asyncio

        from cartograph.v2.config import RunConfig
        from cartograph.v2.pipeline import Pipeline
        from cartograph.v2.stages.annotate.registry import default_annotators
        from cartograph.v2.stages.discover.topology import TopologyDiscoverer
        from cartograph.v2.stages.extract.treesitter_extractor import (
            TreesitterExtractor,
        )
        from cartograph.v2.stages.present.cli import CliPresenter
        from cartograph.v2.stages.resolve.lsp.server import LspServer
        from cartograph.v2.stages.resolve.ty_resolver import TyResolver

        async def run():
            async with LspServer(["ty", "server"]) as server:
                pipeline = Pipeline(
                    extractor=TreesitterExtractor(),
                    resolver=TyResolver(server=server),
                    annotators=default_annotators(),
                    discoverer=TopologyDiscoverer(),
                    presenter=CliPresenter(),
                )
                return await pipeline.build(RunConfig(project_root=project_root))

        return asyncio.run(run())

    def test_rename_impact_enumerates_import_sites_with_exact_lines(
        self, ty_available, tmp_path
    ):
        (tmp_path / "defs.py").write_text("def target():\n    return 1\n")
        (tmp_path / "caller.py").write_text(
            "from defs import target\n"
            "\n"
            "def main():\n"
            "    return target()\n"
        )

        built = self._build(tmp_path)
        from cartograph.v2.ir.base import is_ok

        assert is_ok(built), built
        graph = built.value

        target_qname = next(
            q for q in graph.annotated.resolved.functions if q.endswith(".target")
        )

        from cartograph.v2.analyses import rename_impact

        report = rename_impact(graph, target_qname, "renamed")

        assert report.import_sites
        site = next(
            s for s in report.import_sites if Path(s.file).name == "caller.py"
        )
        assert site.line == 1
        assert site.statement == "from defs import target"

    def test_fastapi_decorator_resolves_via_ty_and_annotates_route(
        self, ty_available, tmp_path
    ):
        # Stub fastapi package — hermetic test without depending on a pip install.
        fastapi = tmp_path / "fastapi"
        fastapi.mkdir()
        (fastapi / "__init__.py").write_text(
            "class APIRouter:\n"
            "    def get(self, path):\n"
            "        def deco(fn):\n"
            "            return fn\n"
            "        return deco\n"
        )

        (tmp_path / "routes.py").write_text(
            "from fastapi import APIRouter\n"
            "\n"
            "router = APIRouter()\n"
            "\n"
            "def build_response():\n"
            "    return {'ok': True}\n"
            "\n"
            "@router.get('/hello')\n"
            "def hello():\n"
            "    return build_response()\n"
        )

        built = self._build(tmp_path)
        from cartograph.v2.ir.analyzed import ApiRouteEntry
        from cartograph.v2.ir.annotated import ApiRouteLabel
        from cartograph.v2.ir.base import is_ok

        assert is_ok(built), built
        graph = built.value

        hello_qname = next(
            q for q in graph.annotated.resolved.functions if q.endswith(".hello")
        )

        resolved_decs = graph.annotated.resolved.decorators_by_target.get(hello_qname)
        assert resolved_decs, f"no resolved decorators for {hello_qname}"
        assert any(
            (rd.resolved_target or "").startswith("fastapi") for rd in resolved_decs
        )

        labels = graph.annotated.labels.get(hello_qname, ())
        assert any(isinstance(lbl, ApiRouteLabel) for lbl in labels)

        api_routes = [
            ep for ep in graph.entry_points if isinstance(ep, ApiRouteEntry)
        ]
        assert any(ep.qname == hello_qname for ep in api_routes)
