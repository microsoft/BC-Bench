import ast
from collections import deque
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).parents[1] / "src" / "bcbench"
IGNORED_IMPORTERS = frozenset({"bcbench.types"})
CONTRACTS = {
    "Dataset models stay independent of runtime packages": (
        frozenset({"bcbench.dataset"}),
        frozenset(
            {
                "bcbench.agent",
                "bcbench.collection",
                "bcbench.commands",
                "bcbench.contamination",
                "bcbench.evaluate",
                "bcbench.operations",
                "bcbench.results",
            }
        ),
    ),
    "Implementation packages do not depend on the CLI": (
        frozenset(
            {
                "bcbench.agent",
                "bcbench.collection",
                "bcbench.contamination",
                "bcbench.dataset",
                "bcbench.evaluate",
                "bcbench.operations",
                "bcbench.results",
            }
        ),
        frozenset({"bcbench.cli", "bcbench.commands"}),
    ),
    "Evaluation pipelines do not select agent implementations": (
        frozenset({"bcbench.evaluate"}),
        frozenset({"bcbench.agent"}),
    ),
    "Result models stay independent of execution": (
        frozenset({"bcbench.results"}),
        frozenset({"bcbench.agent", "bcbench.evaluate", "bcbench.operations"}),
    ),
}


def _module_name(path: Path) -> str:
    relative_path = path.relative_to(PACKAGE_ROOT)
    parts = relative_path.with_suffix("").parts
    return ".".join(("bcbench", *parts[:-1])) if parts[-1] == "__init__" else ".".join(("bcbench", *parts))


def _package_name(module: str) -> str:
    parts = module.split(".")
    return ".".join(parts[:2]) if len(parts) > 1 else module


def _imported_modules(path: Path) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        match node:
            case ast.Import(names=names):
                imports.update(alias.name for alias in names if alias.name == "bcbench" or alias.name.startswith("bcbench."))
            case ast.ImportFrom(module=module) if module and (module == "bcbench" or module.startswith("bcbench.")):
                imports.add(module)
    return imports


def _package_graph() -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for path in PACKAGE_ROOT.rglob("*.py"):
        importer = _module_name(path)
        source = _package_name(importer)
        graph.setdefault(source, set())
        if importer not in IGNORED_IMPORTERS:
            graph[source].update(_package_name(module) for module in _imported_modules(path) if _package_name(module) != source)
    return graph


def _find_path(graph: dict[str, set[str]], source: str, forbidden: frozenset[str]) -> list[str] | None:
    queue = deque([(source, [source])])
    visited = {source}
    while queue:
        current, path = queue.popleft()
        for dependency in graph.get(current, set()):
            dependency_path = [*path, dependency]
            if dependency in forbidden:
                return dependency_path
            if dependency not in visited:
                visited.add(dependency)
                queue.append((dependency, dependency_path))
    return None


@pytest.mark.parametrize(("sources", "forbidden"), CONTRACTS.values(), ids=CONTRACTS)
def test_import_boundaries_include_indirect_dependencies(sources: frozenset[str], forbidden: frozenset[str]) -> None:
    graph = _package_graph()
    violations = [path for source in sources if (path := _find_path(graph, source, forbidden))]
    assert not violations, "\n".join(" -> ".join(path) for path in violations)
