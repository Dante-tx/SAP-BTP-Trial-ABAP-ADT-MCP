from pathlib import Path

import pytest
import respx
from httpx import Response

from app.auth.browser_sso import BrowserSsoSessionManager
from app.auth.browser_sso import BrowserSession
from app.config import AbapDevConfig, load_config
from app.connectors.adt import AdtConnector
from app.errors import AuthorizationError, ValidationError
from app.mcp_server import create_mcp


def test_browser_sso_session_uses_service_key_url(tmp_path):
    service_key = tmp_path / "service-key.json"
    service_key.write_text('{"url": "https://example.abap.local"}', encoding="utf-8")
    config = AbapDevConfig(service_key_path=service_key, session_path=tmp_path / "session.json")

    manager = BrowserSsoSessionManager(config)

    assert manager.login_url().startswith("https://example.abap-web.local/sap/bc/sec/reentrance")
    assert "redirect-url=http%3A%2F%2Flocalhost%3A8000%2Flogon%2Fsuccess" in manager.login_url()
    assert "scenario=FTO1" in manager.login_url()


def test_browser_sso_session_save_and_load(tmp_path):
    config = AbapDevConfig(system_url="https://example.abap.local", session_path=tmp_path / "session.json")
    manager = BrowserSsoSessionManager(config)

    result = manager.save_session({"SESSION": "abc"}, {"X-Test": "1"})
    session = manager.load_session()

    assert result["saved"] is True
    assert session.cookies == {"SESSION": "abc"}
    assert session.headers == {"X-Test": "1"}


def test_browser_sso_session_saves_reentrance_callback(tmp_path):
    config = AbapDevConfig(system_url="https://example.abap.local", session_path=tmp_path / "session.json")
    manager = BrowserSsoSessionManager(config)

    result = manager.save_reentrance_callback({"ticket": "secret-ticket"})
    session = manager.load_session()

    assert result["saved"] is True
    assert result["reentrance_fields"] == ["ticket"]
    assert session.reentrance == {"ticket": "secret-ticket"}


def test_browser_sso_session_saves_raw_cookie_header(tmp_path):
    config = AbapDevConfig(system_url="https://example.abap.local", session_path=tmp_path / "session.json")
    manager = BrowserSsoSessionManager(config)

    result = manager.save_cookie_header("A=1; B=two")
    session = manager.load_session()

    assert result["cookie_count"] == 2
    assert session.cookies == {"A": "1", "B": "two"}


def test_adt_read_path_supports_rap_and_cds_types(tmp_path):
    config = AbapDevConfig(system_url="https://example.abap.local", session_path=tmp_path / "session.json")
    session = BrowserSession(
        system_url="https://example.abap.local",
        cookies={},
        headers={},
        reentrance={"reentrance-ticket": "ticket"},
        created_at=0,
    )
    connector = AdtConnector(config, session)

    assert connector._read_path("DDLS", "ZI_INVOICE_HEAD") == (
        "/sap/bc/adt/ddic/ddl/sources/zi_invoice_head/source/main",
        "source",
    )
    assert connector._read_path("DCLS", "Z0000_AGENCY") == (
        "/sap/bc/adt/acm/dcl/sources/z0000_agency/source/main",
        "source",
    )
    assert connector._read_path("BDEF", "ZI_INVOICE_HEAD") == (
        "/sap/bc/adt/bo/behaviordefinitions/zi_invoice_head/source/main",
        "source",
    )
    assert connector._read_path("DDLX", "ZC_INVOICETABLE") == (
        "/sap/bc/adt/ddic/ddlx/sources/zc_invoicetable/source/main",
        "source",
    )
    assert connector._read_path("SRVD", "ZUI_INVOICE") == (
        "/sap/bc/adt/ddic/srvd/sources/zui_invoice/source/main",
        "source",
    )
    assert connector._read_path("SRVB", "ZUI_INVOICE_UI_V4") == (
        "/sap/bc/adt/businessservices/bindings/zui_invoice_ui_v4",
        "metadata",
    )
    assert connector._read_path("DTEL", "ZDE_INVOICE_TYPE") == (
        "/sap/bc/adt/ddic/dataelements/zde_invoice_type",
        "metadata",
    )
    assert connector._read_path("DOMA", "ZDM_INVOICE_TYPE") == (
        "/sap/bc/adt/ddic/domains/zdm_invoice_type",
        "metadata",
    )
    assert connector._read_path("DEVC", "ZRAP_TX") == (
        "/sap/bc/adt/packages/zrap_tx",
        "metadata",
    )
    assert connector._read_path("CLAS/implementations", "ZBP_I_INVOICETABLE") == (
        "/sap/bc/adt/oo/classes/zbp_i_invoicetable/includes/implementations",
        "source",
    )
    assert connector._read_path("CLAS/metadata", "ZBP_I_INVOICETABLE") == (
        "/sap/bc/adt/oo/classes/zbp_i_invoicetable",
        "metadata",
    )
    assert connector._read_path("CLAS/texts", "ZBP_I_INVOICETABLE") == (
        "/sap/bc/adt/textelements/classes/zbp_i_invoicetable",
        "metadata",
    )
    assert connector._source_path("DDLS", "YI_TEST") == "/sap/bc/adt/ddic/ddl/sources/yi_test/source/main"
    assert connector._source_path("TABL", "ZT_TEST") == "/sap/bc/adt/ddic/tables/zt_test/source/main"
    assert connector._source_path("DTEL", "YE_CHAR01") == "/sap/bc/adt/ddic/dataelements/ye_char01"
    assert connector._source_path("DOMA", "YD_CHAR01") == "/sap/bc/adt/ddic/domains/yd_char01"
    assert connector._source_path("DEVC", "ZRAP_TX") == "/sap/bc/adt/packages/zrap_tx"
    assert connector._read_path("PROG", "YTEST001") == (
        "/sap/bc/adt/programs/programs/ytest001/source/main",
        "source",
    )
    assert connector._read_path("FUGR", "YFG_TEST_MCP") == (
        "/sap/bc/adt/functions/groups/yfg_test_mcp",
        "metadata",
    )
    assert connector._read_path("FUNC", "YFG_TEST_MCP/YFM_TEST_MCP") == (
        "/sap/bc/adt/functions/groups/yfg_test_mcp/fmodules/yfm_test_mcp/source/main",
        "source",
    )


