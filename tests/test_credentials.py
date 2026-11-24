"""Tests for credential list parsing."""

from __future__ import annotations

from pathlib import Path

from trap.auth.credentials import parse_credentials


def test_parse_skips_comments_blanks_and_splits_on_first_colon() -> None:
    text = "# comment\n\nroot:pa:ss\nbad-line\n  \nadmin:admin\n"
    assert parse_credentials(text) == [("root", "pa:ss"), ("admin", "admin")]


def test_default_credentials_file_contains_required_pairs() -> None:
    path = Path(__file__).resolve().parent.parent / "trap" / "credentials_default.txt"
    pairs = set(parse_credentials(path.read_text(encoding="utf-8")))
    users = ["root", "admin", "ubuntu", "pi", "user"]
    passwords = ["123456", "password", "admin", "root", "12345678", "qwerty"]
    assert {(u, p) for u in users for p in passwords} <= pairs
    assert {("pi", "raspberry"), ("ubuntu", "ubuntu"), ("user", "user")} <= pairs
