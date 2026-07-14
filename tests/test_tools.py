"""Smoke tests: client resolution, request bodies, error mapping, tool registry.

All HTTP is mocked with respx — no backend needed.
"""

import httpx
import pytest
import respx

import peil_mcp.server as server
from peil_mcp.api import PeilClient, PeilError

BASE = "http://testserver/api/v1"

CLIENTS = [
    {"id": 1, "name": "Acme Corp", "email": "ap@acme.nl", "active": True},
    {"id": 2, "name": "Bureau Bos", "email": None, "active": True},
    {"id": 3, "name": "Acme Studios", "email": None, "active": True},
]


@pytest.fixture
def client(monkeypatch):
    c = PeilClient(api_key="test-key", base_url=BASE)
    monkeypatch.setattr(server, "_client", c)
    return c


@pytest.fixture
def mock_api():
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        mock.get("/clients/").respond(json=CLIENTS)
        yield mock


# ─── PeilClient basics ────────────────────────────────────────────────────────

def test_missing_key_fails_fast(monkeypatch):
    monkeypatch.delenv("PEIL_API_KEY", raising=False)
    with pytest.raises(PeilError, match="PEIL_API_KEY"):
        PeilClient()


def test_auth_header_is_sent(client, mock_api):
    client.list_clients()
    request = mock_api.calls.last.request
    assert request.headers["Authorization"] == "Bearer test-key"


# ─── Client resolution ────────────────────────────────────────────────────────

def test_resolve_exact_match(client, mock_api):
    assert client.resolve_client("acme corp")["id"] == 1


def test_resolve_unique_substring(client, mock_api):
    assert client.resolve_client("bos")["id"] == 2


def test_resolve_ambiguous_lists_candidates(client, mock_api):
    with pytest.raises(PeilError, match="Acme Corp.*Acme Studios"):
        client.resolve_client("acme")


def test_resolve_none_lists_available(client, mock_api):
    with pytest.raises(PeilError, match="No client found.*Bureau Bos"):
        client.resolve_client("nonexistent")


# ─── Error mapping ────────────────────────────────────────────────────────────

def test_401_maps_to_key_message(client, mock_api):
    mock_api.get("/orientation/snapshot").respond(401, json={"detail": "Not authenticated"})
    with pytest.raises(PeilError, match="Invalid or expired"):
        client.get("/orientation/snapshot")


def test_insufficient_scope_names_missing_permission(client, mock_api):
    mock_api.post("/time_entries/").respond(403, json={
        "detail": {"code": "INSUFFICIENT_SCOPE", "required": ["timesheet:write"],
                   "missing": ["timesheet:write"]},
    })
    with pytest.raises(PeilError, match="timesheet:write"):
        client.post("/time_entries/", json={})


def test_plan_gate_maps_to_upgrade_message(client, mock_api):
    mock_api.get("/invoices/").respond(403, json={
        "detail": {"code": "PLAN_UPGRADE_REQUIRED", "feature": "api_access",
                   "required_plan": "pro"},
    })
    with pytest.raises(PeilError, match="Peil Pro"):
        client.get("/invoices/")


def test_machine_readable_422_passes_code_through(client, mock_api):
    mock_api.post("/invoices/from-hours").respond(422, json={
        "detail": {"code": "NO_UNBILLED_ENTRIES", "message": "NO_UNBILLED_ENTRIES"},
    })
    with pytest.raises(PeilError, match="NO_UNBILLED_ENTRIES"):
        client.post("/invoices/from-hours", json={})


# ─── Tools ────────────────────────────────────────────────────────────────────

def test_log_hours_posts_expected_body(client, mock_api):
    route = mock_api.post("/time_entries/").respond(201, json={
        "id": 9, "client_id": 1, "date": "2026-07-14", "hours": 3.5,
        "rate": 95.0, "description": "API werk",
    })
    out = server.log_hours(client="Acme Corp", date="2026-07-14", hours=3.5,
                              description="API werk", rate=95)
    body = route.calls.last.request.read()
    import json
    payload = json.loads(body)
    assert payload == {"client_id": 1, "date": "2026-07-14", "hours": 3.5,
                       "rate": 95, "description": "API werk"}
    assert "Logged 3.5h for Acme Corp" in out


def test_log_hours_rejects_bad_date(client, mock_api):
    with pytest.raises(PeilError, match="ISO date"):
        server.log_hours(client="Acme Corp", date="14-07-2026", hours=1,
                            description="x")


def test_draft_invoice_returns_draft_summary(client, mock_api):
    mock_api.post("/invoices/from-hours").respond(201, json={
        "invoice": {
            "id": 42, "subtotal": 720.0, "vat_amount": 151.2, "total_amount": 871.2,
            "lines": [{"description": "Advies", "hours": 8, "rate": 90, "amount": 720.0}],
        },
        "entry_count": 2, "total_hours": 8.0,
    })
    out = server.draft_invoice(client="Acme Corp", period_start="2026-07-01",
                                  period_end="2026-07-14")
    assert "Draft invoice #42" in out
    assert "DRAFT" in out


def test_orientation_snapshot_formats(client, mock_api):
    mock_api.get("/orientation/snapshot").respond(json={
        "outstanding": {"count": 2, "total": 2420.0},
        "overdue": {"count": 1, "total": 1210.0},
        "drafts": {"count": 1, "total": 500.0},
        "invoiced_ytd": 24000.0,
        "uninvoiced": {"hours": 12.5, "value": 1125.0},
        "billable_hours_ytd": 800.0,
        "as_of": "2026-07-14",
    })
    out = server.orientation_snapshot()
    assert "Outstanding: 2 invoices" in out
    assert "€24,000.00" in out


def test_expected_tools_are_registered():
    import asyncio
    tools = asyncio.run(server.mcp.list_tools())
    names = {t.name for t in tools}
    assert names == {
        "list_clients", "log_hours", "list_unbilled",
        "draft_invoice", "send_invoice", "orientation_snapshot",
    }
