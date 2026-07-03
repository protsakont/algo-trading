"""Import-isolation architecture test (specs 01/03/05/09).

Violations here are CI failures, not warnings. Rules:
- domain/ imports only stdlib + pydantic (pure core)
- interfaces/ imports only stdlib + pydantic + domain
- strategy/ never imports execution/ or risk/
- risk/ never imports strategy/ or execution/ (direction: execution -> risk -> domain)
- nautilus_trader never appears outside its adapter homes (backtest/, execution/, data/)
- vectorbt never appears anywhere in src/ — research triage lives in research/,
  outside the deployable package (spec 03)
"""

import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "algotrade"
STDLIB = set(sys.stdlib_module_names)

NAUTILUS_ADAPTER_HOMES = {"backtest", "execution", "data"}


def imports_of(module_path: Path) -> set[str]:
    """Top-level distribution/package names imported by a module.

    Relative imports resolve inside the same subpackage and are reported as
    their absolute ``algotrade.<subpackage>`` form.
    """
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                relative_to = module_path.parent.relative_to(SRC.parent)
                found.add(".".join(relative_to.parts[: len(relative_to.parts) - node.level + 1]))
            elif node.module:
                found.add(node.module.split(".")[0])
    return found


def algotrade_subpackages_imported(module_path: Path) -> set[str]:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            parts = node.module.split(".")
            if parts[0] == "algotrade" and len(parts) > 1:
                found.add(parts[1])
        elif isinstance(node, ast.ImportFrom) and node.level > 0:
            relative_to = module_path.parent.relative_to(SRC)
            anchor = relative_to.parts[: len(relative_to.parts) - node.level + 1]
            if anchor:
                found.add(anchor[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == "algotrade" and len(parts) > 1:
                    found.add(parts[1])
    return found


def modules_under(subpackage: str) -> list[Path]:
    return sorted((SRC / subpackage).rglob("*.py"))


def test_domain_imports_only_stdlib_and_pydantic() -> None:
    allowed = STDLIB | {"pydantic", "algotrade.domain"}
    for module in modules_under("domain"):
        illegal = imports_of(module) - allowed
        assert not illegal, f"{module.name}: domain must stay pure, found {sorted(illegal)}"


def test_interfaces_import_only_domain() -> None:
    for module in modules_under("interfaces"):
        illegal = algotrade_subpackages_imported(module) - {"domain", "interfaces"}
        assert not illegal, (
            f"{module.name}: interfaces may depend only on domain, found {sorted(illegal)}"
        )


def test_strategy_never_imports_execution_or_risk() -> None:
    for module in modules_under("strategy"):
        illegal = algotrade_subpackages_imported(module) & {"execution", "risk"}
        assert not illegal, (
            f"{module.name}: strategy must not know about {sorted(illegal)} (spec 03)"
        )


def test_risk_never_imports_strategy_or_execution() -> None:
    for module in modules_under("risk"):
        illegal = algotrade_subpackages_imported(module) & {"strategy", "execution"}
        assert not illegal, (
            f"{module.name}: risk depends only on domain (spec 05), found {sorted(illegal)}"
        )


def test_nautilus_confined_to_adapter_packages() -> None:
    for module in SRC.rglob("*.py"):
        subpackage = module.relative_to(SRC).parts[0] if module.parent != SRC else "(root)"
        if subpackage in NAUTILUS_ADAPTER_HOMES:
            continue
        leaked = imports_of(module) & {"nautilus_trader"}
        assert not leaked, (
            f"{module.relative_to(SRC)}: nautilus_trader may only be imported inside "
            f"{sorted(NAUTILUS_ADAPTER_HOMES)} adapters (CLAUDE.md rule 3)"
        )


def test_vectorbt_never_inside_deployable_package() -> None:
    for module in SRC.rglob("*.py"):
        assert "vectorbt" not in imports_of(module), (
            f"{module.relative_to(SRC)}: vectorbt is research-triage only and lives in "
            "research/ outside src/ (spec 03, CLAUDE.md stack)"
        )
