# SAP BTP ABAP ADT MCP Server

Python + FastMCP + ASGI MCP server for SAP ABAP Development Tools access.

This server is focused on practical ADT development workflows:

- Browser SSO assisted ADT login
- Repository search
- Source and metadata read
- Controlled create, update, activate, delete
- OData V4 service binding publish

## Runtime

- Python 3.11+
- Access to an SAP ABAP system with ADT enabled
- Browser SSO access to the target system
- Change authorization for the object types you intend to modify

Install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -e ".[test]"
```

## HTTP Endpoints

- `/mcp`
- `/healthz`
- `/logon/success`

## Supported MCP Tools

- `abap_adt_login`
- `abap_save_sso_session`
- `abap_save_sso_cookie_header`
- `abap_adt_connect`
- `abap_search_objects`
- `abap_read_source`
- `abap_create_object`
- `abap_update_source`
- `abap_activate_object`
- `abap_delete_object`
- `abap_publish_service_binding`

## Supported Object Coverage

The following object types are supported for read, create, update, and delete:

- `CLAS`, `INTF`
- `DDLS`, `DCLS`, `BDEF`, `DDLX`, `SRVD`, `SRVB`
- `TABL`, `DTEL`, `DOMA`, `DEVC`
- `PROG`, `FUGR`, `FUNC`

Notes:

- Class and interface reads aggregate local includes such as `definitions` and `implementations`.
- Standard SAP packages can be read when `readable_packages` allows them, but standard SAP objects must remain read-only in normal use.
- Create, update, activate, publish, and delete operations are restricted by `allowed_packages`.
- Backend authorizations still apply. If the SAP system blocks an object type, MCP will surface the ADT error.

## Configuration

Copy the example config:

```powershell
copy sap-mcp.example.yaml sap-mcp.yaml
```

Example:

```yaml
server:
  name: "SAP BTP ABAP ADT MCP Server"
  auth_tokens:
    - "dev-token"

abap_dev:
  system_url: "https://your-abap-instance.abap.region.hana.ondemand.com"
  callback_url: "http://localhost:8000/logon/success"
  reentrance_endpoint: "/sap/bc/sec/reentrance"
  reentrance_scenario: "FTO1"
  service_key_path: "service-key.json"
  session_path: ".sap-mcp-session.json"
  readable_packages:
    - "*"
  allowed_packages:
    - "Z*"
  allow_write: false
  allow_activate: false
  default_timeout_seconds: 30
```

Security notes:

- `service-key.json` is only used to discover the ABAP system URL if `system_url` is not set.
- Do not distribute `.sap-mcp-session.json`, `service-key.json`, `.env`, or your real `sap-mcp.yaml`.
- Prefer `readable_packages: ["*"]` with a narrow `allowed_packages` list for production use.

## Service Key Source

When `abap_dev.system_url` is not set, the server can read the ABAP system URL from `service-key.json`.

Typical source in SAP BTP cockpit:

1. Open `Instances and Subscriptions`.
2. Locate your ABAP environment instance.
3. Click the credential entry shown as `1 key value`.
4. In the popup, click `Download` and save the downloaded service key JSON locally as `service-key.json`.

Use the entry below as the navigation reference for where to start the download:

![Service key entry](assets/service-key-entry.png)

## Start

```powershell
$env:SAP_MCP_AUTH_TOKENS="dev-token"
uvicorn app.server:app --host 127.0.0.1 --port 8000
```

## ADT Login Flow

1. Call `abap_adt_login`.
2. Complete SAP SSO in the browser.
3. The callback at `/logon/success` stores the ADT reentrance session locally.
4. Call `abap_adt_connect`.
5. Use read tools first, then enable write and activate only when needed.

## Tests

```powershell
python -m pytest -q
```
