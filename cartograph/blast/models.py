# cartograph/blast/models.py
from dataclasses import dataclass, field
from enum import StrEnum


class ImpactSeverity(StrEnum):
    DIRECT = "direct"  # function is defined in a changed file
    DOWNSTREAM = "downstream"  # function is called (transitively) by a changed function
    UPSTREAM = "upstream"  # function calls (transitively) a changed function


class BlastInputKind(StrEnum):
    DIFF = "diff"  # parsed from unified diff
    FILES = "files"  # explicit files passed
    FUNCTIONS = "functions"  # explicit qnames passed


@dataclass
class AffectedFunction:
    qualified_name: str  # e.g. "cartograph.core.parse_project"
    module: str  # e.g. "cartograph.core"
    severity: ImpactSeverity
    depth: int  # BFS distance from nearest changed function (0 = direct)
    path_from_change: list[str] = field(
        default_factory=list
    )  # qnames: [change, ..., this]


@dataclass
class AffectedEntryPoint:
    qualified_name: str
    entry_point_type: str  # value of existing EntryPointType str-enum
    trigger: str  # e.g. "@app.get('/users')"
    reached_via: list[str] = field(default_factory=list)  # qname chain


@dataclass
class AffectedTest:
    test_qualified_name: str  # "tests.test_core.TestParseProject.test_empty_dir"
    test_file: str  # repo-relative path e.g. "tests/test_core.py"
    covers: list[str] = field(
        default_factory=list
    )  # in-blast-radius qnames this test references


@dataclass
class BlastStats:
    total_changed_functions: int
    total_downstream: int
    total_upstream: int
    total_entry_points_hit: int
    total_tests_affected: int
    max_depth: int


@dataclass
class BlastRadiusReport:
    input_kind: BlastInputKind
    changed_files: list[str]  # repo-relative paths
    changed_functions: list[str]  # qnames
    affected_functions: list[AffectedFunction]
    affected_entry_points: list[AffectedEntryPoint]
    affected_tests: list[AffectedTest]
    stats: BlastStats
