"""Repository execution boundaries, separate from #67's internal app layer/DAG rules.

Decision: #86 — shared app code must not import review tools, experiments or tests.
Scan syntax without importing modules, including gated/function-local imports and
namespace packages. This is an architecture guard, not a Python sandbox: arbitrary
reflection/exec is outside its scope. Recognized dynamic imports must use literals.
"""

import ast
from importlib.util import resolve_name
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXTERNAL_ROOTS = {"tools", "scripts", "tests"}
# Decision #86: stage 3 removed the app.main -> scripts.sim.walk.lab edge.
# Keep the empty allowlist so any new repository dependency fails.
KNOWN_EDGES: set[tuple[str, str]] = set()


def _modules(root: Path) -> dict[str, Path]:
    modules = {}
    for name in ("app", *sorted(EXTERNAL_ROOTS)):
        folder = root / name
        for path in sorted(folder.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            parts = path.relative_to(root).with_suffix("").parts
            module = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
            modules[module] = path
    return modules


def _targets(tree: ast.AST, package: str, modules: set[str]) -> set[str]:
    """Resolve from-imports to module endpoints, not imported function names."""
    targets = set()
    importlibs, importers = set(), {"__import__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
            importlibs.update(
                alias.asname or alias.name for alias in node.names if alias.name == "importlib"
            )
        elif isinstance(node, ast.ImportFrom):
            base = resolve_name("." * node.level + (node.module or ""), package)
            for alias in node.names:
                candidate = f"{base}.{alias.name}"
                # Packages without __init__.py are importable too.
                is_module = candidate in modules or any(
                    module.startswith(candidate + ".") for module in modules
                )
                targets.add(candidate if is_module else base)
                if base == "importlib" and alias.name == "import_module":
                    importers.add(alias.asname or alias.name)
                if base == "builtins" and alias.name == "__import__":
                    importers.add(alias.asname or alias.name)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        direct = isinstance(fn, ast.Name) and fn.id in importers
        qualified = (
            isinstance(fn, ast.Attribute)
            and fn.attr == "import_module"
            and isinstance(fn.value, ast.Name)
            and fn.value.id in importlibs
        )
        if not (direct or qualified):
            continue
        keywords = {kw.arg: kw.value for kw in node.keywords}
        name = node.args[0] if node.args else keywords.get("name")
        assert isinstance(name, ast.Constant) and isinstance(name.value, str), (
            f"Unresolved dynamic import at line {node.lineno}; use a literal module name"
        )
        target = name.value
        if target.startswith("."):
            pkg = node.args[1] if len(node.args) > 1 else keywords.get("package")
            assert isinstance(pkg, ast.Constant) and isinstance(pkg.value, str), (
                f"Unresolved dynamic import package at line {node.lineno}"
            )
            target = resolve_name(target, pkg.value)
        targets.add(target)
    return targets


def _check_repository(root: Path, known: set[tuple[str, str]]) -> set[tuple[str, str]]:
    modules = _modules(root)
    assert "app.main" in modules, "Missing app.main; repository scan root is incomplete"
    for source, target in sorted(known):
        assert source in modules and target in modules, (
            f"Missing exception endpoint: {source} -> {target}"
        )
    found = set()
    for source, path in modules.items():
        if source != "app" and not source.startswith("app."):
            continue
        package = source if path.name == "__init__.py" else source.rpartition(".")[0]
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for target in _targets(tree, package, set(modules)):
            if target.split(".")[0] in EXTERNAL_ROOTS:
                found.add((source, target))
    new, stale = found - known, known - found
    assert not new, f"New app -> tools/scripts/tests imports: {sorted(new)}"
    assert not stale, f"Remove resolved repository import exceptions: {sorted(stale)}"
    return found


def test_app_does_not_gain_repository_tool_dependencies():
    _check_repository(ROOT, KNOWN_EDGES)


# Exercise the same checker on disposable source trees, not only the AST helper.
def _write(root: Path, name: str, content: str = ""):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.mark.parametrize(
    "statement",
    [
        "import tools.review",
        "import os, scripts.sim.walk.lab as lab",
        "from tests.helpers import make_fixture",
        "from tools import review",
        "if False:\n    from scripts.sim.walk.lab import router",
        "def build():\n    import tools.review",
        "import importlib as loader\nloader.import_module('tools.review')",
        "from importlib import import_module as load\nload('tests.helpers')",
        "__import__('scripts.sim.walk.lab')",
        "import importlib\nimportlib.import_module('.review', package='tools')",
    ],
)
def test_new_import_forms_fail_the_repository_check(tmp_path, statement):
    _write(tmp_path, "app/main.py", statement)
    _write(tmp_path, "tools/review.py")
    with pytest.raises(AssertionError, match="New app ->"):
        _check_repository(tmp_path, set())


@pytest.mark.parametrize("path", ["app/__init__.py", "app/new_feature/adapter.py"])
def test_package_initializers_and_namespace_modules_are_scanned(tmp_path, path):
    _write(tmp_path, "app/main.py")
    _write(tmp_path, path, "import tools.review")
    with pytest.raises(AssertionError, match="New app ->"):
        _check_repository(tmp_path, set())


def test_internal_relative_imports_and_tool_consumers_are_allowed(tmp_path):
    _write(tmp_path, "app/main.py", "from . import tools\nfrom .feature import run")
    _write(tmp_path, "app/tools.py")  # app.tools is not the repository tools package.
    _write(tmp_path, "app/feature/__init__.py", "from .worker import run")
    _write(tmp_path, "app/feature/worker.py", "from .. import tools")
    _write(tmp_path, "tools/review.py", "from app.main import app\nimport scripts.sim")
    _write(tmp_path, "scripts/spikes/demo.py", "from app.feature import run")
    _write(tmp_path, "tests/test_feature.py", "from app.feature import run")
    assert _check_repository(tmp_path, set()) == set()


def test_exception_is_exact_and_must_disappear_with_its_import(tmp_path):
    known = {("app.main", "scripts.sim.walk.lab")}
    _write(tmp_path, "app/main.py", "from scripts.sim.walk.lab import router")
    _write(tmp_path, "scripts/sim/walk/lab.py")
    assert _check_repository(tmp_path, known) == known
    # An alternative from-import of the same real module has the same endpoint.
    _write(tmp_path, "app/main.py", "from scripts.sim.walk import lab")
    assert _check_repository(tmp_path, known) == known
    _write(tmp_path, "app/other.py", "from scripts.sim.walk.lab import router")
    with pytest.raises(AssertionError, match="New app ->"):
        _check_repository(tmp_path, known)
    _write(tmp_path, "app/other.py")
    _write(tmp_path, "app/main.py", "import scripts.sim.walk.other_lab")
    with pytest.raises(AssertionError, match="New app ->"):
        _check_repository(tmp_path, known)
    _write(tmp_path, "app/main.py")
    with pytest.raises(AssertionError, match="Remove resolved"):
        _check_repository(tmp_path, known)


@pytest.mark.parametrize("missing", ["app/main.py", "scripts/sim/walk/lab.py"])
def test_missing_scan_root_or_exception_file_fails(tmp_path, missing):
    known = {("app.main", "scripts.sim.walk.lab")}
    _write(tmp_path, "app/main.py", "from scripts.sim.walk.lab import router")
    _write(tmp_path, "scripts/sim/walk/lab.py")
    (tmp_path / missing).unlink()
    with pytest.raises(AssertionError, match="Missing"):
        _check_repository(tmp_path, known)


def test_computed_dynamic_import_is_not_silently_ignored(tmp_path):
    _write(tmp_path, "app/main.py", "import importlib\nimportlib.import_module(target)")
    with pytest.raises(AssertionError, match="Unresolved dynamic import"):
        _check_repository(tmp_path, set())
