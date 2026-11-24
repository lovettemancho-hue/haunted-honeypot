"""In-memory fake filesystem. Nothing here touches the real disk.

The only real file read is the YAML seed template, loaded with ``yaml.safe_load``.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

_DIR_SIZE = 4096
_OCTAL_RE = re.compile(r"^[0-7]{3,4}$")
_SYMBOLIC_RE = re.compile(r"^([ugoa]*)([+\-=])([rwx]+)$")


@dataclass
class FakeNode:
    """A file or directory in the fake filesystem."""

    name: str
    is_dir: bool
    content: str  # empty string for directories
    permissions: str  # e.g. "-rw-r--r--" or "drwxr-xr-x"
    owner: str
    size: int  # bytes, shown by ls -la
    mtime: str  # static display string, e.g. "Jan 15  2009"
    children: dict[str, FakeNode] | None  # None for files, dict for directories


def _split(path: str, cwd: list[str]) -> list[str]:
    """Lexically normalise ``path`` into components from the root."""
    parts: list[str] = [] if path.startswith("/") else list(cwd)
    for comp in path.split("/"):
        if comp in ("", "."):
            continue
        if comp == "..":
            if parts:
                parts.pop()
        else:
            parts.append(comp)
    return parts


def _perm_string(is_dir: bool, bits: int) -> str:
    chars = "".join(
        ("r" if bits >> s & 4 else "-")
        + ("w" if bits >> s & 2 else "-")
        + ("x" if bits >> s & 1 else "-")
        for s in (6, 3, 0)
    )
    return ("d" if is_dir else "-") + chars


def _apply_mode(current: str, mode: str) -> str:
    """Return the new permission string for ``mode`` (octal or simple symbolic)."""
    is_dir = current.startswith("d")
    if _OCTAL_RE.match(mode):
        return _perm_string(is_dir, int(mode[-3:], 8))
    match = _SYMBOLIC_RE.match(mode)
    if match is None:
        raise ValueError(f"invalid mode: {mode}")
    who, op, perms = match.groups()
    shifts = {"u": 6, "g": 3, "o": 0}
    targets = list(shifts.values()) if who in ("", "a") or "a" in who else [
        shifts[w] for w in who
    ]
    bits = 0
    for i, ch in enumerate(current[1:10]):
        if ch != "-":
            bits |= 1 << (8 - i)
    change = 0
    for p in perms:
        value = {"r": 4, "w": 2, "x": 1}[p]
        for shift in targets:
            change |= value << shift
    if op == "+":
        bits |= change
    elif op == "-":
        bits &= ~change
    else:
        mask = 0
        for shift in targets:
            mask |= 7 << shift
        bits = (bits & ~mask) | change
    return _perm_string(is_dir, bits)


class FakeFilesystem:
    """Per-session filesystem seeded from a deep copy of a template tree."""

    def __init__(self, template: FakeNode) -> None:
        self._root: FakeNode = copy.deepcopy(template)
        self._cwd: list[str] = []  # path components from root

    # -- helpers ---------------------------------------------------------

    def _walk(self, parts: list[str]) -> FakeNode | None:
        node = self._root
        for comp in parts:
            if not node.is_dir or node.children is None:
                return None
            child = node.children.get(comp)
            if child is None:
                return None
            node = child
        return node

    def _parent_and_name(self, path: str) -> tuple[FakeNode, str]:
        """Return the existing parent directory and final name for ``path``."""
        parts = _split(path, self._cwd)
        if not parts:
            raise FileExistsError(path)
        parent = self._walk(parts[:-1])
        if parent is None:
            raise FileNotFoundError(path)
        if not parent.is_dir or parent.children is None:
            raise NotADirectoryError(path)
        return parent, parts[-1]

    # -- public API ------------------------------------------------------

    def cwd_path(self) -> str:
        return "/" + "/".join(self._cwd)

    def resolve(self, path: str) -> FakeNode | None:
        return self._walk(_split(path, self._cwd))

    def cd(self, path: str) -> None:
        parts = _split(path, self._cwd)
        node = self._walk(parts)
        if node is None:
            raise FileNotFoundError(path)
        if not node.is_dir:
            raise NotADirectoryError(path)
        self._cwd = parts

    def ls(self, path: str | None = None) -> list[FakeNode]:
        node = self._walk(self._cwd) if path is None else self.resolve(path)
        if node is None:
            raise FileNotFoundError(path)
        if not node.is_dir or node.children is None:
            return [node]
        return sorted(node.children.values(), key=lambda n: n.name)

    def cat(self, path: str) -> str:
        node = self.resolve(path)
        if node is None:
            raise FileNotFoundError(path)
        if node.is_dir:
            raise IsADirectoryError(path)
        return node.content

    def mkdir(self, path: str) -> None:
        parent, name = self._parent_and_name(path)
        if parent.children is None or name in parent.children:
            raise FileExistsError(path)
        parent.children[name] = FakeNode(
            name=name,
            is_dir=True,
            content="",
            permissions="drwxr-xr-x",
            owner="root",
            size=_DIR_SIZE,
            mtime=parent.mtime,
            children={},
        )

    def create_file(self, path: str, content: str = "") -> None:
        parent, name = self._parent_and_name(path)
        if parent.children is None:
            raise NotADirectoryError(path)
        existing = parent.children.get(name)
        if existing is not None and existing.is_dir:
            raise IsADirectoryError(path)
        parent.children[name] = FakeNode(
            name=name,
            is_dir=False,
            content=content,
            permissions="-rw-r--r--",
            owner="root",
            size=len(content.encode("utf-8")),
            mtime=parent.mtime,
            children=None,
        )

    def touch(self, path: str) -> None:
        if self.resolve(path) is None:
            self.create_file(path)

    def rm(self, path: str, recursive: bool = False) -> None:
        parts = _split(path, self._cwd)
        if not parts:
            raise PermissionError(path)
        node = self._walk(parts)
        if node is None:
            raise FileNotFoundError(path)
        if node.is_dir and not recursive:
            raise IsADirectoryError(path)
        parent = self._walk(parts[:-1])
        if parent is None or parent.children is None:
            raise FileNotFoundError(path)
        del parent.children[parts[-1]]
        # Keep the cwd valid if it was removed or lived inside the removed tree.
        if self._cwd[: len(parts)] == parts:
            self._cwd = parts[:-1]

    def chmod(self, path: str, mode: str) -> None:
        node = self.resolve(path)
        if node is None:
            raise FileNotFoundError(path)
        node.permissions = _apply_mode(node.permissions, mode)


def _node_from_dict(name: str, data: dict[str, object]) -> FakeNode:
    is_dir = data.get("type") == "dir"
    raw_children = data.get("children")
    children: dict[str, FakeNode] | None = None
    content = ""
    if is_dir:
        children = {}
        if isinstance(raw_children, dict):
            for child_name, child in raw_children.items():
                if isinstance(child, dict):
                    children[str(child_name)] = _node_from_dict(str(child_name), child)
    else:
        content = str(data.get("content", ""))
    return FakeNode(
        name=name,
        is_dir=is_dir,
        content=content,
        permissions=str(data.get("permissions", "drwxr-xr-x" if is_dir else "-rw-r--r--")),
        owner=str(data.get("owner", "root")),
        size=_DIR_SIZE if is_dir else len(content.encode("utf-8")),
        mtime=str(data.get("mtime", "Jan 15  2009")),
        children=children,
    )


def load_template(path: Path) -> FakeNode:
    """Build the template root from a YAML file (``yaml.safe_load`` only)."""
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict) or not isinstance(data.get("root"), dict):
        raise ValueError("fs template must contain a 'root' mapping")
    return _node_from_dict("", data["root"])
