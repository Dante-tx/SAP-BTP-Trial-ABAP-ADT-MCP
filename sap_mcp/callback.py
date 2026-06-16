from __future__ import annotations

from html import escape

from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from sap_mcp.auth.browser_sso import BrowserSsoSessionManager
from sap_mcp.config import AppConfig
from sap_mcp.errors import SapMcpError


async def healthz(_request):
    return JSONResponse({"status": "ok"})


def create_callback_app(config: AppConfig, *, client_name: str) -> Starlette:
    async def adt_redirect(request):
        params = {key: value for key, value in request.query_params.multi_items()}
        session_manager = BrowserSsoSessionManager(config.abap_dev)
        session_manager.save_reentrance_callback(params)
        fields = ", ".join(sorted(params)) or "none"
        validation_message = "ADT session validation was not attempted."
        validation_title = "ABAP Development Tools login captured"
        try:
            discovery = await session_manager.validate_session()
            validation_title = "ABAP Development Tools session is ready"
            validation_message = (
                f"Validated ADT discovery with status {discovery.get('status_code')}. "
                f"You can close this page and continue in {client_name}."
            )
        except SapMcpError as exc:
            validation_title = "ABAP Development Tools login needs attention"
            validation_message = (
                "The browser callback was captured, but ADT discovery did not accept the ticket. "
                f"Details: {exc}"
            )
        safe_title = escape(validation_title)
        safe_message = escape(validation_message)
        safe_fields = escape(fields)
        return HTMLResponse(
            "<!doctype html><html><head><title>ABAP Development Tools</title></head>"
            '<body style="font-family: Arial, sans-serif; margin: 0;">'
            '<div style="background:#31495f;color:white;padding:12px 24px;font-weight:700;">ABAP Development Tools</div>'
            '<main style="margin:96px auto;max-width:660px;border:1px solid #ddd;padding:32px;box-shadow:0 1px 6px #ccc;">'
            f"<h1>{safe_title}</h1>"
            f"<p>{safe_message}</p>"
            f"<p>Captured fields: {safe_fields}</p>"
            "</main></body></html>"
        )

    return Starlette(
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
            Route("/adt/redirect", adt_redirect, methods=["GET"]),
            Route("/logon/success", adt_redirect, methods=["GET"]),
        ]
    )
