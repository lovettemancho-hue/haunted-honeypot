"""Navigation commands: ``pwd``, ``cd`` and ``ls``.

All handlers operate on the in-memory fake filesystem only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from trap.ghost.dispatcher import CommandResult

if TYPE_CHECKING:
    from trap.ghost.filesystem import FakeNode
    from trap.models import SessionContext


def home_dir(username: str) -> str:
    """Home directory of ``username`` in the fake system."""
    return "/root" if username == "root" else f"/home/{username}"


async def pwd(args: list[str], ctx: SessionContext) -> CommandResult:
    return CommandResult(output=ctx.fs.cwd_path(), is_error=False)


async def cd(args: list[str], ctx: SessionContext) -> CommandResult:
    home = home_dir(ctx.session.username)
    target = args[0] if args else home
    if target == "~" or target.startswith("~/"):
        target = home + target[1:]
    try:
        ctx.fs.cd(target)
    except NotADirectoryError:
        return CommandResult(output=f"bash: cd: {target}: Not a directory", is_error=True)
    except FileNotFoundError:
        return CommandResult(
            output=f"bash: cd: {target}: No such file or directory", is_error=True
        )
    return CommandResult(output="", is_error=False)


def _long_line(node: FakeNode) -> str:
    return (
        f"{node.permissions} 1 {node.owner} {node.owner} "
        f"{node.size:>6} {node.mtime} {node.name}"
    )


async def ls(args: list[str], ctx: SessionContext) -> CommandResult:
    long_format = False
    show_all = False
    paths: list[str] = []
    for arg in args:
        if arg.startswith("-") and len(arg) > 1:
            long_format = long_format or "l" in arg[1:]
            show_all = show_all or "a" in arg[1:]
        else:
            paths.append(arg)

    blocks: list[str] = []
    is_error = False
    for path in paths or [""]:
        try:
            nodes = ctx.fs.ls(path or None)
        except (FileNotFoundError, NotADirectoryError):
            blocks.append(f"ls: cannot access '{path}': No such file or directory")
            is_error = True
            continue
        if not show_all:
            nodes = [n for n in nodes if not n.name.startswith(".")]
        if long_format:
            lines = [f"total {sum(n.size for n in nodes) // 1024}"]
            lines.extend(_long_line(n) for n in nodes)
            body = "\n".join(lines)
        else:
            body = "  ".join(n.name for n in nodes)
        if len(paths) > 1:
            body = f"{path}:\n{body}"
        blocks.append(body)
    return CommandResult(output="\n".join(blocks), is_error=is_error)
