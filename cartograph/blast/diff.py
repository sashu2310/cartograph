"""Diff parsing and file-to-function mapping for blast radius analysis."""

import subprocess
from pathlib import Path


class GitDiffError(Exception):
    def __init__(self, returncode: int, stderr: str) -> None:
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"git diff failed (exit {returncode}): {stderr}")


def parse_changed_files(diff_text: str, repo_root: Path) -> list[Path]:
    """Parse +++ b/... lines from a unified diff. Returns repo-relative paths.

    Excludes /dev/null. Strips a/ and b/ prefixes. Deduplicates.
    """
    seen: set[str] = set()
    result: list[Path] = []

    for line in diff_text.splitlines():
        if not line.startswith("+++ "):
            continue
        path_str = line[4:].strip()
        # Skip deleted files
        if path_str == "/dev/null":
            continue
        # Strip b/ prefix (unified diff format)
        if path_str.startswith("b/") or path_str.startswith("a/"):
            path_str = path_str[2:]

        if path_str not in seen:
            seen.add(path_str)
            result.append(Path(path_str))

    return result


def git_diff_head(repo_root: Path) -> str:
    """Run git -C {repo_root} diff HEAD. Returns stdout.

    On nonzero return, raise GitDiffError(returncode, stderr).
    """
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "diff", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise GitDiffError(proc.returncode, proc.stderr)
    return proc.stdout


def functions_in_files(index: "object", files: list[Path]) -> list[str]:
    """Return all function qnames whose source file matches any of the given paths.

    Match is by full project-root-relative path, NOT by basename. Two modules
    named ``utils.py`` in different packages will not collapse. Files passed
    as absolute paths are resolved relative to ``index.root_path``; files
    passed as already-relative paths are used as-is.

    An entry in ``files`` that doesn't resolve into the project is silently
    skipped.
    """
    root = Path(index.root_path).resolve()

    def _normalize(p: Path) -> Path | None:
        candidate = p if p.is_absolute() else root / p
        try:
            return candidate.resolve().relative_to(root)
        except ValueError:
            return None

    target_relpaths: set[Path] = set()
    for f in files:
        rel = _normalize(f)
        if rel is not None:
            target_relpaths.add(rel)

    result: list[str] = []
    for module in index.modules.values():
        module_rel = _normalize(Path(module.file_path))
        if module_rel is not None and module_rel in target_relpaths:
            for func in module.functions:
                result.append(func.qualified_name)

    return result
