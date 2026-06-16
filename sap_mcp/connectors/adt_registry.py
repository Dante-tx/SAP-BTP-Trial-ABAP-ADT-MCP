from __future__ import annotations

from dataclasses import dataclass


ADT_ACCEPT = "application/atom+xml, application/xml, text/plain, */*"


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
    ),
    AdtPathRegistration(
        "FUGR",
        frozenset({"fugr", "fugr/f", "function_group"}),
        "/sap/bc/adt/functions/groups/{name}",
        "source/main",
        None,
        "metadata",
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
