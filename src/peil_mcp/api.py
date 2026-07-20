"""HTTP client for the Peil public API.

The MCP server is a pure client of the scoped-key surface: it never touches
the database, and every error is translated into a message an agent (or the
person reading its output) can act on. See docs/archive/plan-mcp-api-surface.md in
the main repo.
"""

import os

import httpx

DEFAULT_API_URL = "https://api.peil.app/api/v1"


class PeilError(Exception):
    """A readable, agent-facing error."""


def _detail(response: httpx.Response) -> dict:
    try:
        body = response.json()
    except Exception:
        return {}
    detail = body.get("detail")
    return detail if isinstance(detail, dict) else {"message": detail}


class PeilClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or os.environ.get("PEIL_API_KEY")
        if not self.api_key:
            raise PeilError(
                "PEIL_API_KEY is not set. Create an API key in Peil under "
                "Settings > Developer and set it in the MCP server's environment."
            )
        self.base_url = (base_url or os.environ.get("PEIL_API_URL") or DEFAULT_API_URL).rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=30.0,
        )

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise PeilError(f"Could not reach the Peil API at {self.base_url}: {exc}")

        if response.is_success:
            return response

        detail = _detail(response)
        code = detail.get("code")
        if response.status_code == 401:
            raise PeilError(
                "Invalid or expired Peil API key. Create a new one in Peil under "
                "Settings > Developer."
            )
        if code == "INSUFFICIENT_SCOPE":
            missing = ", ".join(detail.get("missing", []))
            raise PeilError(
                f"Your API key is missing the '{missing}' permission. "
                "Enable it on the key in Peil under Settings > Developer "
                "(or create a new key with that permission)."
            )
        if code == "PLAN_UPGRADE_REQUIRED":
            raise PeilError("API access requires Peil Pro. Upgrade at app.peil.app/upgrade.")
        if code:
            message = detail.get("message") or code
            raise PeilError(f"Peil API error ({code}): {message}")
        raise PeilError(
            f"Peil API error {response.status_code}: {detail.get('message') or response.text[:300]}"
        )

    def get(self, path: str, **kwargs) -> httpx.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> httpx.Response:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs) -> httpx.Response:
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs) -> httpx.Response:
        return self.request("DELETE", path, **kwargs)

    # ── Domain helpers ────────────────────────────────────────────────────────

    def list_clients(self) -> list[dict]:
        return self.get("/clients/").json()

    def list_invoices(self) -> list[dict]:
        return self.get("/invoices/").json()

    def resolve_invoice(self, ref) -> dict:
        """Resolve an invoice by numeric id or by invoice number (case-insensitive)."""
        invoices = self.list_invoices()

        try:
            as_id = int(str(ref).strip())
        except (TypeError, ValueError):
            as_id = None
        if as_id is not None:
            for inv in invoices:
                if inv.get("id") == as_id:
                    return inv

        needle = str(ref).strip().lower()
        by_number = [i for i in invoices if (i.get("invoice_number") or "").strip().lower() == needle]
        if len(by_number) == 1:
            return by_number[0]
        if len(by_number) > 1:
            raise PeilError(f"Multiple invoices match '{ref}'. Use the numeric invoice id instead.")

        raise PeilError(
            f"No invoice found matching '{ref}'. Use the numeric id (from list_invoices) "
            "or the exact invoice number."
        )

    def resolve_client(self, name: str) -> dict:
        """Resolve a client by name: exact (case-insensitive), then unique substring."""
        clients = self.list_clients()
        needle = name.strip().lower()

        exact = [c for c in clients if (c.get("name") or "").strip().lower() == needle]
        if len(exact) == 1:
            return exact[0]

        partial = [c for c in clients if needle in (c.get("name") or "").lower()]
        if len(partial) == 1:
            return partial[0]

        names = sorted((c.get("name") or "?") for c in clients)
        if not partial:
            raise PeilError(
                f"No client found matching '{name}'. Available clients: {', '.join(names) or 'none'}."
            )
        candidates = ", ".join(sorted(c["name"] for c in partial))
        raise PeilError(
            f"Multiple clients match '{name}': {candidates}. Use a more specific name."
        )

    def resolve_project(self, client_id: int, name: str) -> dict:
        """Resolve a project by name within a client's projects."""
        projects = [p for p in self.get("/projects/").json() if p.get("client_id") == client_id]
        needle = name.strip().lower()
        matches = [p for p in projects if needle in (p.get("name") or "").lower()]
        if len(matches) == 1:
            return matches[0]
        names = sorted((p.get("name") or "?") for p in projects)
        if not matches:
            raise PeilError(
                f"No project found matching '{name}' for this client. "
                f"Projects: {', '.join(names) or 'none'}."
            )
        candidates = ", ".join(sorted(p["name"] for p in matches))
        raise PeilError(f"Multiple projects match '{name}': {candidates}. Be more specific.")
