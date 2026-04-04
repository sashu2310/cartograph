"""Registry for language adapters and framework detectors.

The registry is the coordination layer that connects file extensions to
the right parser and runs the right framework detectors for each language.
"""

from pathlib import Path

from cartograph.graph.models import EntryPoint, ParsedModule
from cartograph.parser.protocols import FrameworkDetector, LanguageAdapter


class LanguageRegistry:
    """Maps file extensions to language adapters."""

    def __init__(self):
        self._adapters: dict[str, LanguageAdapter] = {}
        self._by_language: dict[str, LanguageAdapter] = {}

    def register(self, adapter: LanguageAdapter) -> None:
        for ext in adapter.file_extensions:
            self._adapters[ext] = adapter
        self._by_language[adapter.language_id] = adapter

    def get_adapter(self, file_path: str) -> LanguageAdapter | None:
        ext = Path(file_path).suffix
        return self._adapters.get(ext)

    def get_by_language(self, language_id: str) -> LanguageAdapter | None:
        return self._by_language.get(language_id)

    @property
    def supported_extensions(self) -> set[str]:
        return set(self._adapters.keys())

    @property
    def supported_languages(self) -> list[str]:
        return list(self._by_language.keys())


class FrameworkRegistry:
    """Manages framework detectors, grouped by language."""

    def __init__(self):
        self._detectors: dict[str, list[FrameworkDetector]] = {}

    def register(self, language_id: str, detector: FrameworkDetector) -> None:
        if language_id not in self._detectors:
            self._detectors[language_id] = []
        self._detectors[language_id].append(detector)

    def get_detectors(self, language_id: str) -> list[FrameworkDetector]:
        return self._detectors.get(language_id, [])

    def detect_all_entry_points(
        self, module: ParsedModule, language_id: str
    ) -> list[EntryPoint]:
        entry_points = []
        for detector in self.get_detectors(language_id):
            entry_points.extend(detector.detect_entry_points(module))
        return entry_points

    def annotate_module(self, module: ParsedModule, language_id: str) -> None:
        """Run all framework detectors on a module, annotating calls in-place."""
        detectors = self.get_detectors(language_id)
        for func in module.functions:
            for call in func.calls:
                for detector in detectors:
                    async_type = detector.detect_async_boundary(call)
                    if async_type:
                        call.is_async_dispatch = True
                        call.async_type = async_type

                    annotation = detector.annotate_call(call)
                    if annotation:
                        func.annotations.update(annotation)

            for branch in func.branches:
                for call in branch.calls:
                    for detector in detectors:
                        async_type = detector.detect_async_boundary(call)
                        if async_type:
                            call.is_async_dispatch = True
                            call.async_type = async_type
