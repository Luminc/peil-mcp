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
        # reads + original surface
        "list_clients", "log_hours", "list_unbilled",
        "draft_invoice", "send_invoice", "orientation_snapshot",
        # hours edit/delete
        "edit_hours", "delete_hours",
        # client CRUD
        "get_client_details", "create_client", "update_client", "delete_client",
        # invoice ops
        "list_invoices", "set_invoice_status", "update_invoice",
        "delete_invoice", "archive_invoice",
        # email orchestration
        "schedule_send", "cancel_scheduled_send", "send_reminder",
        # reminder copy
        "get_reminder_copy", "set_reminder_copy",
    }


# ─── Expanded CRUD tools ──────────────────────────────────────────────────────

def test_edit_hours_merges_current_date(client, mock_api):
    """edit_hours fetches the entry and carries date over (it's a required field)."""
    mock_api.get("/time_entries/9").respond(json={
        "id": 9, "client_id": 1, "date": "2026-07-10", "hours": 4.0,
        "rate": 90.0, "description": "Oud",
    })
    route = mock_api.put("/time_entries/9").respond(json={
        "id": 9, "client_id": 1, "date": "2026-07-10", "hours": 6.0,
        "rate": 90.0, "description": "Oud",
    })
    out = server.edit_hours(entry_id=9, hours=6.0)
    import json
    payload = json.loads(route.calls.last.request.read())
    assert payload["date"] == "2026-07-10"  # carried over
    assert payload["hours"] == 6.0
    assert "4.0h → 6.0h" in out


def test_delete_hours_confirms(client, mock_api):
    mock_api.get("/time_entries/9").respond(json={
        "id": 9, "client_id": 1, "date": "2026-07-10", "hours": 4.0,
        "rate": 90.0, "description": "Oud",
    })
    mock_api.delete("/time_entries/9").respond(204)
    out = server.delete_hours(entry_id=9)
    assert "Deleted entry #9" in out


def test_create_client_posts_body(client, mock_api):
    route = mock_api.post("/clients/").respond(201, json={
        "id": 5, "name": "Nieuw NV", "default_rate": 95.0,
    })
    out = server.create_client(name="Nieuw NV", default_rate=95)
    import json
    payload = json.loads(route.calls.last.request.read())
    assert payload == {"name": "Nieuw NV", "default_rate": 95}
    assert "Created client Nieuw NV" in out


def test_set_invoice_status_resolves_and_puts(client, mock_api):
    mock_api.get("/invoices/").respond(json=[
        {"id": 42, "invoice_number": "2026-014", "client_id": 1,
         "status": "sent", "total_amount": 871.2},
    ])
    route = mock_api.put("/invoices/42").respond(json={
        "id": 42, "invoice_number": "2026-014", "status": "paid",
    })
    out = server.set_invoice_status(invoice="2026-014", status="paid")
    assert route.called
    assert "sent → paid" in out


def test_send_reminder_requires_confirmation_and_calls_endpoint(client, mock_api):
    mock_api.get("/invoices/").respond(json=[
        {"id": 42, "invoice_number": "2026-014", "client_id": 1,
         "status": "overdue", "total_amount": 871.2},
    ])
    mock_api.post("/invoices/42/send-reminder").respond(json={
        "id": 42, "invoice_number": "2026-014", "total_amount": 871.2,
    })
    out = server.send_reminder(invoice="42")
    assert "Reminder emailed" in out


def test_set_reminder_copy_merges_templates(client, mock_api):
    """set_reminder_copy preserves other tones/langs while updating one."""
    mock_api.get("/invoices/reminder-settings").respond(json={
        "auto_enabled": True, "schedule": [-3, 0, 7],
        "custom_templates": {"nl": {"pre_due": {"subject": "Oud", "body": "x"}}},
    })
    route = mock_api.put("/invoices/reminder-settings").respond(json={})
    server.set_reminder_copy(tone="overdue", subject="Herinnering", body="Betaal aub", lang="nl")
    import json
    payload = json.loads(route.calls.last.request.read())
    ct = payload["custom_templates"]
    assert ct["nl"]["pre_due"]["subject"] == "Oud"          # preserved
    assert ct["nl"]["overdue"]["subject"] == "Herinnering"  # added
