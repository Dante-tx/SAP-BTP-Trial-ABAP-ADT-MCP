# SAP-ADT MCP 使用问题记录

## 1. abap_read_source 不支持 SRVD/DDLS 类型

- **工具**: `abap_read_source`
- **时间**: 2026-06-17
- **错误**: `uri-only source operations currently support CLAS/INTF main/include ADT source URIs`
- **场景**: 尝试通过 URI 直接读取 `ZUI_INVOICE` (SRVD) 的源代码
- **根因**: URI-only 解析逻辑只识别 CLAS/INTF 类型，未复用已有 ADT path registry
- **修复**: 已扩展 `abap_read_source(uri=...)`，支持 registry 中的非 OO source URI，例如 DDLS/SRVD/DCLS/BDEF/DDLX/TABL/PROG/FUNC
- **状态**: ✅ 已修复

## 2. abap_get_object_metadata 不支持 URI 类型查询

- **工具**: `abap_get_object_metadata`
- **时间**: 2026-06-17
- **错误**: `GET /sap/bc/adt/businessservices/odatav4/ZUI_INVOICE_UI_V4: Parameter servicename could not be found`
- **场景**: 想查询 OData V4 Service Binding 信息
- **根因**: 直接传 `/sap/bc/adt/businessservices/odatav4/<binding>` 时缺少 ADT 后端要求的 `servicename` 查询参数
- **修复**: `abap_get_object_metadata(uri=...)` 对 `/sap/bc/adt/businessservices/odatav2|odatav4/<binding>` 自动补充 `?servicename=<BINDING>`
- **状态**: ✅ 已修复

## 3. abap_business_services-fetch_service_information 参数设计不合理

- **工具**: `abap_business_services-fetch_service_information`
- **时间**: 2026-06-17
- **错误**: 7 个必填参数：serviceBindingName, serviceName, serviceDefinition, serviceVersion, odataInfoUri, odataVersion, destination
- **场景**: 想查询 `ZUI_INVOICE_UI_V4` 绑定的 OData 信息
- **根因**: 工具签名把可由 service binding metadata 推导的信息全部设为必填
- **修复**: 现在只需 `serviceBindingName` + `destination`；`serviceName`、`serviceDefinition`、`serviceVersion`、`odataInfoUri`、`odataVersion` 可省略并自动从 `fetch_services` 结果推导
- **状态**: ✅ 已修复

## 4. abap_update_source scope/include_type 组合容易出错

- **工具**: `abap_update_source`
- **时间**: 2026-06-17
- **场景**: 更新 CLAS 的 implementations include
- **现象**: 更新 implementations include 需要同时传 `scope=include` + `include_type=implementations`，缺一不可。而更新 main 则只需 `scope=main`，不带 include_type
- **根因**: 两个参数组合逻辑不够直观，第一次用时不清楚怎么传
- **状态**: ⚠️ 文档提示不充分

## 5. abap_activate_object 报错信息不够精确

- **工具**: `abap_activate_object`
- **时间**: 2026-06-17
- **场景**: 激活 `ZBP_I_INVOICE_HEAD` 时多次语法报错
- **错误序列**:
  1. `"REPORTED was already declared"` — 实际是 REPORTED/FAILED 是 handler 类的上下文保留标识符，不能用作局部 DATA 变量名
  2. `"The statement before MODIFY... was not closed (period missing)"` — 实际原因是 `MODIFY FIELDS (LineNumber) WITH lt_items` 在 strict 模式下不被支持，但错误指向了句号
  3. `"The field @LT_ITEMS is unknown"` — `UPDATE FROM @lt_items` 的 `@` 前缀在 EML 中不需要
- **状态**: ⚠️ 错误提示可以更精准

## 6. abap_update_source 连续更新需注意 etag

- **工具**: `abap_update_source`
- **时间**: 2026-06-17
- **现象**: 连续多次更新同一 include 时，每次返回新 etag，下次必须用新 etag
- **状态**: ✅ 已知行为，遵循规范即可
