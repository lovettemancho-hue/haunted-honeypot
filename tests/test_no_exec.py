"""AST-based check that trap/ never imports or calls process-execution primitives.

Pure static analysis: no process is started.

Validates: Requirements 10.1
"""

from __future__ import annotations

import ast
from pathlib import Path

TRAP_DIR = Path(__file__).resolve().parent.parent / "trap"

FORBIDDEN_CALL_NAMES = {"eval", "exec"}
FORBIDDEN_OS_ATTRS = {"system", "popen"}


def _forbidden_module(name: str) -> bool:
    return name.startswith("subprocess") or name == "pty"


def find_violations(source: str, filename: str = "<string>") -> list[str]:
    """Return 'file:line: description' for each violation found in ``source``."""
    tree = ast.parse(source, filename=filename)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _forbidden_module(alias.name):
                    found.append(f"{filename}:{node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module and _forbidden_module(node.module):
                found.append(f"{filename}:{node.lineno}: from {node.module} import ...")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in FORBIDDEN_CALL_NAMES:
                found.append(f"{filename}:{node.lineno}: call to {func.id}()")
            elif (
                isinstance(func, ast.Attribute)
                and func.attr in FORBIDDEN_OS_ATTRS
                and isinstance(func.value, ast.Name)
                and func.value.id == "os"
            ):
                found.append(f"{filename}:{node.lineno}: call to os.{func.attr}()")
    return sorted(found)


def test_trap_has_no_forbidden_imports_or_calls() -> None:
    files = sorted(TRAP_DIR.rglob("*.py"))
    assert files, f"no .py files found under {TRAP_DIR}"

    violations: list[str] = []
    for path in files:
        rel = path.relative_to(TRAP_DIR.parent).as_posix()
        violations.extend(find_violations(path.read_text(encoding="utf-8"), rel))

    assert not violations, "Forbidden constructs in trap/:\n" + "\n".join(violations)


def test_checker_detects_violations_in_sample_source() -> None:
    sample = (
        "import subprocess\n"
        "import subprocess.run\n"
        "import pty\n"
        "from subprocess import Popen\n"
        "from pty import spawn\n"
        "import os\n"
        "eval('1')\n"
        "exec('x=1')\n"
        "os.system('ls')\n"
        "os.popen('ls')\n"
    )
    result = find_violations(sample, "sample.py")
    assert len(result) == 9
    for line in (1, 2, 3, 4, 5, 7, 8, 9, 10):
        assert any(v.startswith(f"sample.py:{line}:") for v in result)


def test_checker_accepts_clean_source() -> None:
    clean = "import os\nimport asyncio\nx = os.path.join('a', 'b')\nprint(x)\n"
    assert find_violations(clean, "clean.py") == []