@pytest.mark.asyncio
@respx.mock
async def test_adt_read_class_source_includes_local_types(tmp_path):
    config = AbapDevConfig(system_url="https://example.abap.local", session_path=tmp_path / "session.json")
    session = BrowserSession(
        system_url="https://example.abap.local",
        cookies={},
        headers={},
        reentrance={},
        created_at=0,
    )
    class_metadata = """<?xml version="1.0" encoding="utf-8"?>
<class:abapClass xmlns:class="http://www.sap.com/adt/oo/classes"
  xmlns:abapsource="http://www.sap.com/adt/abapsource"
  xmlns:adtcore="http://www.sap.com/adt/core">
  <class:include class:includeType="definitions" abapsource:sourceUri="includes/definitions">
    <atom:link xmlns:atom="http://www.w3.org/2005/Atom" href="includes/definitions"
      rel="http://www.sap.com/adt/relations/source" type="text/plain" etag="def-etag" />
  </class:include>
  <class:include class:includeType="implementations" abapsource:sourceUri="includes/implementations">
    <atom:link xmlns:atom="http://www.w3.org/2005/Atom" href="includes/implementations"
      rel="http://www.sap.com/adt/relations/source" type="text/plain" etag="impl-etag" />
  </class:include>
  <class:include class:includeType="main" abapsource:sourceUri="source/main">
    <atom:link xmlns:atom="http://www.w3.org/2005/Atom" href="source/main"
      rel="http://www.sap.com/adt/relations/source" type="text/plain" etag="main-etag" />
  </class:include>
</class:abapClass>"""
    base_url = "https://example.abap.local/sap/bc/adt/oo/classes/zbp_i_invoicetable"
    respx.get(f"{base_url}/source/main").mock(
        return_value=Response(200, text="CLASS zbp_i_invoicetable DEFINITION.\nENDCLASS.", headers={"etag": "main-etag"})
    )
    respx.get(base_url).mock(return_value=Response(200, text=class_metadata))
    respx.get(f"{base_url}/includes/definitions").mock(
        return_value=Response(200, text="CLASS lhc_invoice DEFINITION.\nENDCLASS.", headers={"etag": "def-etag"})
    )
    respx.get(f"{base_url}/includes/implementations").mock(
        return_value=Response(200, text="CLASS lhc_invoice IMPLEMENTATION.\nENDCLASS.", headers={"etag": "impl-etag"})
    )

    result = await AdtConnector(config, session).read_source("CLAS/OC", "ZBP_I_INVOICETABLE")

    assert result["source_kind"] == "source_with_includes"
    assert "CLASS lhc_invoice DEFINITION" in result["source"]
    assert "CLASS lhc_invoice IMPLEMENTATION" in result["source"]
    assert [part["include_type"] for part in result["source_parts"]] == ["main", "definitions", "implementations"]
    assert result["includes"][0]["uri"] == "/sap/bc/adt/oo/classes/zbp_i_invoicetable/includes/definitions"


