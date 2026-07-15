"""Peil MCP server — tools for logging hours, drafting invoices and orientation.

Draft-by-default: draft_invoice never sends anything to a client; send_invoice
is a separate, explicitly-confirmed tool that also requires the invoices:send
key permission. Dates are ISO YYYY-MM-DD.
"""

from datetime import date
from typing import Literal

from mcp.server.fastmcp import FastMCP

from peil_mcp.api import PeilClient, PeilError

INSTRUCTIONS = """\
Peil is a Dutch ZZP (freelancer) financial tool. These tools log hours, draft \
invoices from unbilled hours, and report where the user stands. House rules:

- DATES: all tools take ISO YYYY-MM-DD. The user speaks in relative terms \
("today", "yesterday", "this month"). Resolve them yourself against the \
current date, and always restate the exact date range you used ("I logged this \
to 2026-07-15" / "drafting from 2026-07-01 to today, 2026-07-15") so an \
ambiguous phrase can be corrected. "This month" = the 1st through today unless \
the user clearly means the full calendar month.
- CLIENT NAMES: match loosely. If a name is ambiguous or you're unsure which \
client is meant, call list_clients and ask — never guess. Tool errors already \
list the available clients; use them to recover.
- RATE €0: if log_hours reports an entry at €0.00/h, that client has no rate \
configured — say so plainly and offer to set a rate. Do NOT silently proceed to \
draft an invoice from €0 hours.
- SENDING / EMAIL: draft_invoice only ever creates a DRAFT. The tools that put \
mail in front of a client — send_invoice, schedule_send, send_reminder — are \
irreversible and require the invoices:send permission. NEVER call any of them \
unless the user has explicitly confirmed that specific action on that specific \
invoice. When you do, restate what will happen ("this emails invoice 2026-014 \
to De Correspondent now" / "scheduled for Monday 2026-07-20 09:00").
- EDITS / DELETES: editing or deleting hours, clients or invoices changes real \
records. For deletes and for editing anything already sent/paid, confirm first. \
After an edit, restate what changed (old → new). Deletes of sent/paid records \
are blocked server-side — surface that guardrail rather than working around it.
"""

mcp = FastMCP("peil", instructions=INSTRUCTIONS)

_client: PeilClient | None = None


def get_client() -> PeilClient:
    global _client
    if _client is None:
        _client = PeilClient()
    return _client


