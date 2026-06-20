from __future__ import annotations

from dataclasses import dataclass

ADT_ACCEPT = "application/atom+xml, application/xml, text/plain, */*"
ADT_BASE_PATH = "/sap/bc/adt"

# Shared error message for unsupported object types (used across multiple files)
# WARNING: Keep in sync with the alias list in ADT_PATH_REGISTRATIONS
SUPPORTED_TYPES_HELP = (
    "Supported object types are class, interface, ddls/cds, dcls/dcl, bdef, "
    "ddlx, srvd, srvb, tabl, dtel, doma, devc, prog, incl, fugr, and func"
)
SUPPORTED_SOURCE_TYPES_HELP = (
    "Supported source types are class, interface, ddls/cds, dcls/dcl, bdef, "
    "ddlx, srvd, tabl, dtel, doma, devc, srvb, prog, incl, fugr, and func"
)
SUPPORTED_SEARCH_TYPES_HELP = (
    "Supported search types are class, interface, ddls/cds, dcls/dcl, bdef, "
    "ddlx, srvd, srvb, tabl, dtel, doma, devc, prog, incl, fugr, and func"
)
SUPPORTED_WRITABLE_TYPES_HELP = (
    "Writable types are class, interface, ddls/cds, dcls/dcl, bdef, "
    "ddlx, srvd, srvb, tabl, dtel, doma, devc, prog, incl, fugr, and func"
)

# Default language version for ABAP Cloud Development
DEFAULT_ABAP_LANGUAGE_VERSION = "cloudDevelopment"

# User-Agent string
USER_AGENT = "sap-mcp-adt/0.1"

# Default search/max results limits
DEFAULT_MAX_RESULTS = 20
MAX_SEARCH_RESULTS_CAP = 100
DEFAULT_PACKAGE_LIST_LIMIT = 100
LARGE_PACKAGE_THRESHOLD = 20


@dataclass(frozen=True)
class AdtResponse:
    status_code: int
    text: str
    headers: dict[str, str]
    content_type: str


@dataclass(frozen=True)
class AdtPathRegistration:
    canonical_type: str
    aliases: frozenset[str]
    root_template: str
    source_suffix: str | None
    read_suffix: str | None
    read_kind: str
    search_type: str
    source_search: bool = True
    oo_source: bool = False
    texts_template: str | None = None
    display_name: str = "Object"
    collection_template: str | None = None
    create_xml_name: str | None = None
    create_xml_namespace: str | None = None
    create_adt_type: str | None = None
    create_content_type: str | None = None
    create_accept: str | None = None
    create_abap_language_version: str | None = DEFAULT_ABAP_LANGUAGE_VERSION
    create_xml_extra_attrs: str | None = None


@dataclass(frozen=True)
class SourceTarget:
    object_type: str
    name: str
    uri: str
    source_kind: str
    scope: str
    include_type: str | None = None
    round_trippable: bool = True
    read_hint: str | None = None