@pytest.mark.asyncio
@respx.mock
async def test_adt_search_falls_back_to_package_source_matches(tmp_path):
    config = AbapDevConfig(system_url="https://example.abap.local", session_path=tmp_path / "session.json")
    session = BrowserSession(
        system_url="https://example.abap.local",
        cookies={},
        headers={},
        reentrance={},
        created_at=0,
    )
    empty_search = """<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom" />"""
    class_search = """<?xml version="1.0" encoding="utf-8"?>
<adtcore:objectReferences xmlns:adtcore="http://www.sap.com/adt/core">
  <adtcore:objectReference adtcore:uri="/sap/bc/adt/oo/classes/zbp_i_invoicetable"
    adtcore:type="CLAS/OC" adtcore:name="ZBP_I_INVOICETABLE" adtcore:packageName="ZRAP_TX" />
</adtcore:objectReferences>"""
    class_metadata = """<?xml version="1.0" encoding="utf-8"?>
<class:abapClass xmlns:class="http://www.sap.com/adt/oo/classes"
  xmlns:abapsource="http://www.sap.com/adt/abapsource">
  <class:include class:includeType="implementations" abapsource:sourceUri="includes/implementations">
    <atom:link xmlns:atom="http://www.w3.org/2005/Atom" href="includes/implementations"
      rel="http://www.sap.com/adt/relations/source" type="text/plain" etag="impl-etag" />
  </class:include>
</class:abapClass>"""
    base_url = "https://example.abap.local/sap/bc/adt/oo/classes/zbp_i_invoicetable"
    respx.get("https://example.abap.local/sap/bc/adt/repository/informationsystem/search").mock(
        side_effect=[Response(200, text=empty_search), Response(200, text=class_search)]
    )
    respx.get(f"{base_url}/source/main").mock(return_value=Response(200, text="CLASS zbp_i_invoicetable DEFINITION."))
    respx.get(base_url).mock(return_value=Response(200, text=class_metadata))
    respx.get(f"{base_url}/includes/implementations").mock(
        return_value=Response(200, text="CLASS lhc_Invoice DEFINITION.\nENDCLASS.")
    )

    result = await AdtConnector(config, session).search_objects("lhc_Invoice", 20, "CLAS", "ZRAP_TX")

    assert result[0]["type"] == "SOURCE/LOCAL"
    assert result[0]["parentName"] == "ZBP_I_INVOICETABLE"
    assert result[0]["includeType"] == "implementations"
    assert result[0]["match"] == "CLASS lhc_Invoice DEFINITION."


@pytest.mark.asyncio
@respx.mock
async def test_adt_search_falls_back_to_cds_source_matches(tmp_path):
    config = AbapDevConfig(system_url="https://example.abap.local", session_path=tmp_path / "session.json")
    session = BrowserSession(
        system_url="https://example.abap.local",
        cookies={},
        headers={},
        reentrance={},
        created_at=0,
    )
    empty_search = """<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom" />"""
    ddls_search = """<?xml version="1.0" encoding="utf-8"?>
<adtcore:objectReferences xmlns:adtcore="http://www.sap.com/adt/core">
  <adtcore:objectReference adtcore:uri="/sap/bc/adt/ddic/ddl/sources/zi_invoicetable"
    adtcore:type="DDLS/DF" adtcore:name="ZI_INVOICETABLE" adtcore:packageName="ZRAP_TX" />
</adtcore:objectReferences>"""
    respx.get("https://example.abap.local/sap/bc/adt/repository/informationsystem/search").mock(
        side_effect=[Response(200, text=empty_search), Response(200, text=ddls_search)]
    )
    respx.get("https://example.abap.local/sap/bc/adt/ddic/ddl/sources/zi_invoicetable/source/main").mock(
        return_value=Response(200, text="define root view entity ZI_INVOICETABLE\n  as select from zinvoicetable\n{\n  key zuuid as Zuuid,\n      Filename\n}")
    )

    result = await AdtConnector(config, session).search_objects("Filename", 20, "DDLS", "ZRAP_TX")

    assert result[0]["type"] == "SOURCE/LOCAL"
    assert result[0]["parentName"] == "ZI_INVOICETABLE"
    assert result[0]["match"] == "Filename"


