"""ExtractCache (Stage 1) and ResolveCache (Stage 2) — content-addressed caches."""

from __future__ import annotations

from pathlib import Path

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