def _validate_date(value: str, label: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise PeilError(f"{label} must be an ISO date (YYYY-MM-DD), got '{value}'.")


def _eur(amount) -> str:
    return f"€{float(amount or 0):,.2f}"


@mcp.tool()
def list_clients() -> str:
    """List the user's clients (names to use with the other Peil tools)."""
    clients = get_client().list_clients()
    if not clients:
        return "No clients yet."
    lines = [
        f"- {c['name']}" + (f" ({c['email']})" if c.get("email") else "")
        for c in clients
        if c.get("active", True)
    ]
    return "Clients:\n" + "\n".join(lines)


@mcp.tool()
def log_hours(
    client: str,
    date: str,
    hours: float,
    description: str,
    project: str | None = None,
    rate: float | None = None,
) -> str:
    """Log worked hours for a client in Peil's timesheet.

    Omit `rate` to use the client's default rate. `date` is ISO YYYY-MM-DD.
    Requires the timesheet:write key permission.
    """
    api = get_client()
    day = _validate_date(date, "date")
    resolved = api.resolve_client(client)
    payload: dict = {
        "client_id": resolved["id"],
        "date": day,
        "hours": hours,
        "description": description,
    }
    if rate is not None:
        payload["rate"] = rate
    if project:
        payload["project_id"] = api.resolve_project(resolved["id"], project)["id"]

    entry = api.post("/time_entries/", json=payload).json()
    result = (
        f"Logged {entry['hours']}h for {resolved['name']} on {entry['date']} "
        f"at {_eur(entry['rate'])}/h: {entry.get('description') or '-'} "
        f"(entry #{entry['id']})"
    )
    if float(entry.get("rate") or 0) <= 0:
        result += (
            f"\n⚠ No rate is configured for {resolved['name']} — this was logged "
            "at €0/h and would invoice as €0. Set a default rate for the client "
            "in Peil, or pass an explicit rate."
        )
    return result


@mcp.tool()
def list_unbilled(
    client: str | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
) -> str:
    """List billable hours not yet on any invoice, grouped per client."""
    api = get_client()
    params: dict = {}
    if client:
        params["client_id"] = api.resolve_client(client)["id"]
    if period_start:
        params["period_start"] = _validate_date(period_start, "period_start")
    if period_end:
        params["period_end"] = _validate_date(period_end, "period_end")

    entries = api.get("/invoices/unbilled-entries", params=params).json()
    entries = [e for e in entries if e.get("invoice_id") is None]
    if not entries:
        return "No unbilled hours in this selection."

    clients = {c["id"]: c["name"] for c in api.list_clients()}
    by_client: dict = {}
    for e in entries:
        g = by_client.setdefault(e["client_id"], {"hours": 0.0, "amount": 0.0, "count": 0})
        g["hours"] += e["hours"]
        g["amount"] += e["amount"]
        g["count"] += 1

    lines = [
        f"- {clients.get(cid, f'client #{cid}')}: {g['count']} entries, "
        f"{g['hours']:.2f}h, {_eur(g['amount'])}"
        for cid, g in by_client.items()
    ]
    return "Unbilled hours:\n" + "\n".join(lines)


@mcp.tool()
def draft_invoice(
    client: str,
    period_start: str,
    period_end: str,
    grouping: Literal["summary", "by_project", "per_day"] = "summary",
) -> str:
    """Create a DRAFT invoice from a client's unbilled hours in a period.

    Nothing is sent to the client — the user reviews the draft in Peil (or asks
    explicitly to send it via send_invoice). Grouping: 'summary' (one line per
    description), 'by_project', or 'per_day'. Requires invoices:write.
    """
    api = get_client()
    resolved = api.resolve_client(client)
    body = {
        "client_id": resolved["id"],
        "period_start": _validate_date(period_start, "period_start"),
        "period_end": _validate_date(period_end, "period_end"),
        "grouping": grouping,
    }
    result = api.post("/invoices/from-hours", json=body).json()
    invoice = result["invoice"]
    lines = "\n".join(
        f"  - {l['description']}: {l['hours'] or '-'}h @ {_eur(l['rate']) if l['rate'] else '-'} = {_eur(l['amount'])}"
        for l in invoice.get("lines", [])
    )
    return (
        f"Draft invoice #{invoice['id']} created for {resolved['name']} "
        f"({result['entry_count']} entries, {result['total_hours']}h linked).\n"
        f"{lines}\n"
        f"Subtotal {_eur(invoice['subtotal'])} + VAT {_eur(invoice['vat_amount'])} "
        f"= {_eur(invoice['total_amount'])}.\n"
        "This is a DRAFT — review and send it in Peil."
    )


@mcp.tool()
def send_invoice(invoice: str) -> str:
    """Send an invoice to the client BY EMAIL. Irreversible and client-facing.

    `invoice` is a numeric id or invoice number. Only call this when the user has
    explicitly confirmed sending this specific invoice. Requires invoices:send.
    """
    api = get_client()
    inv = api.resolve_invoice(invoice)
    sent = api.post(f"/invoices/{inv['id']}/send-email").json()
    return (
        f"Invoice {sent.get('invoice_number') or f'#{inv['id']}'} sent "
        f"({_eur(sent['total_amount'])}, due {sent.get('due_date')})."
    )


@mcp.tool()
def orientation_snapshot() -> str:
    """Where does the user stand financially? Outstanding, overdue, drafts, YTD."""
    s = get_client().get("/orientation/snapshot").json()
    return (
        f"Peil orientation ({s['as_of']}):\n"
        f"- Outstanding: {s['outstanding']['count']} invoices, {_eur(s['outstanding']['total'])}\n"
        f"- Overdue: {s['overdue']['count']} invoices, {_eur(s['overdue']['total'])}\n"
        f"- Drafts: {s['drafts']['count']} invoices, {_eur(s['drafts']['total'])}\n"
        f"- Invoiced this year (ex VAT): {_eur(s['invoiced_ytd'])}\n"
        f"- Uninvoiced hours this year: {s['uninvoiced']['hours']}h ({_eur(s['uninvoiced']['value'])})\n"
        f"- Billable hours this year: {s['billable_hours_ytd']}h"
    )


# ── Hours: edit / delete ─────────────────────────────────────────────────────

@mcp.tool()
def edit_hours(
    entry_id: int,
    hours: float | None = None,
    description: str | None = None,
    rate: float | None = None,
    date: str | None = None,
    client: str | None = None,
    project: str | None = None,
) -> str:
    """Edit an existing time entry. Only the fields you pass are changed.

    Confirm with the user before editing an entry that's already on a sent/paid
    invoice (the server blocks it with INVOICE_LOCK). Requires timesheet:write.
    """
    api = get_client()
    current = api.get(f"/time_entries/{entry_id}").json()
    # date is a required field on the update schema — carry the current one over.
    payload: dict = {"date": current["date"]}
    if date is not None:
        payload["date"] = _validate_date(date, "date")
    if hours is not None:
        payload["hours"] = hours
    if description is not None:
        payload["description"] = description
    if rate is not None:
        payload["rate"] = rate
    if client is not None:
        resolved = api.resolve_client(client)
        payload["client_id"] = resolved["id"]
        if project is not None:
            payload["project_id"] = api.resolve_project(resolved["id"], project)["id"]
    elif project is not None:
        cid = current.get("client_id")
        if not cid:
            raise PeilError("Pass `client` too when setting a project on an internal entry.")
        payload["project_id"] = api.resolve_project(cid, project)["id"]

    updated = api.put(f"/time_entries/{entry_id}", json=payload).json()
    return (
        f"Updated entry #{entry_id}: "
        f"{current['hours']}h → {updated['hours']}h, "
        f"{_eur(current['rate'])}/h → {_eur(updated['rate'])}/h, "
        f"date {current['date']} → {updated['date']}. "
        f"Description: {updated.get('description') or '-'}"
    )


@mcp.tool()
def delete_hours(entry_id: int) -> str:
    """Delete a time entry. Destructive — confirm with the user first.

    Entries on a sent/paid/archived invoice are blocked server-side. Requires
    timesheet:write.
    """
    api = get_client()
    current = api.get(f"/time_entries/{entry_id}").json()
    api.delete(f"/time_entries/{entry_id}")
    return (
        f"Deleted entry #{entry_id} ({current['hours']}h on {current['date']}: "
        f"{current.get('description') or '-'})."
    )


# ── Clients: read / create / update / delete ─────────────────────────────────

@mcp.tool()
def get_client_details(client: str) -> str:
    """Show a client's details, including whether a default rate is configured."""
    c = get_client().resolve_client(client)
    rate = c.get("default_rate")
    return (
        f"{c['name']} (id {c['id']})\n"
        f"- Email: {c.get('email') or '—'}\n"
        f"- Default rate: {_eur(rate) + '/h' if rate else '⚠ none configured'}\n"
        f"- Payment terms: {c.get('payment_terms_days', '—')} days"
    )


@mcp.tool()
def create_client(
    name: str,
    email: str | None = None,
    default_rate: float | None = None,
    payment_terms_days: int | None = None,
) -> str:
    """Create a new client. Requires clients:write.

    Set a default_rate so hours logged for this client aren't billed at €0.
    """
    payload: dict = {"name": name}
    if email is not None:
        payload["email"] = email
    if default_rate is not None:
        payload["default_rate"] = default_rate
    if payment_terms_days is not None:
        payload["payment_terms_days"] = payment_terms_days
    c = get_client().post("/clients/", json=payload).json()
    rate = c.get("default_rate")
    return (
        f"Created client {c['name']} (id {c['id']}). "
        f"Default rate: {_eur(rate) + '/h' if rate else '⚠ none — hours will bill at €0'}."
    )


@mcp.tool()
def update_client(
    client: str,
    name: str | None = None,
    email: str | None = None,
    default_rate: float | None = None,
    payment_terms_days: int | None = None,
) -> str:
    """Update a client's details. Only the fields you pass change. Requires clients:write."""
    api = get_client()
    current = api.resolve_client(client)
    # name is required on the update schema — keep the current one unless changed.
    payload: dict = {"name": name if name is not None else current["name"]}
    if email is not None:
        payload["email"] = email
    if default_rate is not None:
        payload["default_rate"] = default_rate
    if payment_terms_days is not None:
        payload["payment_terms_days"] = payment_terms_days
    c = api.put(f"/clients/{current['id']}", json=payload).json()
    return f"Updated client {c['name']} (id {c['id']})."


@mcp.tool()
def delete_client(client: str) -> str:
    """Delete a client. Destructive — confirm first.

    Blocked (409) if the client has projects or sent/paid invoices. Requires
    clients:write.
    """
    api = get_client()
    current = api.resolve_client(client)
    api.delete(f"/clients/{current['id']}")
    return f"Deleted client {current['name']} (id {current['id']})."


# ── Invoices: list / status / update / delete / archive ──────────────────────

@mcp.tool()
def list_invoices(status: str | None = None, client: str | None = None) -> str:
    """List invoices, most recent first. Optionally filter by status and/or client."""
    api = get_client()
    invoices = api.list_invoices()
    if client:
        cid = api.resolve_client(client)["id"]
        invoices = [i for i in invoices if i.get("client_id") == cid]
    if status:
        invoices = [i for i in invoices if (i.get("status") or "").lower() == status.lower()]
    if not invoices:
        return "No invoices match this selection."
    names = {c["id"]: c["name"] for c in api.list_clients()}
    lines = [
        f"- #{i['id']} {i.get('invoice_number') or '(draft)'}: "
        f"{names.get(i.get('client_id'), '?')}, {_eur(i.get('total_amount'))}, "
        f"{i.get('status')}" + (f", due {i['due_date']}" if i.get('due_date') else "")
        for i in invoices[:50]
    ]
    return "Invoices:\n" + "\n".join(lines)


@mcp.tool()
def set_invoice_status(
    invoice: str,
    status: Literal["draft", "sent", "paid", "overdue", "archived"],
) -> str:
    """Change an invoice's status (e.g. mark paid). Requires invoices:write.

    `invoice` is a numeric id or invoice number. This does NOT email anyone —
    it only records the status. Use send_invoice to actually email the client.
    """
    api = get_client()
    inv = api.resolve_invoice(invoice)
    updated = api.put(f"/invoices/{inv['id']}", json={"status": status}).json()
    return (
        f"Invoice {updated.get('invoice_number') or f'#{inv['id']}'} status: "
        f"{inv.get('status')} → {updated.get('status')}."
    )


@mcp.tool()
def update_invoice(
    invoice: str,
    due_date: str | None = None,
    payment_date: str | None = None,
    notes: str | None = None,
) -> str:
    """Update safe invoice fields (due date, payment date, notes). Requires invoices:write.

    Line items and amounts are not edited here — redraft from hours for those.
    """
    api = get_client()
    inv = api.resolve_invoice(invoice)
    payload: dict = {}
    if due_date is not None:
        payload["due_date"] = _validate_date(due_date, "due_date")
    if payment_date is not None:
        payload["payment_date"] = _validate_date(payment_date, "payment_date")
    if notes is not None:
        payload["notes"] = notes
    if not payload:
        raise PeilError("Nothing to update — pass at least one of due_date, payment_date, notes.")
    updated = api.put(f"/invoices/{inv['id']}", json=payload).json()
    return f"Updated invoice {updated.get('invoice_number') or f'#{inv['id']}'} ({', '.join(payload)})."


@mcp.tool()
def delete_invoice(invoice: str) -> str:
    """Delete an invoice. Destructive — confirm first.

    Paid invoices can't be deleted (archive instead); sent invoices are blocked
    unless the user is sure. Requires invoices:write.
    """
    api = get_client()
    inv = api.resolve_invoice(invoice)
    api.delete(f"/invoices/{inv['id']}")
    return f"Deleted invoice {inv.get('invoice_number') or f'#{inv['id']}'}."


@mcp.tool()
def archive_invoice(invoice: str) -> str:
    """Archive an invoice (hidden from default views, kept for records). Requires invoices:write."""
    api = get_client()
    inv = api.resolve_invoice(invoice)
    api.post(f"/invoices/{inv['id']}/archive")
    return f"Archived invoice {inv.get('invoice_number') or f'#{inv['id']}'}."


# ── Email orchestration (all require invoices:send) ──────────────────────────

@mcp.tool()
def schedule_send(invoice: str, scheduled_at: str) -> str:
    """Schedule a DRAFT invoice to be emailed at a future time. Client-facing.

    `scheduled_at` is an ISO datetime (e.g. 2026-07-20T09:00:00). Only call this
    when the user has explicitly confirmed sending this invoice at this time.
    Requires invoices:send.
    """
    api = get_client()
    inv = api.resolve_invoice(invoice)
    result = api.post(f"/invoices/{inv['id']}/schedule-send", json={"scheduled_at": scheduled_at}).json()
    return (
        f"Invoice {inv.get('invoice_number') or f'#{inv['id']}'} will be emailed to the client "
        f"at {result.get('scheduled_send_at')}."
    )


@mcp.tool()
def cancel_scheduled_send(invoice: str) -> str:
    """Cancel a previously scheduled send. Requires invoices:send."""
    api = get_client()
    inv = api.resolve_invoice(invoice)
    api.delete(f"/invoices/{inv['id']}/schedule-send")
    return f"Cancelled the scheduled send for invoice {inv.get('invoice_number') or f'#{inv['id']}'}."


@mcp.tool()
def send_reminder(invoice: str) -> str:
    """Email a payment reminder for a sent/overdue invoice. Irreversible, client-facing.

    Only call this when the user has explicitly confirmed reminding about this
    specific invoice. Requires invoices:send.
    """
    api = get_client()
    inv = api.resolve_invoice(invoice)
    updated = api.post(f"/invoices/{inv['id']}/send-reminder").json()
    return (
        f"Reminder emailed for invoice {updated.get('invoice_number') or f'#{inv['id']}'} "
        f"({_eur(updated.get('total_amount'))})."
    )


# ── Reminder copy (read / write) ─────────────────────────────────────────────

@mcp.tool()
def get_reminder_copy() -> str:
    """Show the user's custom reminder email copy and schedule."""
    s = get_client().get("/invoices/reminder-settings").json()
    ct = s.get("custom_templates") or {}
    out = [
        f"Auto-reminders: {'on' if s.get('auto_enabled') else 'off'}",
        f"Schedule (days relative to due date): {s.get('schedule')}",
    ]
    if not ct:
        out.append("Custom copy: none (Peil's defaults are used).")
    for lang in sorted(ct):
        for tone in sorted(ct[lang]):
            t = ct[lang][tone]
            if t.get("subject") or t.get("body"):
                out.append(f"[{lang}/{tone}] subject: {t.get('subject') or '—'}")
    return "\n".join(out)


@mcp.tool()
def set_reminder_copy(
    tone: Literal["pre_due", "overdue", "formal"],
    subject: str,
    body: str,
    lang: Literal["nl", "en"] = "nl",
) -> str:
    """Set the reminder email copy for one tone/language. Requires invoices:write.

    Tones: pre_due (before due date), overdue (0–7 days late), formal (>7 days).
    Other tones/languages are preserved. Use {invoice_number}, {total_amount},
    {due_date} placeholders as in Peil's editor.
    """
    api = get_client()
    current = api.get("/invoices/reminder-settings").json()
    ct = dict(current.get("custom_templates") or {})
    lang_map = dict(ct.get(lang) or {})
    lang_map[tone] = {"subject": subject, "body": body}
    ct[lang] = lang_map
    api.put("/invoices/reminder-settings", json={"custom_templates": ct})
    return f"Saved {lang}/{tone} reminder copy. Subject: {subject}"


def main() -> None:
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