@pytest.mark.asyncio
@respx.mock
async def test_adt_search_allows_standard_packages_for_read(tmp_path):
    config = AbapDevConfig(system_url="https://example.abap.local", session_path=tmp_path / "session.json")
    session = BrowserSession(
        system_url="https://example.abap.local",
        cookies={},
        headers={},
        reentrance={},
        created_at=0,
    )
    search_result = """<?xml version="1.0" encoding="utf-8"?>
<adtcore:objectReferences xmlns:adtcore="http://www.sap.com/adt/core">
  <adtcore:objectReference adtcore:uri="/sap/bc/adt/oo/classes/cl_abap_context_info"
    adtcore:type="CLAS/OC" adtcore:name="CL_ABAP_CONTEXT_INFO" adtcore:packageName="SABP_CORE" />
</adtcore:objectReferences>"""
    respx.get("https://example.abap.local/sap/bc/adt/repository/informationsystem/search").mock(
        return_value=Response(200, text=search_result)
    )

    result = await AdtConnector(config, session).search_objects("CL_ABAP_CONTEXT_INFO", 20, "CLAS", "SABP_CORE")

    assert result[0]["packageName"] == "SABP_CORE"


@pytest.mark.asyncio
@respx.mock
async def test_adt_update_rejects_standard_package_objects(tmp_path):
    config = AbapDevConfig(
        system_url="https://example.abap.local",
        session_path=tmp_path / "session.json",
        allow_write=True,
        allowed_packages=["Z*"],
    )
    session = BrowserSession(
        system_url="https://example.abap.local",
        cookies={},
        headers={},
        reentrance={},
        created_at=0,
    )
    search_result = """<?xml version="1.0" encoding="utf-8"?>
<adtcore:objectReferences xmlns:adtcore="http://www.sap.com/adt/core">
  <adtcore:objectReference adtcore:uri="/sap/bc/adt/oo/classes/cl_abap_context_info"
    adtcore:type="CLAS/OC" adtcore:name="CL_ABAP_CONTEXT_INFO" adtcore:packageName="SABP_CORE" />
</adtcore:objectReferences>"""
    respx.get("https://example.abap.local/sap/bc/adt/repository/informationsystem/search").mock(
        return_value=Response(200, text=search_result)
    )

    with pytest.raises(AuthorizationError, match="write allowlist"):
        await AdtConnector(config, session).update_source("CLAS", "CL_ABAP_CONTEXT_INFO", "source", "etag", "test")


@pytest.mark.asyncio
@respx.mock
async def test_adt_search_does_not_source_scan_standard_packages(tmp_path):
    config = AbapDevConfig(system_url="https://example.abap.local", session_path=tmp_path / "session.json")
    session = BrowserSession(
        system_url="https://example.abap.local",
        cookies={},
        headers={},
        reentrance={},
        created_at=0,
    )
    empty_search = """<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom" />"""
    route = respx.get("https://example.abap.local/sap/bc/adt/repository/informationsystem/search").mock(
        return_value=Response(200, text=empty_search)
    )

    result = await AdtConnector(config, session).search_objects("internal_symbol", 20, "CLAS", "SABP_CORE")

    assert result == []
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_adt_create_ddls_uses_metadata_then_source_put(tmp_path):
    config = AbapDevConfig(
        system_url="https://example.abap.local",
        session_path=tmp_path / "session.json",
        allow_write=True,
        allowed_packages=["Z*"],
    )
    session = BrowserSession(
        system_url="https://example.abap.local",
        cookies={},
        headers={},
        reentrance={},
        created_at=0,
    )
    respx.get("https://example.abap.local/sap/bc/adt/discovery").mock(
        return_value=Response(200, text="<service />", headers={"x-csrf-token": "token"})
    )
    create_route = respx.post("https://example.abap.local/sap/bc/adt/ddic/ddl/sources").mock(
        return_value=Response(201, text="<ddl />", headers={"etag": "created-etag"})
    )
    source_route = respx.put("https://example.abap.local/sap/bc/adt/ddic/ddl/sources/yi_test/source/main").mock(
        return_value=Response(200, text="", headers={"etag": "source-etag"})
    )

    result = await AdtConnector(config, session).create_object(
        "DDLS",
        "YI_TEST",
        "ZRAP_TX",
        "test mcp",
        "test",
        "define view entity YI_TEST as select from zinvoice_head { key zuuid }",
    )

    assert result["created"] is True
    assert result["etag"] == "source-etag"
    assert 'adtcore:name="YI_TEST"' in create_route.calls[0].request.content.decode("utf-8")
    assert source_route.calls[0].request.headers["if-match"] == "created-etag"


