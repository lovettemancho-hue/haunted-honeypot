"""Static checks on the brain deployment shape and production code.

Validates: Requirements 1.6, 8.4, 12.2, 12.3, 12.5, 12.6, 12.7
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
BRAIN_DIR = REPO_ROOT / "brain"
COMPOSE_PATH = REPO_ROOT / "deploy" / "docker-compose.yml"


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    data = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _production_files() -> list[Path]:
    return [
        p
        for p in BRAIN_DIR.rglob("*.py")
        if "tests" not in p.relative_to(BRAIN_DIR).parts
        and ".egg-info" not in str(p)
    ]


def test_brain_mounts_logs_read_only_and_own_db_volume(compose: dict[str, Any]) -> None:
    volumes = compose["services"]["brain"]["volumes"]
    log_mounts = [v for v in volumes if v.startswith("trap_logs:")]
    assert len(log_mounts) == 1
    assert log_mounts[0].endswith(":ro")
    assert any(v.startswith("brain_db:") and not v.endswith(":ro") for v in volumes)


def test_brain_is_hardened(compose: dict[str, Any]) -> None:
    brain = compose["services"]["brain"]
    assert "ALL" in brain["cap_drop"]
    assert any(s.startswith("no-new-privileges") for s in brain["security_opt"])
    assert "mem_limit" in brain
    assert "cpus" in brain


def test_trap_and_brain_networks_are_separate(compose: dict[str, Any]) -> None:
    services = compose["services"]
    trap_nets = set(services["trap"]["networks"])
    brain_nets = set(services["brain"]["networks"])
    assert trap_nets
    assert brain_nets
    assert trap_nets.isdisjoint(brain_nets)


def test_trap_does_not_mount_database_volume(compose: dict[str, Any]) -> None:
    trap_volumes = compose["services"]["trap"]["volumes"]
    assert not any(v.split(":")[0] == "brain_db" for v in trap_volumes)


def test_brain_production_code_has_no_process_execution() -> None:
    files = _production_files()
    assert files
    offenders: list[str] = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(a.name.split(".")[0] == "subprocess" for a in node.names):
                    offenders.append(f"{path.name}: import subprocess")
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "").split(".")[0] == "subprocess":
                    offenders.append(f"{path.name}: from subprocess")
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in {"eval", "exec"}:
                    offenders.append(f"{path.name}:{node.lineno}: {func.id}()")
                elif (
                    isinstance(func, ast.Attribute)
                    and func.attr == "system"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "os"
                ):
                    offenders.append(f"{path.name}:{node.lineno}: os.system()")
    assert offenders == []


def test_deps_uses_compare_digest() -> None:
    source = (BRAIN_DIR / "api" / "deps.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "compare_digest"
    ]
    assert calls
