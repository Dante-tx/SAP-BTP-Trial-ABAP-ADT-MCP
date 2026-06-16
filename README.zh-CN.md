# SAP BTP ABAP ADT MCP Server

这是一个通过 ADT HTTP API 操作 SAP ABAP Development Tools 的 MCP 服务端。

## 功能

- 浏览器 SSO 登录 ADT。
- ABAP Repository 搜索。
- 源码和元数据读取。
- 受控创建、更新、激活、发布和删除。
- 通过官方 REST 服务运行 ABAP Unit 和 ATC。
- 支持 HTTP 和 STDIO 两种 Transport。

## 运行要求

- Python 3.11+
- 已启用 ADT 的 SAP ABAP 系统
- 可以通过浏览器完成目标系统 SSO
- 可选：用于 ABAP Unit（`SAP_COM_0735`）和 ATC（`SAP_COM_0901`）的 Communication User

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -e .
copy sap-mcp.example.yaml sap-mcp.yaml
```

编辑 `sap-mcp.yaml`，至少配置：

- `abap_dev.system_url`
- `allowed_packages`
- `allow_write` / `allow_activate`
- 如需 ABAP Unit 或 ATC，配置 `communication_user` / `communication_password`

不要提交或分享 `sap-mcp.yaml`、`.env`、`.sap-mcp-session.json`。

## 启动

HTTP：

```powershell
$env:SAP_MCP_AUTH_TOKENS="dev-token"
uvicorn sap_mcp.server:app --host 127.0.0.1 --port 8000
```

STDIO：

```powershell
python -m sap_mcp.stdio_server
```

HTTP 端点：

- `/mcp`
- `/healthz`
- `/logon/success`

## MCP 工具

- 登录与连接：`abap_adt_login`、`abap_adt_connect`、`abap_save_sso_session`、`abap_save_sso_cookie_header`
- 读取：`abap_search_objects`、`abap_read_source`、`abap_get_object_metadata`
- 写入：`abap_create_object`、`abap_update_source`、`abap_activate_object`、`abap_activate_objects`、`abap_delete_object`、`abap_publish_service_binding`
- 质量检查：`abap_run_unit_tests`、`abap_get_unit_test_run`、`abap_get_unit_test_result`、`abap_run_atc_checks`、`abap_get_atc_run`、`abap_get_atc_result`

## 支持对象

- `CLAS`、`INTF`
- `DDLS`、`DCLS`、`BDEF`、`DDLX`、`SRVD`、`SRVB`
- `TABL`、`DTEL`、`DOMA`、`DEVC`
- `PROG`、`FUGR`、`FUNC`

创建、更新、激活、发布和删除操作受 `allowed_packages` 限制。SAP 后端授权仍然生效。

## 登录流程

1. 调用 `abap_adt_login`。
2. 在浏览器中完成 SAP SSO。
3. 回调保存本地 ADT 会话。
4. 调用 `abap_adt_connect`。
5. 建议先读后写，只在需要时开启写入和激活。