@pytest.mark.asyncio
@respx.mock
async def test_adt_create_srvb_uses_service_binding_metadata(tmp_path):
    config = AbapDevConfig(
        system_url="https://example.abap.local",
        session_path=tmp_path / "session.json",
        allow_write=True,
        allowed_packages=["Z*"],
    )
    session = BrowserSession(
        system_url="https://example.abap.local",
        cookies={},
        headers={},
        reentrance={},
        created_at=0,
    )
    respx.get("https://example.abap.local/sap/bc/adt/discovery").mock(
        return_value=Response(200, text="<service />", headers={"x-csrf-token": "token"})
    )
    create_route = respx.post("https://example.abap.local/sap/bc/adt/businessservices/bindings").mock(
        return_value=Response(201, text="<srvb />", headers={"etag": "srvb-etag"})
    )

    result = await AdtConnector(config, session).create_object(
        "SRVB",
        "ZUI_INVOICETABLE_TEST",
        "ZRAP_TX",
        "Test binding",
        "test",
        "ZUI_INVOICETABLE",
    )

    body = create_route.calls[0].request.content.decode("utf-8")
    assert result["created"] is True
    assert result["service_definition"] == "ZUI_INVOICETABLE"
    assert 'adtcore:name="ZUI_INVOICETABLE_TEST"' in body
    assert 'srvb:version="V4"' in body
    assert 'adtcore:name="ZUI_INVOICETABLE"' in body


@pytest.mark.asyncio
@respx.mock
async def test_adt_create_function_module_uses_function_group_container(tmp_path):
    config = AbapDevConfig(
        system_url="https://example.abap.local",
        session_path=tmp_path / "session.json",
        allow_write=True,
        allowed_packages=["Z*"],
    )
    session = BrowserSession(
        system_url="https://example.abap.local",
        cookies={},
        headers={},
        reentrance={},
        created_at=0,
    )
    search_result = """<?xml version="1.0" encoding="utf-8"?>
<adtcore:objectReferences xmlns:adtcore="http://www.sap.com/adt/core">
  <adtcore:objectReference adtcore:uri="/sap/bc/adt/functions/groups/yfg_test_mcp"
    adtcore:type="FUGR/F" adtcore:name="YFG_TEST_MCP" adtcore:packageName="ZRAP_TX" />
</adtcore:objectReferences>"""
    respx.get("https://example.abap.local/sap/bc/adt/repository/informationsystem/search").mock(
        return_value=Response(200, text=search_result)
    )
    respx.get("https://example.abap.local/sap/bc/adt/discovery").mock(
        return_value=Response(200, text="<service />", headers={"x-csrf-token": "token"})
    )
    create_route = respx.post(
        "https://example.abap.local/sap/bc/adt/functions/groups/yfg_test_mcp/fmodules"
    ).mock(return_value=Response(201, text="<fmodule />"))

    result = await AdtConnector(config, session).create_object(
        "FUNC",
        "YFM_TEST_MCP02",
        "ZRAP_TX",
        "test mcp",
        "test",
        "YFG_TEST_MCP",
    )

    body = create_route.calls[0].request.content.decode("utf-8")
    assert result["created"] is True
    assert result["function_group"] == "YFG_TEST_MCP"
    assert 'adtcore:name="YFM_TEST_MCP02"' in body
    assert 'adtcore:type="FUGR/FF"' in body
    assert 'adtcore:name="YFG_TEST_MCP"' in body


