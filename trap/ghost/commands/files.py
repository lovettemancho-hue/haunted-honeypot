"""File commands: ``cat``, ``touch``, ``rm``, ``mkdir`` and ``chmod``.

All handlers operate on the in-memory fake filesystem only and translate
filesystem exceptions into bash-style error messages.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from trap.ghost.dispatcher import CommandResult

if TYPE_CHECKING:
    from trap.models import SessionContext


def _split_flags(args: list[str]) -> tuple[set[str], list[str]]:
    """Separate short option letters from operands (``--`` ends options)."""
    flags: set[str] = set()
    operands: list[str] = []
    options_done = False
    for arg in args:
        if options_done or not arg.startswith("-") or arg == "-":
            operands.append(arg)
        elif arg == "--":
            options_done = True
        elif arg.startswith("--"):
            flags.add(arg[2:])
        else:
            flags.update(arg[1:])
    return flags, operands


def _finish(lines: list[str]) -> CommandResult:
    return CommandResult(output="\n".join(lines), is_error=bool(lines))


async def cat(args: list[str], ctx: SessionContext) -> CommandResult:
    _, files = _split_flags(args)
    out: list[str] = []
    errors = False
    for path in files:
        try:
            content = ctx.fs.cat(path)
        except FileNotFoundError:
            out.append(f"cat: {path}: No such file or directory")
            errors = True
        except IsADirectoryError:
            out.append(f"cat: {path}: Is a directory")
            errors = True
        except NotADirectoryError:
            out.append(f"cat: {path}: Not a directory")
            errors = True
        else:
            out.append(content.rstrip("\n"))
    return CommandResult(output="\n".join(out), is_error=errors)


async def touch(args: list[str], ctx: SessionContext) -> CommandResult:
    _, files = _split_flags(args)
    if not files:
        return CommandResult(output="touch: missing file operand", is_error=True)
    lines: list[str] = []
    for path in files:
        try:
            ctx.fs.touch(path)
        except FileNotFoundError:
            lines.append(
                f"touch: cannot touch '{path}': No such file or directory"
            )
        except NotADirectoryError:
            lines.append(f"touch: cannot touch '{path}': Not a directory")
        except IsADirectoryError:
            lines.append(f"touch: cannot touch '{path}': Is a directory")
        except FileExistsError:
            lines.append(f"touch: cannot touch '{path}': File exists")
    return _finish(lines)


async def rm(args: list[str], ctx: SessionContext) -> CommandResult:
    flags, paths = _split_flags(args)
    recursive = bool(flags & {"r", "R", "recursive"})
    force = "f" in flags or "force" in flags
    if not paths:
        if force:
            return CommandResult(output="", is_error=False)
        return CommandResult(output="rm: missing operand", is_error=True)
    lines: list[str] = []
    for path in paths:
        try:
            ctx.fs.rm(path, recursive=recursive)
        except FileNotFoundError:
            if not force:
                lines.append(
                    f"rm: cannot remove '{path}': No such file or directory"
                )
        except NotADirectoryError:
            if not force:
                lines.append(f"rm: cannot remove '{path}': Not a directory")
        except IsADirectoryError:
            lines.append(f"rm: cannot remove '{path}': Is a directory")
        except PermissionError:
            lines.append(f"rm: it is dangerous to operate recursively on '{path}'")
    return _finish(lines)


async def mkdir(args: list[str], ctx: SessionContext) -> CommandResult:
    flags, paths = _split_flags(args)
    parents = "p" in flags or "parents" in flags
    if not paths:
        return CommandResult(output="mkdir: missing operand", is_error=True)
    lines: list[str] = []
    for path in paths:
        try:
            ctx.fs.mkdir(path)
        except FileExistsError:
            if not parents:
                lines.append(
                    f"mkdir: cannot create directory '{path}': File exists"
                )
        except FileNotFoundError:
            lines.append(
                f"mkdir: cannot create directory '{path}': No such file or directory"
            )
        except NotADirectoryError:
            lines.append(
                f"mkdir: cannot create directory '{path}': Not a directory"
            )
    return _finish(lines)


async def chmod(args: list[str], ctx: SessionContext) -> CommandResult:
    _, operands = _split_flags([a for a in args if not _is_symbolic_minus(a)])
    # Symbolic modes such as ``-x`` look like flags; treat them as the mode.
    mode_candidates = [a for a in args if _is_symbolic_minus(a)]
    if mode_candidates:
        mode = mode_candidates[0]
        paths = operands
    elif operands:
        mode, paths = operands[0], operands[1:]
    else:
        return CommandResult(output="chmod: missing operand", is_error=True)
    if not paths:
        return CommandResult(
            output=f"chmod: missing operand after '{mode}'", is_error=True
        )
    lines: list[str] = []
    for path in paths:
        try:
            ctx.fs.chmod(path, mode)
        except FileNotFoundError:
            lines.append(f"chmod: cannot access '{path}': No such file or directory")
        except NotADirectoryError:
            lines.append(f"chmod: cannot access '{path}': Not a directory")
        except ValueError:
            return CommandResult(output=f"chmod: invalid mode: '{mode}'", is_error=True)
    return _finish(lines)


def _is_symbolic_minus(arg: str) -> bool:
    """True for symbolic modes that start with ``-`` such as ``-x`` or ``-wx``."""
    return len(arg) > 1 and arg[0] == "-" and set(arg[1:]) <= set("rwxugoa")
