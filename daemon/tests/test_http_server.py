"""Tests for the aiohttp HTTP server (handle_hook, handle_health, handle_status)."""

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from claude_monitor.http_server import create_app
from claude_monitor.session_tracker import SessionTracker


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tracker() -> SessionTracker:
    return SessionTracker(stale_timeout=60)


@pytest_asyncio.fixture
async def client(tracker) -> TestClient:
    """Spin up a real aiohttp test server and return a TestClient."""
    app = create_app(tracker)
    async with TestClient(TestServer(app)) as c:
        yield c


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


class TestHealth:
    @pytest.mark.asyncio
    async def test_health_returns_200(self, client):
        resp = await client.get("/health")
        assert resp.status == 200
        text = await resp.text()
        assert text == "ok"


# ---------------------------------------------------------------------------
# /hook — valid events
# ---------------------------------------------------------------------------


class TestHookValid:
    @pytest.mark.asyncio
    async def test_session_start_creates_session(self, client, tracker):
        resp = await client.post(
            "/hook",
            json={"hook_event_name": "SessionStart", "session_id": "sess-001"},
        )
        assert resp.status == 200
        assert "sess-001" in tracker.sessions

    @pytest.mark.asyncio
    async def test_user_prompt_sets_thinking(self, client, tracker):
        await client.post(
            "/hook",
            json={"hook_event_name": "SessionStart", "session_id": "sess-002"},
        )
        resp = await client.post(
            "/hook",
            json={"hook_event_name": "UserPromptSubmit", "session_id": "sess-002"},
        )
        assert resp.status == 200
        assert tracker.sessions["sess-002"].state == "THINKING"

    @pytest.mark.asyncio
    async def test_returns_ok_text(self, client):
        resp = await client.post(
            "/hook",
            json={"hook_event_name": "SessionStart", "session_id": "sess-003"},
        )
        assert await resp.text() == "ok"


# ---------------------------------------------------------------------------
# /hook — malformed / missing fields
# ---------------------------------------------------------------------------


class TestHookErrors:
    @pytest.mark.asyncio
    async def test_malformed_json_returns_400(self, client):
        resp = await client.post(
            "/hook",
            data="not-json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_missing_hook_event_name_returns_400(self, client):
        resp = await client.post(
            "/hook",
            json={"session_id": "sess-x"},
        )
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_missing_session_id_returns_400(self, client):
        resp = await client.post(
            "/hook",
            json={"hook_event_name": "SessionStart"},
        )
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_both_missing_returns_400(self, client):
        resp = await client.post("/hook", json={})
        assert resp.status == 400


# ---------------------------------------------------------------------------
# /hook — X-PPID / X-TTY header extraction
# ---------------------------------------------------------------------------


class TestHookHeaders:
    @pytest.mark.asyncio
    async def test_x_ppid_stored_on_session(self, client, tracker):
        resp = await client.post(
            "/hook",
            json={"hook_event_name": "SessionStart", "session_id": "sess-hdr1"},
            headers={"X-PPID": "12345"},
        )
        assert resp.status == 200
        assert tracker.sessions["sess-hdr1"].ppid == "12345"

    @pytest.mark.asyncio
    async def test_x_tty_stored_on_session(self, client, tracker):
        resp = await client.post(
            "/hook",
            json={"hook_event_name": "SessionStart", "session_id": "sess-hdr2"},
            headers={"X-TTY": "/dev/pts/3"},
        )
        assert resp.status == 200
        assert tracker.sessions["sess-hdr2"].tty == "/dev/pts/3"

    @pytest.mark.asyncio
    async def test_missing_headers_default_to_empty(self, client, tracker):
        resp = await client.post(
            "/hook",
            json={"hook_event_name": "SessionStart", "session_id": "sess-hdr3"},
        )
        assert resp.status == 200
        info = tracker.sessions["sess-hdr3"]
        assert info.ppid == ""
        assert info.tty == ""


# ---------------------------------------------------------------------------
# /status
# ---------------------------------------------------------------------------


class TestStatus:
    @pytest.mark.asyncio
    async def test_empty_status(self, client):
        resp = await client.get("/status")
        assert resp.status == 200
        data = await resp.json()
        assert data["sessions"] == {}
        assert "ble_connected" in data

    @pytest.mark.asyncio
    async def test_status_contains_active_sessions(self, client, tracker):
        await client.post(
            "/hook",
            json={"hook_event_name": "SessionStart", "session_id": "sess-st1"},
        )
        resp = await client.get("/status")
        assert resp.status == 200
        data = await resp.json()
        sessions = data["sessions"]
        assert "sess-st1" in sessions
        assert "state" in sessions["sess-st1"]
        assert "label" in sessions["sess-st1"]

    @pytest.mark.asyncio
    async def test_status_reflects_state_change(self, client, tracker):
        await client.post(
            "/hook",
            json={"hook_event_name": "SessionStart", "session_id": "sess-st2"},
        )
        await client.post(
            "/hook",
            json={"hook_event_name": "PreToolUse", "session_id": "sess-st2"},
        )
        resp = await client.get("/status")
        data = await resp.json()
        assert data["sessions"]["sess-st2"]["state"] == "TOOL_USE"