@pytest.mark.asyncio
@respx.mock
async def test_adt_create_domain_uses_domain_metadata(tmp_path):
    config = AbapDevConfig(
        system_url="https://example.abap.local",
        session_path=tmp_path / "session.json",
        allow_write=True,
        allowed_packages=["Z*"],
    )
    session = BrowserSession(
        system_url="https://example.abap.local",
        cookies={},
        headers={},
        reentrance={},
        created_at=0,
    )
    respx.get("https://example.abap.local/sap/bc/adt/discovery").mock(
        return_value=Response(200, text="<service />", headers={"x-csrf-token": "token"})
    )
    create_route = respx.post("https://example.abap.local/sap/bc/adt/ddic/domains").mock(
        return_value=Response(201, text="<domain />", headers={"etag": "domain-etag"})
    )

    result = await AdtConnector(config, session).create_object("DOMA", "YD_CHAR01", "ZRAP_TX", "test mcp", "test")

    body = create_route.calls[0].request.content.decode("utf-8")
    assert result["created"] is True
    assert result["object_type"] == "DOMA"
    assert 'adtcore:name="YD_CHAR01"' in body
    assert "<doma:dataType>CHAR</doma:dataType>" in body


@pytest.mark.asyncio
@respx.mock
async def test_adt_create_package_uses_parent_package_metadata(tmp_path):
    config = AbapDevConfig(
        system_url="https://example.abap.local",
        session_path=tmp_path / "session.json",
        allow_write=True,
        allowed_packages=["Z*"],
    )
    session = BrowserSession(
        system_url="https://example.abap.local",
        cookies={},
        headers={},
        reentrance={},
        created_at=0,
    )
    respx.get("https://example.abap.local/sap/bc/adt/discovery").mock(
        return_value=Response(200, text="<service />", headers={"x-csrf-token": "token"})
    )
    create_route = respx.post("https://example.abap.local/sap/bc/adt/packages").mock(
        return_value=Response(201, text="<package />", headers={"etag": "package-etag"})
    )

    result = await AdtConnector(config, session).create_object("DEVC", "ZCHILD", "ZPARENT", "test mcp", "test")

    body = create_route.calls[0].request.content.decode("utf-8")
    assert result["created"] is True
    assert result["object_type"] == "DEVC"
    assert 'adtcore:name="ZCHILD"' in body
    assert 'adtcore:name="ZPARENT"' in body


@pytest.mark.asyncio
@respx.mock
async def test_adt_update_metadata_objects_uses_xml_content_type(tmp_path):
    config = AbapDevConfig(
        system_url="https://example.abap.local",
        session_path=tmp_path / "session.json",
        allow_write=True,
        allowed_packages=["Z*"],
    )
    session = BrowserSession(
        system_url="https://example.abap.local",
        cookies={},
        headers={},
        reentrance={},
        created_at=0,
    )
    search_result = """<?xml version="1.0" encoding="utf-8"?>
<adtcore:objectReferences xmlns:adtcore="http://www.sap.com/adt/core">
  <adtcore:objectReference adtcore:uri="/sap/bc/adt/ddic/dataelements/ye_char01"
    adtcore:type="DTEL/DE" adtcore:name="YE_CHAR01" adtcore:packageName="ZRAP_TX" />
</adtcore:objectReferences>"""
    respx.get("https://example.abap.local/sap/bc/adt/repository/informationsystem/search").mock(
        return_value=Response(200, text=search_result)
    )
    respx.get("https://example.abap.local/sap/bc/adt/discovery").mock(
        return_value=Response(200, text="<service />", headers={"x-csrf-token": "token"})
    )
    update_route = respx.put("https://example.abap.local/sap/bc/adt/ddic/dataelements/ye_char01").mock(
        return_value=Response(200, text="<dtel />", headers={"etag": "updated-etag"})
    )

    result = await AdtConnector(config, session).update_source("DTEL", "YE_CHAR01", "<dtel />", "etag", "test")

    assert result["updated"] is True
    assert update_route.calls[0].request.headers["content-type"] == "application/xml; charset=utf-8"


@pytest.mark.asyncio
@respx.mock
async def test_adt_function_module_write_permission_uses_function_group_package(tmp_path):
    config = AbapDevConfig(
        system_url="https://example.abap.local",
        session_path=tmp_path / "session.json",
        allow_write=True,
        allowed_packages=["Z*"],
    )
    session = BrowserSession(
        system_url="https://example.abap.local",
        cookies={},
        headers={},
        reentrance={},
        created_at=0,
    )
    search_result = """<?xml version="1.0" encoding="utf-8"?>
<adtcore:objectReferences xmlns:adtcore="http://www.sap.com/adt/core">
  <adtcore:objectReference adtcore:uri="/sap/bc/adt/functions/groups/yfg_test_mcp"
    adtcore:type="FUGR/F" adtcore:name="YFG_TEST_MCP" adtcore:packageName="ZRAP_TX" />
</adtcore:objectReferences>"""
    respx.get("https://example.abap.local/sap/bc/adt/repository/informationsystem/search").mock(
        return_value=Response(200, text=search_result)
    )

    package = await AdtConnector(config, session)._object_package("FUNC", "YFG_TEST_MCP/YFM_TEST_MCP")

    assert package == "ZRAP_TX"


