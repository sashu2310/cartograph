"""Pipeline orchestrator. Composes stages; holds no subprocess or filesystem state."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import logfire

from cartograph.v2.cache.store import (
    ExtractCache,
    ResolveCache,
    content_hash,
    project_fingerprint,
)
from cartograph.v2.config import RunConfig
from cartograph.v2.ir.analyzed import AnalyzedGraph
from cartograph.v2.ir.annotated import AnnotatedGraph, SemanticLabel
from cartograph.v2.ir.base import Err_, Ok, is_err
from cartograph.v2.ir.errors import PipelineError
from cartograph.v2.ir.syntactic import SyntacticModule
from cartograph.v2.stages.annotate.protocol import Annotator
from cartograph.v2.stages.discover.protocol import Discoverer
from cartograph.v2.stages.extract.protocol import Extractor
from cartograph.v2.stages.present.protocol import Presenter
from cartograph.v2.stages.resolve.protocol import Resolver


@dataclass(frozen=True)
class Pipeline:
    extractor: Extractor
    resolver: Resolver
    annotators: tuple[Annotator, ...]
    discoverer: Discoverer
    presenter: Presenter

    async def build(self, config: RunConfig) -> Ok[AnalyzedGraph] | Err_[PipelineError]:
        """Run stages 1-4 and return the final AnalyzedGraph."""
        with logfire.span(
            "pipeline.build",
            project_root=str(config.project_root),
            resolver=self.resolver.name,
        ):
            # Stage 1: Extract
            modules = tuple(_extract_all(self.extractor, config))
            if not modules:
                return Err_(
                    error=PipelineError(
                        stage="extract",
                        detail="no modules extracted from project",
                    )
                )
            logfire.info("stage 1 complete", module_count=len(modules))

            # Stage 2: Resolve (with optional whole-graph cache)
            resolve_cache = (
                ResolveCache(config.project_root) if config.use_cache else None
            )
            resolve_key = (
                project_fingerprint(
                    modules,
                    resolver_version=f"{self.resolver.name}@{self.resolver.version}",
                )
                if resolve_cache is not None
                else None
            )
            resolved = None
            if resolve_cache is not None and resolve_key is not None:
                resolved = resolve_cache.get(resolve_key)
                if resolved is not None:
                    logfire.info("resolve cache hit", key=resolve_key[:12])

            if resolved is None:
                resolved_result = await self.resolver.resolve(
                    modules, config.project_root
                )
                if is_err(resolved_result):
                    return Err_(
                        error=PipelineError(
                            stage="resolve",
                            detail=_describe_err(resolved_result.error),
                        )
                    )
                resolved = resolved_result.value
                if resolve_cache is not None and resolve_key is not None:
                    resolve_cache.put(resolve_key, resolved)

            logfire.info(
                "stage 2 complete",
                edge_count=len(resolved.edges),
                unresolved_count=len(resolved.unresolved),
            )

            # Stage 3: Annotate
            module_by_name = {m.module_name: m for m in modules}
            labels = _merge_labels(
                a.annotate(resolved, module_by_name) for a in self.annotators
            )
            annotated = AnnotatedGraph(resolved=resolved, labels=labels)
            logfire.info(
                "stage 3 complete",
                annotator_count=len(self.annotators),
                labelled_functions=len(labels),
            )

            # Stage 4: Discover
            entries = self.discoverer.discover(annotated)
            analyzed = AnalyzedGraph(annotated=annotated, entry_points=entries)
            logfire.info(
                "stage 4 complete",
                entry_point_count=len(entries),
            )

            return Ok(value=analyzed)

    async def run(
        self, config: RunConfig, render_options: dict | None = None
    ) -> Ok[bytes] | Err_[PipelineError]:
        """Full pipeline: build the analyzed graph + render via presenter."""
        built = await self.build(config)
        if is_err(built):
            return built  # type: ignore[return-value]
        rendered = self.presenter.render(built.value, render_options or {})
        return Ok(value=rendered)


def _extract_all(extractor: Extractor, config: RunConfig) -> Iterator[SyntacticModule]:
    """Walk the project and extract each file, with optional Stage 1 cache."""
    cache = ExtractCache(config.project_root) if config.use_cache else None
    hits = 0
    misses = 0
    for path, module_name in scan_python_files(config):
        key = None
        if cache is not None:
            try:
                key = content_hash(path)
            except OSError:
                key = None
            if key is not None:
                cached = cache.get(key)
                if cached is not None:
                    hits += 1
                    yield cached
                    continue
        result = extractor.extract(path, module_name)
        if is_err(result):
            logfire.warn(
                "extract skipped",
                path=str(path),
                reason=type(result.error).__name__,
            )
            continue
        misses += 1
        if cache is not None and key is not None:
            cache.put(key, result.value)
        yield result.value
    if cache is not None:
        logfire.info("extract cache", hits=hits, misses=misses)


def scan_python_files(config: RunConfig) -> Iterator[tuple[Path, str]]:
    """Yield (absolute_path, module_name) for every `.py` file under the root.

    `module_name` is the dotted path relative to the project root.
    `__init__.py` files collapse to their parent package name.
    """
    excludes = config.exclude_dirs
    if not config.include_tests:
        excludes = excludes | {"tests", "test"}

    root = config.project_root.resolve()
    for path in root.rglob("*.py"):
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        # Check excludes against relative parts only, not the whole absolute
        # path. Otherwise a project located under a path like `/usr/tests/foo`
        # would have every file excluded because "tests" happens to be an
        # ancestor outside the project root.
        if any(part in excludes for part in relative.parts):
            continue

        dotted = str(relative.with_suffix("")).replace("/", ".")
        if dotted.endswith(".__init__"):
            dotted = dotted[: -len(".__init__")]
        if not dotted:
            continue
        yield (path, dotted)


def _merge_labels(
    label_dicts: Iterator[dict[str, tuple[SemanticLabel, ...]]],
) -> dict[str, tuple[SemanticLabel, ...]]:
    """Union multiple annotators' outputs into one qname → labels map."""
    merged: dict[str, list[SemanticLabel]] = {}
    for d in label_dicts:
        for qname, labels in d.items():
            merged.setdefault(qname, []).extend(labels)
    return {q: tuple(ls) for q, ls in merged.items()}


def _describe_err(err) -> str:
    """One-line description for nested stage errors."""
    kind = getattr(err, "kind", None) or type(err).__name__
    detail = getattr(err, "detail", None) or ""
    return f"{kind}: {detail}".strip(": ")
