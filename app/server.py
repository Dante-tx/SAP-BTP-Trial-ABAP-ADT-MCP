from __future__ import annotations

import uvicorn
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Mount, Route

from app.auth.browser_sso import BrowserSsoSessionManager
from app.config import get_config
from app.mcp_server import create_mcp
from app.security import BearerAuthMiddleware, token_values


config = get_config()
mcp = create_mcp(config)
mcp_app = mcp.streamable_http_app()


async def healthz(_request):
    return JSONResponse({"status": "ok", "service": config.server.name})


async def adt_redirect(request):
    params = {key: value for key, value in request.query_params.multi_items()}
    BrowserSsoSessionManager(config.abap_dev).save_reentrance_callback(params)
    fields = ", ".join(sorted(params)) or "none"
    return HTMLResponse(
        "<!doctype html><html><head><title>ABAP Development Tools</title></head>"
        "<body style=\"font-family: Arial, sans-serif; margin: 0;\">"
        "<div style=\"background:#31495f;color:white;padding:12px 24px;font-weight:700;\">ABAP Development Tools</div>"
        "<main style=\"margin:96px auto;max-width:660px;border:1px solid #ddd;padding:32px;box-shadow:0 1px 6px #ccc;\">"
        "<h1>You have been successfully logged on</h1>"
        "<p>You can close this page and continue in Codex.</p>"
        f"<p>Captured fields: {fields}</p>"
        "</main></body></html>"
    )


app = Starlette(
    routes=[
        Route("/healthz", healthz, methods=["GET"]),
        Route("/adt/redirect", adt_redirect, methods=["GET"]),
        Route("/logon/success", adt_redirect, methods=["GET"]),
        Mount("/", app=mcp_app),
    ],
    lifespan=mcp_app.router.lifespan_context,
)
app.add_middleware(BearerAuthMiddleware, allowed_tokens=token_values(config))


def main() -> None:
    uvicorn.run("app.server:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