@pytest.mark.asyncio
@respx.mock
async def test_adt_publish_service_binding_uses_odatav4_publish_job(tmp_path):
    config = AbapDevConfig(
        system_url="https://example.abap.local",
        session_path=tmp_path / "session.json",
        allow_write=True,
        allowed_packages=["Z*"],
    )
    session = BrowserSession(
        system_url="https://example.abap.local",
        cookies={},
        headers={},
        reentrance={},
        created_at=0,
    )
    search_result = """<?xml version="1.0" encoding="utf-8"?>
<adtcore:objectReferences xmlns:adtcore="http://www.sap.com/adt/core">
  <adtcore:objectReference adtcore:uri="/sap/bc/adt/businessservices/bindings/zui_invoicetable_test"
    adtcore:type="SRVB/SVB" adtcore:name="ZUI_INVOICETABLE_TEST" adtcore:packageName="ZRAP_TX" />
</adtcore:objectReferences>"""
    binding_metadata = """<?xml version="1.0" encoding="utf-8"?>
<srvb:serviceBinding xmlns:srvb="http://www.sap.com/adt/ddic/ServiceBindings"
  xmlns:adtcore="http://www.sap.com/adt/core"
  srvb:published="false" adtcore:name="ZUI_INVOICETABLE_TEST" adtcore:type="SRVB/SVB" />"""
    status = """<?xml version="1.0" encoding="utf-8"?>
<statusMessages>
  <statusMessage severity="INFO">Local Publish of ZUI_INVOICETABLE_TEST finished</statusMessage>
</statusMessages>"""
    respx.get("https://example.abap.local/sap/bc/adt/repository/informationsystem/search").mock(
        return_value=Response(200, text=search_result)
    )
    respx.get("https://example.abap.local/sap/bc/adt/businessservices/bindings/zui_invoicetable_test").mock(
        return_value=Response(200, text=binding_metadata)
    )
    respx.get("https://example.abap.local/sap/bc/adt/discovery").mock(
        return_value=Response(200, text="<service />", headers={"x-csrf-token": "token"})
    )
    publish_route = respx.post("https://example.abap.local/sap/bc/adt/businessservices/odatav4/publishjobs").mock(
        return_value=Response(200, text=status)
    )

    result = await AdtConnector(config, session).publish_service_binding("ZUI_INVOICETABLE_TEST", "test")

    body = publish_route.calls[0].request.content.decode("utf-8")
    assert result["published"] is True
    assert result["changed"] is True
    assert "servicename=ZUI_INVOICETABLE_TEST" in str(publish_route.calls[0].request.url)
    assert 'adtcore:name="ZUI_INVOICETABLE_TEST"' in body
    assert 'adtcore:type="SRVB/SVB"' in body
    assert "/sap/bc/adt/businessservices/odatav4/ZUI_INVOICETABLE_TEST" in body


@pytest.mark.asyncio
@respx.mock
async def test_adt_publish_service_binding_is_idempotent_when_already_published(tmp_path):
    config = AbapDevConfig(
        system_url="https://example.abap.local",
        session_path=tmp_path / "session.json",
        allow_write=True,
        allowed_packages=["Z*"],
    )
    session = BrowserSession(
        system_url="https://example.abap.local",
        cookies={},
        headers={},
        reentrance={},
        created_at=0,
    )
    search_result = """<?xml version="1.0" encoding="utf-8"?>
<adtcore:objectReferences xmlns:adtcore="http://www.sap.com/adt/core">
  <adtcore:objectReference adtcore:uri="/sap/bc/adt/businessservices/bindings/zui_invoicetable_test"
    adtcore:type="SRVB/SVB" adtcore:name="ZUI_INVOICETABLE_TEST" adtcore:packageName="ZRAP_TX" />
</adtcore:objectReferences>"""
    binding_metadata = """<?xml version="1.0" encoding="utf-8"?>
<srvb:serviceBinding xmlns:srvb="http://www.sap.com/adt/ddic/ServiceBindings"
  xmlns:adtcore="http://www.sap.com/adt/core"
  srvb:published="true" adtcore:name="ZUI_INVOICETABLE_TEST" adtcore:type="SRVB/SVB" />"""
    respx.get("https://example.abap.local/sap/bc/adt/repository/informationsystem/search").mock(
        return_value=Response(200, text=search_result)
    )
    respx.get("https://example.abap.local/sap/bc/adt/businessservices/bindings/zui_invoicetable_test").mock(
        return_value=Response(200, text=binding_metadata)
    )

    result = await AdtConnector(config, session).publish_service_binding("ZUI_INVOICETABLE_TEST", "test")

    assert result["published"] is True
    assert result["changed"] is False


