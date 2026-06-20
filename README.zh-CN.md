# SAP ABAP ADT MCP Server

通过 ADT HTTP API 为 AI 代理提供操作 SAP ABAP Development Tools 的 MCP 服务端。提供 27 个工具，覆盖完整的 ABAP 开发生命周期。

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

## MCP 工具（27 个）

### 会话与系统

| 工具 | 说明 | 操作 |
|------|------|------|
| `abap_list_destinations` | 列出可用的 ABAP 系统目的地 | _(无参数)_ |
| `abap_adt_session` | 管理 ADT 认证 | `login`、`validate`、`save_cookies`、`save_cookie_header`、`clear` |
| `abap_system_info` | 读取 ABAP 系统信息 | `system`、`components`、`users` |

### 对象发现

| 工具 | 说明 | 关键参数 |
|------|------|----------|
| `abap_find_objects` | 按名称、查询或包查找 ABAP 仓库对象 | `query`、`exact_name`、`name`、`object_type`、`package`、`search_mode`、`sort_by` |
| `abap_where_used` | 查找 ABAP 对象的引用位置（Where-Used） | `object_type`、`name`、`enable_all_types` |
| `abap_get_object_metadata` | 读取对象元数据、包、链接、源码结构 | `object_type`、`name`、`uri`、`destination` |

### 源代码

| 工具 | 说明 | 关键参数 |
|------|------|----------|
| `abap_read_source` | 读取 ABAP 源代码 | `object_type`、`name`、`scope`（main/include/active/inactive/both）、`include_type`、`uri` |
| `abap_update_source` | 更新 ABAP 源代码 | `object_type`、`name`、`source`、`include_type`、`etag`、`reason`、`transport_request_number` |
| `abap_syntax_check` | 在源码上运行语法检查（不激活） | `object_type`、`name`、`source` |
| `abap_code_assist` | 代码辅助 — 元素信息或格式化 | `action`（element_info/format）、`object_type`、`object_name`、`source`、`position` |

### 生命周期管理

| 工具 | 说明 | 关键参数 |
|------|------|----------|
| `abap_create_object` | 创建 ABAP 仓库对象 | `object_type`、`name`、`package`、`description`、`source`、`object_content`、`transport_request_number`、`implementation_type`、`service_binding_version` |
| `abap_creation_info` | 查看/验证创建元数据 | `action`（list_types/type_details/validate）、`destination`、`object_type` |
| `abap_activate` | 激活一个或多个 ABAP 对象 | `object_type`、`name`、`objects[]`、`reason` |
| `abap_delete_object` | 删除 ABAP 仓库对象 | `object_type`、`name`、`reason`、`etag`、`transport_request_number` |
| `abap_lock` | 锁定 ABAP 对象以供编辑 | `object_url`、`is_creation` |
| `abap_unlock` | 释放 ABAP 对象锁定 | `lock_handle`、`object_url` |

### 传输

| 工具 | 说明 | 操作 |
|------|------|------|
| `abap_transport` | 管理传输请求 | `get`、`create`、`list_tasks`、`objects`、`release` |

### 服务绑定

| 工具 | 说明 | 关键参数 |
|------|------|----------|
| `abap_business_services` | 读取服务绑定 OData 数据 | `action`（list_services/service_info）、`service_binding_name`、`destination` |
| `abap_publish_service_binding` | 发布 OData V2 或 V4 服务绑定 | `name`、`odata_version`、`reason` |
| `abap_unpublish_service_binding` | 取消发布 OData V2 或 V4 服务绑定 | `name`、`odata_version`、`reason` |

### RAP 生成器

| 工具 | 说明 | 操作 |
|------|------|------|
| `abap_generators` | 使用 RAP 生成器 | `list`、`schema`、`generate` |

### CDS 分析

| 工具 | 说明 | 操作 |
|------|------|------|
| `abap_cds_analysis` | 分析 CDS 视图 | `dependencies`、`related_objects`、`active_object`、`create_sql`、`object_relations` |

### 数据预览

| 工具 | 说明 | 操作 |
|------|------|------|
| `abap_data_preview` | 预览 CDS 视图、DDIC 表或自由 SQL 的数据 | `cds`、`ddic`、`freestyle` |

### 执行

| 工具 | 说明 | 关键参数 |
|------|------|----------|
| `abap_execute` | 执行 ABAP 程序或类 | `action`（program/class）、`object_name`、`parameters` |
| `abap_call_function` | 调用 ABAP 函数模块或 BAPI | `function_name`、`importing`、`changing`、`tables`、`commit`、`destination` |

### 质量检查

| 工具 | 说明 | 关键参数 |
|------|------|------|
| `abap_quality` | 运行 ABAP 质量检查（单元测试 / ATC） | `kind`（unit/atc）、`action`（start/status/result） |

## 支持的对象类型

| 类型 | 说明 |
|------|------|
| `CLAS` | 类 |
| `INTF` | 接口 |
| `DDLS` | CDS 视图 / 实体 |
| `DCLS` / `DCLX` | 访问控制（DCL） |
| `BDEF` | 行为定义 |
| `DDLX` | CDS 扩展 |
| `SRVD` | 服务定义 |
| `SRVB` | 服务绑定 |
| `TABL` | 表 / 结构 |
| `DTEL` | 数据元素 |
| `DOMA` | 域 |
| `DEVC` | 包 |
| `PROG` | 程序 |
| `FUGR` | 函数组 |
| `FUNC` | 函数模块 |

对象类型参数既可以传短类型（`TABL`、`DDLS`、`SRVB`），也可以传搜索/创建结果中的 ADT 类型 id。跨工具调用时优先使用短类型。

## 典型工作流

```
find/read → syntax_check → update_source → activate
```

1. 用 `abap_find_objects` 查找对象
2. 用 `abap_read_source` 读取源码
3. 用 `abap_syntax_check` 检查语法
4. 用 `abap_update_source` 更新源码
5. 用 `abap_activate` 激活

传输管理的系统需先用 `abap_transport(action="get")`。创建、更新、激活、发布和删除操作受 `allowed_packages` 限制。

## 登录流程

### SSO 模式

1. 设置 `abap_dev.auth_mode: "sso"`
2. 调用 `abap_adt_session(action="login")`
3. 在浏览器中完成 SAP SSO
4. 回调保存本地 ADT 会话
5. 调用 `abap_adt_session(action="validate")`

### Basic Auth 模式

1. 设置 `abap_dev.auth_mode: "basic"`
2. 配置 `abap_dev.username` 和 `abap_dev.password`
3. 调用 `abap_adt_session(action="validate")`

建议先读后写，只在需要时开启写入和激活。

## 项目结构

```
SAP-ABAP-ADT-MCP/
├── sap_mcp/                  # Python 包
│   ├── auth/                 # 认证（SSO）
│   ├── connectors/           # ADT API 连接器
│   │   ├── analysis/         # CDS 分析、代码辅助
│   │   ├── core/             # HTTP、认证、路径、XML 工具
│   │   ├── integration/      # 业务服务、目的地、生成器
│   │   ├── lifecycle/        # 激活、质量检查、语法检查、传输
│   │   ├── objects/          # 增删改查、搜索、执行、函数模块
│   │   └── system/           # 系统信息
│   ├── services/             # ABAP Dev Gateway
│   ├── tools/                # MCP 工具工作流
│   ├── mcp_server.py         # MCP 工具定义（27 个工具）
│   └── server.py             # HTTP/STDIO 服务入口
├── sap-mcp.example.yaml      # 示例配置
├── pyproject.toml            # Python 项目元数据
├── .gitignore
└── README.md
```
