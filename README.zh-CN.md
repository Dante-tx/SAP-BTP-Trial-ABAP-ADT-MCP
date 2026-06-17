# SAP ABAP ADT MCP Server

这是一个通过 ADT HTTP API 操作 SAP ABAP Development Tools 的 MCP 服务端。

## 功能

- 浏览器 SSO 登录 ADT。
- ABAP Repository 搜索。
- 源码和元数据读取。
- 受控创建、更新、激活、发布和删除。
- 通过 ADT REST 服务运行 ABAP Unit 和 ATC。
- 提供对象创建、RAP 生成器、传输和业务服务查询工作流。
- 支持 HTTP 和 STDIO 两种 Transport。

## 运行要求

- Python 3.11+
- 已启用 ADT 的 SAP ABAP 系统
- 可以通过浏览器完成目标系统 SSO，或具备可访问 ADT 的 Basic Auth 账号密码
- 可选：用于 ABAP Unit（`SAP_COM_0735`）和 ATC（`SAP_COM_0901`）的通信安排

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -e .
copy sap-mcp.example.yaml sap-mcp.yaml
```

编辑 `sap-mcp.yaml`，至少配置：

- `abap_dev.system_url`
- 如 SAP 系统要求明确集团，配置 `abap_dev.client`，例如 `100`
- `abap_dev.auth_mode`：`sso`、`basic` 或 `auto`（默认）
- 如使用 `basic` 或 `auto`，配置 `abap_dev.username` / `abap_dev.password`
- `allowed_packages`
- `allow_write` / `allow_activate`
- 旧字段 `communication_user` / `communication_password` 仍可作为 Basic Auth 账号密码别名使用

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
- ADT 兼容工作流：`abap_list_destinations`、`abap_creation-*`、`abap_generators-*`、`abap_transport-*`、`abap_business_services-*`

## 支持对象

- `CLAS`、`INTF`
- `DDLS`、`DCLS`、`BDEF`、`DDLX`、`SRVD`、`SRVB`
- `TABL`、`DTEL`、`DOMA`、`DEVC`
- `PROG`、`FUGR`、`FUNC`

对于 Service Binding，`abap_create_object` 支持可选参数 `service_binding_version`（`V2` 或 `V4`，默认 `V4`）。
`abap_publish_service_binding` 支持可选参数 `odata_version`（`V2` 或 `V4`）；未传时会尝试从 SRVB 元数据识别版本，并对既有调用回退到 `V4`。

创建、更新、激活、发布和删除操作受 `allowed_packages` 限制。SAP 后端授权仍然生效。

## 登录流程

SSO 模式：

1. 设置 `abap_dev.auth_mode: "sso"`。
2. 调用 `abap_adt_login`。
3. 在浏览器中完成 SAP SSO。
4. 回调保存本地 ADT 会话。
5. 调用 `abap_adt_connect`。

Basic Auth 模式：

1. 设置 `abap_dev.auth_mode: "basic"`。
2. 配置 `abap_dev.username` 和 `abap_dev.password`。
3. 调用 `abap_adt_connect`。

建议先读后写，只在需要时开启写入和激活。
