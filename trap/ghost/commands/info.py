"""Info commands: ``whoami``, ``id``, ``uname``, ``hostname`` and ``echo``.

All output is static text derived from the session; nothing is executed and
``echo`` performs no expansion of any kind.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from trap.ghost.dispatcher import CommandResult

if TYPE_CHECKING:
    from trap.models import SessionContext

HOSTNAME = "records-srv-09"
KERNEL_RELEASE = "2.6.18-92.el5"
KERNEL_VERSION = "#1 SMP Tue Apr 29 13:16:15 EDT 2009"
MACHINE = "x86_64"


async def whoami(args: list[str], ctx: SessionContext) -> CommandResult:
    return CommandResult(output=ctx.session.username, is_error=False)


async def id_(args: list[str], ctx: SessionContext) -> CommandResult:
    username = ctx.session.username
    if username == "root":
        output = "uid=0(root) gid=0(root) groups=0(root)"
    else:
        output = f"uid=1000({username}) gid=1000({username}) groups=1000({username})"
    return CommandResult(output=output, is_error=False)


async def uname(args: list[str], ctx: SessionContext) -> CommandResult:
    flags = "".join(a[1:] for a in args if a.startswith("-") and len(a) > 1)
    if "a" in flags:
        output = (
            f"Linux {HOSTNAME} {KERNEL_RELEASE} {KERNEL_VERSION} "
            f"{MACHINE} {MACHINE} {MACHINE} GNU/Linux"
        )
    elif "r" in flags:
        output = KERNEL_RELEASE
    elif "n" in flags:
        output = HOSTNAME
    elif "m" in flags:
        output = MACHINE
    else:
        output = "Linux"
    return CommandResult(output=output, is_error=False)


async def hostname(args: list[str], ctx: SessionContext) -> CommandResult:
    return CommandResult(output=HOSTNAME, is_error=False)


async def echo(args: list[str], ctx: SessionContext) -> CommandResult:
    return CommandResult(output=" ".join(args), is_error=False)
