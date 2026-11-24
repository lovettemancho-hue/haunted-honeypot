"""Unit tests for the fake filesystem."""

from __future__ import annotations

import pytest

from trap.ghost.filesystem import FakeFilesystem, FakeNode


def _dir(name: str, children: dict[str, FakeNode] | None = None) -> FakeNode:
    return FakeNode(name, True, "", "drwxr-xr-x", "root", 4096, "Jan 15  2009", children or {})


def _file(name: str, content: str = "") -> FakeNode:
    return FakeNode(name, False, content, "-rw-r--r--", "root", len(content), "Jan 15  2009", None)


@pytest.fixture
def fs() -> FakeFilesystem:
    root = _dir(
        "",
        {
            "etc": _dir("etc", {"hostname": _file("hostname", "records-srv-09\n")}),
            "root": _dir("root"),
            "tmp": _dir("tmp", {"sub": _dir("sub", {"f": _file("f", "x")})}),
        },
    )
    return FakeFilesystem(root)


def test_cwd_starts_at_root(fs: FakeFilesystem) -> None:
    assert fs.cwd_path() == "/"


def test_resolve_absolute_and_relative(fs: FakeFilesystem) -> None:
    node = fs.resolve("/etc/hostname")
    assert node is not None and node.name == "hostname"
    fs.cd("/etc")
    rel = fs.resolve("hostname")
    assert rel is node


def test_resolve_dotdot_and_dot(fs: FakeFilesystem) -> None:
    fs.cd("/tmp/sub")
    assert fs.resolve("..") is fs.resolve("/tmp")
    assert fs.resolve(".") is fs.resolve("/tmp/sub")
    assert fs.resolve("../../etc") is fs.resolve("/etc")


def test_dotdot_from_root_stays_at_root(fs: FakeFilesystem) -> None:
    assert fs.resolve("/..") is fs.resolve("/")
    fs.cd("..")
    assert fs.cwd_path() == "/"


def test_cd_existing(fs: FakeFilesystem) -> None:
    fs.cd("/tmp/sub")
    assert fs.cwd_path() == "/tmp/sub"
    fs.cd("..")
    assert fs.cwd_path() == "/tmp"


def test_cd_missing_leaves_cwd_unchanged(fs: FakeFilesystem) -> None:
    fs.cd("/tmp")
    with pytest.raises(FileNotFoundError):
        fs.cd("/nope")
    assert fs.cwd_path() == "/tmp"


def test_cd_into_file_errors(fs: FakeFilesystem) -> None:
    with pytest.raises(NotADirectoryError):
        fs.cd("/etc/hostname")


def test_mkdir_success_and_collision(fs: FakeFilesystem) -> None:
    fs.mkdir("/tmp/new")
    assert [n.name for n in fs.ls("/tmp")] == ["new", "sub"]
    with pytest.raises(FileExistsError):
        fs.mkdir("/tmp/new")


def test_touch_creates_and_is_noop_on_existing(fs: FakeFilesystem) -> None:
    fs.touch("/tmp/a")
    assert fs.cat("/tmp/a") == ""
    fs.touch("/etc/hostname")
    assert fs.cat("/etc/hostname") == "records-srv-09\n"


def test_rm_file(fs: FakeFilesystem) -> None:
    fs.rm("/tmp/sub/f")
    assert fs.resolve("/tmp/sub/f") is None


def test_rm_dir_requires_recursive(fs: FakeFilesystem) -> None:
    with pytest.raises(IsADirectoryError):
        fs.rm("/tmp/sub")
    fs.rm("/tmp/sub", recursive=True)
    assert fs.resolve("/tmp/sub") is None


def test_rm_missing_errors(fs: FakeFilesystem) -> None:
    with pytest.raises(FileNotFoundError):
        fs.rm("/tmp/ghost")


def test_cat_file_dir_missing(fs: FakeFilesystem) -> None:
    assert fs.cat("/etc/hostname") == "records-srv-09\n"
    with pytest.raises(IsADirectoryError):
        fs.cat("/etc")
    with pytest.raises(FileNotFoundError):
        fs.cat("/etc/missing")


def test_chmod_octal_and_symbolic(fs: FakeFilesystem) -> None:
    fs.chmod("/etc/hostname", "755")
    assert fs.resolve("/etc/hostname").permissions == "-rwxr-xr-x"  # type: ignore[union-attr]
    fs.chmod("/etc/hostname", "u-x")
    assert fs.resolve("/etc/hostname").permissions == "-rw-r-xr-x"  # type: ignore[union-attr]


def test_chmod_missing_errors(fs: FakeFilesystem) -> None:
    with pytest.raises(FileNotFoundError):
        fs.chmod("/nope", "755")


def test_create_file_with_content(fs: FakeFilesystem) -> None:
    fs.create_file("/tmp/hello.txt", "hi")
    assert fs.cat("/tmp/hello.txt") == "hi"
    node = fs.resolve("/tmp/hello.txt")
    assert node is not None and node.size == 2


def test_sessions_are_isolated() -> None:
    template = _dir("", {"tmp": _dir("tmp")})
    a, b = FakeFilesystem(template), FakeFilesystem(template)
    a.mkdir("/tmp/x")
    assert b.resolve("/tmp/x") is None
    assert template.children is not None and template.children["tmp"].children == {}
