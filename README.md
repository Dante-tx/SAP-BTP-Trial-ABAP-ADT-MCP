# SAP BTP ABAP ADT MCP Server

MCP server for operating SAP ABAP Development Tools through ADT HTTP APIs.

## Features

- Browser SSO assisted ADT login.
- ABAP repository search.
- Source and metadata read.
- Controlled create, update, activate, publish, and delete.
- ABAP Unit and ATC runs through official REST services.
- HTTP and STDIO transports.

## Requirements

- Python 3.11+
- SAP ABAP system with ADT enabled
- Browser SSO access to the target system
- Optional communication user for ABAP Unit (`SAP_COM_0735`) and ATC (`SAP_COM_0901`)

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -e .
copy sap-mcp.example.yaml sap-mcp.yaml
```

Edit `sap-mcp.yaml` and set:

- `abap_dev.system_url`
- `allowed_packages`
- `allow_write` / `allow_activate`
- `communication_user` / `communication_password`, if ABAP Unit or ATC is needed

Do not commit or share `sap-mcp.yaml`, `.env`, or `.sap-mcp-session.json`.

## Start

HTTP:

```powershell
$env:SAP_MCP_AUTH_TOKENS="dev-token"
uvicorn sap_mcp.server:app --host 127.0.0.1 --port 8000
```

STDIO:

```powershell
python -m sap_mcp.stdio_server
```

HTTP endpoints:

- `/mcp`
- `/healthz`
- `/logon/success`

## MCP Tools

- Login and connection: `abap_adt_login`, `abap_adt_connect`, `abap_save_sso_session`, `abap_save_sso_cookie_header`
- Read: `abap_search_objects`, `abap_read_source`, `abap_get_object_metadata`
- Write: `abap_create_object`, `abap_update_source`, `abap_activate_object`, `abap_activate_objects`, `abap_delete_object`, `abap_publish_service_binding`
- Quality: `abap_run_unit_tests`, `abap_get_unit_test_run`, `abap_get_unit_test_result`, `abap_run_atc_checks`, `abap_get_atc_run`, `abap_get_atc_result`

## Supported Objects

- `CLAS`, `INTF`
- `DDLS`, `DCLS`, `BDEF`, `DDLX`, `SRVD`, `SRVB`
- `TABL`, `DTEL`, `DOMA`, `DEVC`
- `PROG`, `FUGR`, `FUNC`

Write, activate, publish, and delete operations are restricted by `allowed_packages`. Backend SAP authorizations still apply.

## Login Flow

1. Call `abap_adt_login`.
2. Complete SAP SSO in the browser.
3. The callback stores the local ADT session.
4. Call `abap_adt_connect`.
5. Use read tools first; enable write and activation only when needed.