ADT_PATH_REGISTRATIONS = (
    AdtPathRegistration(
        canonical_type="CLAS",
        aliases=frozenset({"class", "clas"}),
        root_template="/sap/bc/adt/oo/classes/{name}",
        source_suffix="source/main",
        read_suffix="source/main",
        read_kind="source",
        search_type="CLAS",
        oo_source=True,
        texts_template="/sap/bc/adt/textelements/classes/{name}",
        display_name="Class",
        collection_template="/sap/bc/adt/oo/classes",
        create_xml_name="class:abapClass",
        create_xml_namespace='xmlns:class="http://www.sap.com/adt/oo/classes"',
        create_adt_type="CLAS/OC",
        create_content_type="application/vnd.sap.adt.oo.classes.v4+xml; charset=utf-8",
        create_accept="application/vnd.sap.adt.oo.classes.v4+xml, application/xml, */*",
    ),
    AdtPathRegistration(
        canonical_type="INTF",
        aliases=frozenset({"interface", "intf"}),
        root_template="/sap/bc/adt/oo/interfaces/{name}",
        source_suffix="source/main",
        read_suffix="source/main",
        read_kind="source",
        search_type="INTF",
        oo_source=True,
        texts_template="/sap/bc/adt/textelements/interfaces/{name}",
        display_name="Interface",
        collection_template="/sap/bc/adt/oo/interfaces",
        create_xml_name="intf:abapInterface",
        create_xml_namespace='xmlns:intf="http://www.sap.com/adt/oo/interfaces"',
        create_adt_type="INTF/OI",
        create_content_type="application/vnd.sap.adt.oo.interfaces.v5+xml; charset=utf-8",
        create_accept="application/vnd.sap.adt.oo.interfaces.v5+xml, application/xml, */*",
        create_abap_language_version=None,
    ),
    AdtPathRegistration(
        "DDLS",
        frozenset({"ddls", "cds"}),
        "/sap/bc/adt/ddic/ddl/sources/{name}",
        "source/main",
        "source/main",
        "source",
        "DDLS",
        collection_template="/sap/bc/adt/ddic/ddl/sources",
        create_xml_name="ddl:ddlSource",
        create_xml_namespace='xmlns:ddl="http://www.sap.com/adt/ddic/ddlsources"',
        create_adt_type="DDLS/DF",
        create_content_type="application/vnd.sap.adt.ddlSource+xml; charset=utf-8",
        create_accept="application/vnd.sap.adt.ddlSource+xml, application/xml, */*",
    ),
    AdtPathRegistration(
        "DCLS",
        frozenset({"dcls", "dcl"}),
        "/sap/bc/adt/acm/dcl/sources/{name}",
        "source/main",
        "source/main",
        "source",
        "DCLS",
        collection_template="/sap/bc/adt/acm/dcl/sources",
        create_xml_name="dcl:dclSource",
        create_xml_namespace='xmlns:dcl="http://www.sap.com/adt/acm/dclsources"',
        create_adt_type="DCLS/DL",
        create_content_type="application/vnd.sap.adt.dclSource+xml; charset=utf-8",
        create_accept="application/vnd.sap.adt.dclSource+xml, application/xml, */*",
    ),
    AdtPathRegistration(
        "BDEF",
        frozenset({"bdef", "behavior", "behavior_definition"}),
        "/sap/bc/adt/bo/behaviordefinitions/{name}",
        "source/main",
        "source/main",
        "source",
        "BDEF",
        collection_template="/sap/bc/adt/bo/behaviordefinitions",
        create_adt_type="BDEF/BDO",
        create_content_type="application/vnd.sap.adt.blues.v1+xml; charset=utf-8",
        create_accept="application/vnd.sap.adt.blues.v1+xml, application/xml, */*",
    ),
    AdtPathRegistration(
        "DDLX",
        frozenset({"ddlx", "metadata_extension"}),
        "/sap/bc/adt/ddic/ddlx/sources/{name}",
        "source/main",
        "source/main",
        "source",
        "DDLX",
        collection_template="/sap/bc/adt/ddic/ddlx/sources",
        create_xml_name="ddlxsources:ddlxSource",
        create_xml_namespace='xmlns:ddlxsources="http://www.sap.com/adt/ddic/ddlxsources"',
        create_adt_type="DDLX/EX",
        create_content_type="application/vnd.sap.adt.ddic.ddlx.v1+xml; charset=utf-8",
        create_accept="application/vnd.sap.adt.ddic.ddlx.v1+xml, application/xml, */*",
    ),
    AdtPathRegistration(
        "SRVD",
        frozenset({"srvd", "service_definition"}),
        "/sap/bc/adt/ddic/srvd/sources/{name}",
        "source/main",
        "source/main",
        "source",
        "SRVD",
        collection_template="/sap/bc/adt/ddic/srvd/sources",
        create_xml_name="srvd:srvdSource",
        create_xml_namespace='xmlns:srvd="http://www.sap.com/adt/ddic/srvdsources"',
        create_adt_type="SRVD/SRV",
        create_content_type="application/vnd.sap.adt.ddic.srvd.v1+xml; charset=utf-8",
        create_accept="application/vnd.sap.adt.ddic.srvd.v1+xml, application/xml, */*",
        create_xml_extra_attrs='srvd:srvdSourceType="S"',
    ),
    AdtPathRegistration(
        "TABL",
        frozenset({"tabl", "table"}),
        "/sap/bc/adt/ddic/tables/{name}",
        "source/main",
        "source/main",
        "source",
        "TABL",
        collection_template="/sap/bc/adt/ddic/tables",
        create_adt_type="TABL/DT",
        create_content_type="application/vnd.sap.adt.tables.v2+xml; charset=utf-8",
        create_accept="application/vnd.sap.adt.tables.v2+xml, application/xml, */*",
    ),
    AdtPathRegistration(
        "DTEL",
        frozenset({"dtel", "data_element"}),
        "/sap/bc/adt/ddic/dataelements/{name}",
        None,
        None,
        "metadata",
        "DTEL",
        collection_template="/sap/bc/adt/ddic/dataelements",
    ),
    AdtPathRegistration(
        "DOMA",
        frozenset({"doma", "domain"}),
        "/sap/bc/adt/ddic/domains/{name}",
        None,
        None,
        "metadata",
        "DOMA",
        collection_template="/sap/bc/adt/ddic/domains",
    ),
    AdtPathRegistration(
        "DEVC",
        frozenset({"devc", "package"}),
        "/sap/bc/adt/packages/{name}",
        None,
        None,
        "metadata",
        "DEVC",
        source_search=False,
        collection_template="/sap/bc/adt/packages",
    ),
    AdtPathRegistration(
        "SRVB",
        frozenset({"srvb", "service_binding"}),
        "/sap/bc/adt/businessservices/bindings/{name}",
        None,
        None,
        "metadata",
        "SRVB",
        source_search=False,
        collection_template="/sap/bc/adt/businessservices/bindings",
    ),
    AdtPathRegistration(
        "PROG",
        frozenset({"prog", "prog/p", "program", "report"}),
        "/sap/bc/adt/programs/programs/{name}",
        "source/main",
        "source/main",
        "source",
        "PROG",
        collection_template="/sap/bc/adt/programs/programs",
        create_xml_name="program:abapProgram",
        create_xml_namespace='xmlns:program="http://www.sap.com/adt/programs/programs"',
        create_adt_type="PROG/P",
        create_content_type="application/vnd.sap.adt.programs.programs.v2+xml; charset=utf-8",
        create_accept="application/vnd.sap.adt.programs.programs.v2+xml, application/xml, */*",
    ),
    AdtPathRegistration(
        "INCL",
        frozenset({"incl", "progi", "prog_i", "prog/i", "include"}),
        "/sap/bc/adt/programs/includes/{name}",
        "source/main",
        "source/main",
        "source",
        "PROG",
        collection_template="/sap/bc/adt/programs/includes",
    ),
    AdtPathRegistration(
        "FUGR",
        frozenset({"fugr", "fugr/f", "function_group"}),
        "/sap/bc/adt/functions/groups/{name}",
        "source/main",
        "source/main",
        "source",
        "FUGR",
        collection_template="/sap/bc/adt/functions/groups",
        create_xml_name="group:abapFunctionGroup",
        create_xml_namespace='xmlns:group="http://www.sap.com/adt/functions/groups"',
        create_adt_type="FUGR/F",
    ),
    AdtPathRegistration(
        "FUNC",
        frozenset({"func", "fugr/ff", "function_module"}),
        "/sap/bc/adt/functions/groups/{group_name}/fmodules/{function_name}",
        "source/main",
        "source/main",
        "source",
        "FUGR",
        collection_template="/sap/bc/adt/functions/groups/{group_name}/fmodules",
    ),
)

ADT_PATH_REGISTRY_BY_ALIAS = {
    alias: registration for registration in ADT_PATH_REGISTRATIONS for alias in registration.aliases
}