@pytest.mark.asyncio
@respx.mock
async def test_adt_delete_ddls_retries_server_etag(tmp_path):
    config = AbapDevConfig(
        system_url="https://example.abap.local",
        session_path=tmp_path / "session.json",
        allow_write=True,
        allowed_packages=["Z*"],
    )
    session = BrowserSession(
        system_url="https://example.abap.local",
        cookies={},
        headers={},
        reentrance={},
        created_at=0,
    )
    search_result = """<?xml version="1.0" encoding="utf-8"?>
<adtcore:objectReferences xmlns:adtcore="http://www.sap.com/adt/core">
  <adtcore:objectReference adtcore:uri="/sap/bc/adt/ddic/ddl/sources/yi_test"
    adtcore:type="DDLS/DF" adtcore:name="YI_TEST" adtcore:packageName="ZRAP_TX" />
</adtcore:objectReferences>"""
    respx.get("https://example.abap.local/sap/bc/adt/repository/informationsystem/search").mock(
        return_value=Response(200, text=search_result)
    )
    respx.get("https://example.abap.local/sap/bc/adt/discovery").mock(
        return_value=Response(200, text="<service />", headers={"x-csrf-token": "token"})
    )
    respx.get("https://example.abap.local/sap/bc/adt/ddic/ddl/sources/yi_test").mock(
        return_value=Response(200, text="<ddl />", headers={"etag": "client-etag"})
    )
    delete_route = respx.delete("https://example.abap.local/sap/bc/adt/ddic/ddl/sources/yi_test").mock(
        side_effect=[
            Response(
                412,
                text="Client ETag client-etag does not match the object ETag server-etag in the server",
            ),
            Response(200, text=""),
        ]
    )

    result = await AdtConnector(config, session).delete_object("DDLS", "YI_TEST", "test")

    assert result["deleted"] is True
    assert delete_route.calls[0].request.headers["if-match"] == "client-etag"
    assert delete_route.calls[1].request.headers["if-match"] == "server-etag"


@pytest.mark.asyncio
@respx.mock
async def test_adt_discovery_with_saved_session(tmp_path):
    config = AbapDevConfig(system_url="https://example.abap.local", session_path=tmp_path / "session.json")
    manager = BrowserSsoSessionManager(config)
    session = manager.save_session({"SESSION": "abc"})
    loaded = manager.load_session()
    respx.get("https://example.abap.local/sap/bc/adt/discovery").mock(
        return_value=Response(200, text="<service />", headers={"content-type": "application/xml"})
    )

    result = await AdtConnector(config, loaded).discovery()

    assert session["cookie_count"] == 1
    assert result["connected"] is True


@pytest.mark.asyncio
@respx.mock
async def test_adt_unauthorized_reports_relogin(tmp_path):
    config = AbapDevConfig(system_url="https://example.abap.local", session_path=tmp_path / "session.json")
    manager = BrowserSsoSessionManager(config)
    manager.save_session({"SESSION": "abc"})
    respx.get("https://example.abap.local/sap/bc/adt/discovery").mock(return_value=Response(401, text="login"))

    with pytest.raises(AuthorizationError, match="abap_adt_login"):
        await AdtConnector(config, manager.load_session()).discovery()


def test_mcp_registers_abap_dev_tools():
    config = load_config(Path("sap-mcp.example.yaml"))
    mcp = create_mcp(config)
    tools = {tool.name for tool in mcp._tool_manager.list_tools()}

    assert "abap_adt_login" in tools
    assert "abap_save_sso_cookie_header" in tools
    assert "abap_create_object" in tools
    assert "abap_read_source" in tools
    assert "abap_update_source" in tools
    assert "abap_delete_object" in tools
    assert "abap_publish_service_binding" in tools
