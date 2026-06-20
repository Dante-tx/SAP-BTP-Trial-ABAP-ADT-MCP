# SAP ABAP ADT MCP Server

MCP (Model Context Protocol) server for AI agents to interact with SAP ABAP systems via ADT HTTP APIs. Provides 27 tools covering the full ABAP development lifecycle.

## Requirements

- Python 3.11+
- SAP ABAP system with ADT enabled
- Browser SSO access to the target system, or ADT-enabled Basic Auth credentials
- Optional: communication arrangements for ABAP Unit (`SAP_COM_0735`) and ATC (`SAP_COM_0901`)

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -e .
copy sap-mcp.example.yaml sap-mcp.yaml
```

Edit `sap-mcp.yaml` and set:

- `abap_dev.system_url`
- `abap_dev.client`, if the SAP system requires an explicit client such as `100`
- `abap_dev.auth_mode`: `sso`, `basic`, or `auto` (default)
- `abap_dev.username` / `abap_dev.password`, if `auth_mode` is `basic` or `auto`
- `allowed_packages`
- `allow_write` / `allow_activate`

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

## MCP Tools (27)

### Session & System

| Tool | Description | Actions |
|------|-------------|---------|
| `abap_list_destinations` | List available ABAP system destinations | _(no args)_ |
| `abap_adt_session` | Manage ADT authentication | `login`, `validate`, `save_cookies`, `save_cookie_header`, `clear` |
| `abap_system_info` | Read ABAP system information | `system`, `components`, `users` |

### Object Discovery

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `abap_find_objects` | Find ABAP repository objects by name, query, or package | `query`, `exact_name`, `name`, `object_type`, `package`, `search_mode`, `sort_by` |
| `abap_where_used` | Find where an ABAP object is referenced (Where-Used list) | `object_type`, `name`, `enable_all_types` |
| `abap_get_object_metadata` | Read object metadata, package, links, source structure | `object_type`, `name`, `uri`, `destination` |

### Source Code

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `abap_read_source` | Read ABAP source code | `object_type`, `name`, `scope` (main/include/active/inactive/both), `include_type`, `uri` |
| `abap_describe_signature` | Describe ABAP object method signatures | `object_type`, `name`, `method_name` |
| `abap_update_source` | Update ABAP source code | `object_type`, `name`, `source`, `include_type`, `etag`, `reason`, `transport_request_number` |
| `abap_syntax_check` | Run syntax check on source (no activation) | `object_type`, `name`, `source` |
| `abap_code_assist` | Code assistance — element info or format | `action` (element_info/format), `object_type`, `object_name`, `source`, `position` |

### Lifecycle Management

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `abap_create_object` | Create an ABAP repository object | `object_type`, `name`, `package`, `description`, `source`, `object_content`, `transport_request_number`, `implementation_type`, `service_binding_version` |
| `abap_creation_info` | Inspect/validate creation metadata | `action` (list_types/type_details/validate), `destination`, `object_type` |
| `abap_activate` | Activate one or more ABAP objects | `object_type`, `name`, `objects[]`, `reason` |
| `abap_delete_object` | Delete an ABAP repository object | `object_type`, `name`, `reason`, `etag`, `transport_request_number` |
| `abap_lock` | Lock an ABAP object for editing | `object_url`, `is_creation` |
| `abap_unlock` | Release an ABAP object lock | `lock_handle`, `object_url` |

### Transport

| Tool | Description | Actions |
|------|-------------|---------|
| `abap_transport` | Manage transport requests for object workflows | `get`, `create`, `list_tasks`, `objects`, `release` |

### Service Binding

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `abap_business_services` | Read service binding OData data | `action` (list_services/service_info), `service_binding_name`, `destination` |
| `abap_publish_service_binding` | Publish an OData V2 or V4 service binding | `name`, `odata_version`, `reason` |
| `abap_unpublish_service_binding` | Unpublish an OData V2 or V4 service binding | `name`, `odata_version`, `reason` |

### RAP Generators

| Tool | Description | Actions |
|------|-------------|---------|
| `abap_generators` | Work with RAP generators | `list`, `schema`, `generate` |

### CDS Analysis

| Tool | Description | Actions |
|------|-------------|---------|
| `abap_cds_analysis` | Analyze CDS views | `dependencies`, `related_objects`, `active_object`, `create_sql`, `object_relations` |

### Data Preview

| Tool | Description | Actions |
|------|-------------|---------|
| `abap_data_preview` | Preview data from CDS views, DDIC tables, or free-style SQL | `cds`, `ddic`, `freestyle` |

### Execution

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `abap_execute` | Execute ABAP programs or classes | `action` (program/class), `object_name`, `parameters` |
| `abap_call_function` | Call an ABAP function module or BAPI | `function_name`, `importing`, `changing`, `tables`, `commit`, `destination` |

### Quality

| Tool | Description | Key Parameters |
|------|-------------|---------|
| `abap_quality` | Run ABAP quality checks (unit tests / ATC) | `kind` (unit/atc), `action` (start/status/result) |

## Supported Object Types

| Code | Description |
|------|-------------|
| `CLAS` | Class |
| `INTF` | Interface |
| `DDLS` | CDS View / Entity |
| `DCLS` / `DCLX` | Access Control (DCL) |
| `BDEF` | Behavior Definition |
| `DDLX` | CDS Extension |
| `SRVD` | Service Definition |
| `SRVB` | Service Binding |
| `TABL` | Table / Structure |
| `DTEL` | Data Element |
| `DOMA` | Domain |
| `DEVC` | Package |
| `PROG` | Program |
| `FUGR` | Function Group |
| `FUNC` | Function Module |

Object type inputs accept either short canonical type (`TABL`, `DDLS`, `SRVB`) or an ADT type id from search/creation results (`TABL/DT`, `DDLS/DF`, `SRVB/SVB`). Prefer short `object_type` values for cross-tool calls.

## Typical Workflow

```
find/read → syntax_check → update_source → activate
```

1. **Find objects** with `abap_find_objects`
2. **Read source** with `abap_read_source`
3. **Check syntax** with `abap_syntax_check`
4. **Update source** with `abap_update_source`
5. **Activate** with `abap_activate`

For transport-managed systems, use `abap_transport(action="get")` first. Write, activate, publish, and delete operations are restricted by `allowed_packages`.

## Login Flow

### SSO Mode

1. Set `abap_dev.auth_mode: "sso"`
2. Call `abap_adt_session(action="login")`
3. Complete SAP SSO in the browser
4. The callback stores the local ADT session
5. Call `abap_adt_session(action="validate")`

### Basic Auth Mode

1. Set `abap_dev.auth_mode: "basic"`
2. Set `abap_dev.username` and `abap_dev.password`
3. Call `abap_adt_session(action="validate")`

Use read tools first; enable write and activation only when needed.

## Project Structure

```
SAP-ABAP-ADT-MCP/
├── sap_mcp/                  # Python package
│   ├── auth/                 # Authentication (SSO)
│   ├── connectors/           # ADT API connectors
│   │   ├── analysis/         # CDS analysis, code assist
│   │   ├── core/             # HTTP, auth, paths, XML utils
│   │   ├── integration/      # Business services, destinations, generators
│   │   ├── lifecycle/        # Activation, lock, quality, syntax check, transport
│   │   ├── objects/          # CRUD, search, execution, function modules
│   │   └── system/           # System info
│   ├── services/             # ABAP Dev Gateway
│   ├── tools/                # MCP tool workflows
│   ├── mcp_server.py         # MCP tool definitions (27 tools total)
│   └── server.py             # HTTP/STDIO server entry points
├── sap-mcp.example.yaml      # Example configuration
├── pyproject.toml            # Python project metadata
├── .gitignore
└── README.md
```
