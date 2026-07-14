"""Peil MCP server — tools for logging hours, drafting invoices and orientation.

Draft-by-default: draft_invoice never sends anything to a client; send_invoice
is a separate, explicitly-confirmed tool that also requires the invoices:send
key permission. Dates are ISO YYYY-MM-DD.
"""

from datetime import date

from mcp.server.fastmcp import FastMCP

from peil_mcp.api import PeilClient, PeilError

mcp = FastMCP("peil")

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
    return (
        f"Logged {entry['hours']}h for {resolved['name']} on {entry['date']} "
        f"at {_eur(entry['rate'])}/h: {entry.get('description') or '-'} "
        f"(entry #{entry['id']})"
    )


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
    grouping: str = "summary",
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
def send_invoice(invoice_id: int) -> str:
    """Send an invoice to the client BY EMAIL. Irreversible and client-facing.

    Only call this when the user has explicitly confirmed sending this specific
    invoice. Requires the invoices:send key permission.
    """
    invoice = get_client().post(f"/invoices/{invoice_id}/send-email").json()
    return (
        f"Invoice {invoice.get('invoice_number') or f'#{invoice_id}'} sent "
        f"({_eur(invoice['total_amount'])}, due {invoice.get('due_date')})."
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


def main() -> None:
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
