"""Property tests for the Brain API (Properties 15, 20, 22, 24, 25, 26).

Feature: brain. Each example resets one shared temp-file SQLite database, seeds
it directly through SQLModel, and queries the app through a ``TestClient``.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlmodel import Session as DBSession
from sqlmodel import SQLModel

from brain.config import Config
from brain.db import create_db_and_tables, make_engine
from brain.iocs import defang
from brain.main import create_app
from brain.models import Event, LabNote, Technique
from brain.models import Session as SessionRow

TOKEN = "test-token"
BASE = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
AUTH = {"Authorization": f"Bearer {TOKEN}"}

_text = st.text(alphabet=st.characters(blacklist_characters="\x00"), max_size=40)
_nonempty_text = st.text(
    alphabet=st.characters(blacklist_characters="\x00"), min_size=1, max_size=40
)
# Attacker-style text that tends to trip up renderers.
_nasty = st.one_of(
    _text,
    st.sampled_from(
        ["<script>alert(1)</script>", "`id`", "**bold** [x](http://e.com)", "{{7*7}}", "&amp;"]
    ),
)


@pytest.fixture(scope="module")
def env() -> Iterator[tuple[Any, TestClient]]:
    tmp = Path(tempfile.mkdtemp(prefix="brain-api-prop-"))
    engine = make_engine(tmp / "api.db")
    create_db_and_tables(engine)
    config = Config(log_dir=tmp, api_token=TOKEN, database_path=tmp / "api.db")
    app = create_app(config=config, engine=engine, start_ingest=False)
    yield engine, TestClient(app)
    engine.dispose()
    shutil.rmtree(tmp, ignore_errors=True)


def _reset(engine: Any) -> None:
    with DBSession(engine) as db:
        for table in reversed(SQLModel.metadata.sorted_tables):
            db.execute(table.delete())
        db.commit()


def _login(username: str, password: str, success: bool) -> tuple[str, dict[str, Any]]:
    return "login_attempt", {"username": username, "password": password, "success": success}


# --- Property 15 -----------------------------------------------------------


@settings(max_examples=40, deadline=None)
@given(
    note=_nasty,
    username=_nasty,
    password=_nasty,
    command=_nasty,
    version=_nasty,
)
def test_property_15_attacker_strings_pass_through_unrendered(
    env: tuple[Any, TestClient],
    note: str,
    username: str,
    password: str,
    command: str,
    version: str,
) -> None:
    """Feature: brain, Property 15: attacker strings pass through unrendered.

    **Validates: Requirements 6.10, 8.5**
    """
    engine, client = env
    _reset(engine)
    with DBSession(engine) as db:
        db.add(
            SessionRow(
                id="s1",
                src_ip="203.0.113.5",
                src_port=4000,
                username=username,
                password=password,
                client_version=version,
                started_at=BASE,
                ended_at=BASE + timedelta(seconds=5),
            )
        )
        db.add(
            Event(
                session_id="s1",
                timestamp=BASE,
                kind="command",
                payload=json.dumps({"command": command}),
                generated_by="scripted",
            )
        )
        db.add(
            LabNote(session_id="s1", text=note, generated_by="template", created_at=BASE)
        )
        db.commit()

    resp = client.get("/api/sessions/s1", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["lab_note"] == note
    assert body["username"] == username
    assert body["password"] == password
    assert body["client_version"] == version
    assert body["events"][0]["payload"]["command"] == command
    assert resp.headers["content-type"].startswith("application/json")
    listed = client.get("/api/sessions", headers=AUTH).json()
    assert listed[0]["username"] == username


# --- Property 20 -----------------------------------------------------------

_bad_tokens = st.text(
    alphabet=st.characters(min_codepoint=0x21, max_codepoint=0x7E), max_size=30
).filter(lambda t: t != TOKEN)
_endpoints = st.sampled_from(
    ["/api/stats", "/api/sessions", "/api/sessions/secret-id", "/api/containment"]
)


@settings(max_examples=60, deadline=None)
@given(
    path=_endpoints,
    token=_bad_tokens,
    mode=st.sampled_from(["missing", "wrong", "wrong_scheme"]),
)
def test_property_20_bad_auth_never_returns_data(
    env: tuple[Any, TestClient], path: str, token: str, mode: str
) -> None:
    """Feature: brain, Property 20: bad auth never returns session data.

    **Validates: Requirements 8.2, 8.3**
    """
    engine, client = env
    _reset(engine)
    with DBSession(engine) as db:
        db.add(
            SessionRow(
                id="secret-id",
                src_ip="198.51.100.77",
                src_port=1,
                username="SECRETUSER",
                client_version="SSH-2.0-SECRETCLIENT",
                started_at=BASE,
            )
        )
        db.commit()
    headers: dict[str, str] = {}
    if mode == "wrong":
        headers = {"Authorization": f"Bearer {token}"}
    elif mode == "wrong_scheme":
        headers = {"Authorization": f"Basic {TOKEN}"}
    resp = client.get(path, headers=headers)
    assert resp.status_code == 401
    for marker in ("secret-id", "198.51.100.77", "SECRETUSER", "SECRETCLIENT"):
        assert marker not in resp.text


# --- Property 22 -----------------------------------------------------------

_ATTACK_IDS = ["T1110", "T1078", "T1082", "T1105", "T1059.004"]

_session_spec = st.fixed_dictionaries(
    {
        "ip": st.sampled_from(["10.0.0.1", "10.0.0.2", "10.0.0.3", "2001:db8::1"]),
        "duration": st.one_of(st.none(), st.integers(min_value=0, max_value=100_000)),
        "logins": st.lists(
            st.tuples(st.sampled_from(["pw1", "pw2", "pw3", "pw4", "pw5", "pw6"]), st.booleans()),
            max_size=6,
        ),
        "techniques": st.lists(st.sampled_from(_ATTACK_IDS), unique=True, max_size=4),
    }
)


def _seed_stats(engine: Any, specs: list[dict[str, Any]]) -> None:
    with DBSession(engine) as db:
        for i, spec in enumerate(specs):
            sid = f"s{i}"
            ended = None if spec["duration"] is None else BASE + timedelta(seconds=spec["duration"])
            db.add(
                SessionRow(
                    id=sid,
                    src_ip=spec["ip"],
                    src_port=1000 + i,
                    client_version="SSH-2.0-x",
                    started_at=BASE,
                    ended_at=ended,
                )
            )
            for password, success in spec["logins"]:
                kind, payload = _login("root", password, success)
                db.add(
                    Event(
                        session_id=sid,
                        timestamp=BASE,
                        kind=kind,
                        payload=json.dumps(payload),
                        generated_by="scripted",
                    )
                )
            for attack_id in spec["techniques"]:
                db.add(
                    Technique(
                        session_id=sid, attack_id=attack_id, name=attack_id, evidence_event_id=0
                    )
                )
        db.commit()


@settings(max_examples=40, deadline=None)
@given(specs=st.lists(_session_spec, max_size=8))
def test_property_22_stats_match_reference(
    env: tuple[Any, TestClient], specs: list[dict[str, Any]]
) -> None:
    """Feature: brain, Property 22: stats match an independent reference.

    **Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.6, 9.7, 9.8**
    """
    engine, client = env
    _reset(engine)
    _seed_stats(engine, specs)

    all_logins = [login for spec in specs for login in spec["logins"]]
    pw_counts = Counter(pw for pw, _ in all_logins)
    expected_top = sorted(pw_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    durations = [s["duration"] for s in specs if s["duration"] is not None]
    technique_counts = Counter(t for s in specs for t in s["techniques"])

    resp = client.get("/api/stats", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["attempts"] == len(all_logins)
    assert body["unique_ips"] == len({s["ip"] for s in specs})
    assert body["captured"] == sum(1 for s in specs if any(ok for _, ok in s["logins"]))
    assert body["longest_session_seconds"] == (max(durations) if durations else 0)
    assert [(p["password"], p["count"]) for p in body["top_passwords"]] == expected_top
    assert len(body["top_passwords"]) <= 10
    assert body["technique_counts"] == dict(technique_counts)
    assert 0 <= body["threat_level"] <= 10
    if not specs:
        assert body["attempts"] == 0
        assert body["top_passwords"] == []
        assert body["technique_counts"] == {}


# --- Property 24 -----------------------------------------------------------


@settings(max_examples=40, deadline=None)
@given(
    offsets=st.lists(st.integers(min_value=0, max_value=10_000), unique=True, max_size=12),
    open_flags=st.lists(st.booleans(), min_size=12, max_size=12),
    limit=st.one_of(st.none(), st.integers(min_value=0, max_value=300)),
    offset=st.one_of(st.none(), st.integers(min_value=0, max_value=15)),
)
def test_property_24_listing_order_shape_pagination(
    env: tuple[Any, TestClient],
    offsets: list[int],
    open_flags: list[bool],
    limit: int | None,
    offset: int | None,
) -> None:
    """Feature: brain, Property 24: listing is ordered, shaped and paginated.

    **Validates: Requirements 10.1, 10.2, 10.3**
    """
    engine, client = env
    _reset(engine)
    started = {f"s{i}": BASE + timedelta(seconds=o) for i, o in enumerate(offsets)}
    is_open = {f"s{i}": open_flags[i] for i in range(len(offsets))}
    with DBSession(engine) as db:
        for sid, ts in started.items():
            db.add(
                SessionRow(
                    id=sid,
                    src_ip="192.0.2.1",
                    src_port=22,
                    client_version="c",
                    started_at=ts,
                    ended_at=None if is_open[sid] else ts + timedelta(seconds=1),
                )
            )
            db.add(Technique(session_id=sid, attack_id="T1082", name="n", evidence_event_id=0))
        db.commit()

    params: dict[str, int] = {}
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    resp = client.get("/api/sessions", params=params, headers=AUTH)
    assert resp.status_code == 200
    items = resp.json()

    ordered = sorted(started, key=lambda sid: started[sid], reverse=True)
    eff_limit = 50 if limit is None else min(limit, 200)
    eff_offset = offset or 0
    expected = ordered[eff_offset : eff_offset + eff_limit]
    assert [i["id"] for i in items] == expected
    required = {"id", "src_ip", "src_port", "username", "started_at", "ended_at"}
    for item in items:
        assert required <= item.keys()
        assert item["open"] is is_open[item["id"]]
        assert item["techniques"] == ["T1082"]
        assert {"label", "description"} <= item["severity"].keys()


@settings(max_examples=30, deadline=None)
@given(
    bad=st.sampled_from(["-1", "abc", "1.5", "", "x1", "--3"]),
    which=st.sampled_from(["limit", "offset"]),
)
def test_property_24_invalid_pagination_is_422(
    env: tuple[Any, TestClient], bad: str, which: str
) -> None:
    """Feature: brain, Property 24: invalid limit/offset gives 422.

    **Validates: Requirements 10.3**
    """
    _, client = env
    assert client.get("/api/sessions", params={which: bad}, headers=AUTH).status_code == 422


# --- Property 25 -----------------------------------------------------------

_url = st.builds(
    lambda scheme, host, path: f"{scheme}://{host}.example.com/{path}",
    st.sampled_from(["http", "https"]),
    st.text(alphabet="abcdefgh", min_size=1, max_size=5),
    st.text(alphabet="abcdefgh01", min_size=1, max_size=5),
)

_detail_event = st.tuples(
    st.sampled_from(["download", "command_url", "plain"]),
    _url,
)


@settings(max_examples=40, deadline=None)
@given(
    raw_events=st.lists(_detail_event, max_size=10),
    order_seed=st.randoms(use_true_random=False),
    note=st.one_of(st.none(), _nonempty_text),
    techniques=st.lists(st.sampled_from(_ATTACK_IDS), unique=True, max_size=4),
)
def test_property_25_detail_complete_and_iocs_deduped(
    env: tuple[Any, TestClient],
    raw_events: list[tuple[str, str]],
    order_seed: Any,
    note: str | None,
    techniques: list[str],
) -> None:
    """Feature: brain, Property 25: detail is complete, IOCs deduplicated.

    **Validates: Requirements 10.4, 10.5, 10.6**
    """
    engine, client = env
    _reset(engine)
    entries = list(enumerate(raw_events))  # (timestamp offset, (type, url))
    insertion = entries[:]
    order_seed.shuffle(insertion)
    with DBSession(engine) as db:
        db.add(
            SessionRow(
                id="d1",
                src_ip="192.0.2.9",
                src_port=2200,
                username="u",
                password="p",
                client_version="SSH-2.0-c",
                started_at=BASE,
                ended_at=BASE + timedelta(seconds=60),
                end_reason="client_disconnect",
            )
        )
        for ts, (kind, url) in insertion:
            if kind == "download":
                etype, payload = "download_attempt", {"url": url}
            elif kind == "command_url":
                etype, payload = "command", {"command": f"wget {url}"}
            else:
                etype, payload = "command", {"command": "ls"}
            db.add(
                Event(
                    session_id="d1",
                    timestamp=BASE + timedelta(seconds=ts),
                    kind=etype,
                    payload=json.dumps(payload),
                    generated_by="scripted",
                )
            )
        for attack_id in techniques:
            db.add(Technique(session_id="d1", attack_id=attack_id, name="N", evidence_event_id=7))
        if note is not None:
            db.add(LabNote(session_id="d1", text=note, generated_by="template", created_at=BASE))
        db.commit()

    resp = client.get("/api/sessions/d1", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    for key in ("id", "src_ip", "src_port", "username", "password", "client_version",
                "started_at", "ended_at", "end_reason", "severity", "open"):
        assert key in body
    stamps = [e["timestamp"] for e in body["events"]]
    assert stamps == sorted(stamps)
    assert len(body["events"]) == len(raw_events)
    assert {t["attack_id"] for t in body["techniques"]} == set(techniques)
    assert all({"attack_id", "name", "evidence_event_id"} <= t.keys() for t in body["techniques"])
    assert body["lab_note"] == note

    expected: list[str] = []
    for _, (kind, url) in entries:
        if kind != "plain" and defang(url) not in expected:
            expected.append(defang(url))
    assert body["iocs"] == expected
    assert len(body["iocs"]) == len(set(body["iocs"]))
    assert all("http://" not in i and "https://" not in i for i in body["iocs"])


# --- Property 26 -----------------------------------------------------------


@settings(max_examples=60, deadline=None)
@given(fmt=st.text(max_size=20).filter(lambda s: s not in ("json", "script")))
def test_property_26_unsupported_format_is_422(env: tuple[Any, TestClient], fmt: str) -> None:
    """Feature: brain, Property 26: unsupported format values give 422.

    **Validates: Requirements 11.4**
    """
    _, client = env
    resp = client.get("/api/containment", params={"format": fmt}, headers=AUTH)
    assert resp.status_code == 422
