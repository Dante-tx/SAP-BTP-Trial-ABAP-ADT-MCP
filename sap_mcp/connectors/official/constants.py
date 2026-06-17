from __future__ import annotations

from typing import Any


GENERATOR_ACCEPT = "application/vnd.sap.adt.repository.generator.v1+json, application/json, */*"
GENERATOR_CONTENT_TYPE = "application/vnd.sap.adt.repository.generator.content.v1+json"
GENERATOR_SCHEMA_ACCEPT = "application/vnd.sap.adt.repository.generator.schema.v1+json, application/json, */*"
GENERATOR_CONTENT_ACCEPT = "application/vnd.sap.adt.repository.generator.content.v1+json, application/json, */*"


CREATABLE_OBJECT_TYPES: dict[str, dict[str, Any]] = {
    "PROG/P": {
        "name": "Program",
        "creation_path": "programs/programs",
        "validation_path": "programs/validation",
        "root": "program:abapProgram",
        "namespace": 'xmlns:program="http://www.sap.com/adt/programs/programs"',
        "max_len": 30,
    },
    "CLAS/OC": {
        "name": "Class",
        "creation_path": "oo/classes",
        "validation_path": "oo/validation/objectname",
        "root": "class:abapClass",
        "namespace": 'xmlns:class="http://www.sap.com/adt/oo/classes"',
        "max_len": 30,
    },
    "INTF/OI": {
        "name": "Interface",
        "creation_path": "oo/interfaces",
        "validation_path": "oo/validation/objectname",
        "root": "intf:abapInterface",
        "namespace": 'xmlns:intf="http://www.sap.com/adt/oo/interfaces"',
        "max_len": 30,
    },
    "FUGR/F": {
        "name": "Function Group",
        "creation_path": "functions/groups",
        "validation_path": "functions/validation",
        "root": "group:abapFunctionGroup",
        "namespace": 'xmlns:group="http://www.sap.com/adt/functions/groups"',
        "max_len": 26,
    },
    "FUGR/FF": {
        "name": "Function Module",
        "creation_path": "functions/groups/{parent}/fmodules",
        "validation_path": "functions/validation",
        "root": "fmodule:abapFunctionModule",
        "namespace": 'xmlns:fmodule="http://www.sap.com/adt/functions/fmodules"',
        "max_len": 30,
        "parent_type": "FUGR/F",
    },
    "DDLS/DF": {
        "name": "CDS Data Definition",
        "creation_path": "ddic/ddl/sources",
        "validation_path": "ddic/ddl/validation",
        "root": "ddl:ddlSource",
        "namespace": 'xmlns:ddl="http://www.sap.com/adt/ddic/ddlsources"',
        "max_len": 30,
    },
    "DCLS/DL": {
        "name": "CDS Access Control",
        "creation_path": "acm/dcl/sources",
        "validation_path": "acm/dcl/validation",
        "root": "dcl:dclSource",
        "namespace": 'xmlns:dcl="http://www.sap.com/adt/acm/dclsources"',
        "max_len": 30,
    },
    "DDLX/EX": {
        "name": "CDS Metadata Extension",
        "creation_path": "ddic/ddlx/sources",
        "validation_path": "ddic/ddlx/sources/validation",
        "root": "ddlx:ddlxSource",
        "namespace": 'xmlns:ddlx="http://www.sap.com/adt/ddic/ddlxsources"',
        "max_len": 30,
    },
    "DEVC/K": {
        "name": "Package",
        "creation_path": "packages",
        "validation_path": "packages/validation",
        "root": "pak:package",
        "namespace": 'xmlns:pak="http://www.sap.com/adt/packages"',
        "max_len": 30,
    },
    "TABL/DT": {
        "name": "Table",
        "creation_path": "ddic/tables",
        "validation_path": "ddic/tables/validation",
        "root": "blue:blueSource",
        "namespace": 'xmlns:blue="http://www.sap.com/wbobj/blue"',
        "max_len": 16,
    },
    "TABL/DS": {
        "name": "Structure",
        "creation_path": "ddic/structures",
        "validation_path": "ddic/structures/validation",
        "root": "blue:blueSource",
        "namespace": 'xmlns:blue="http://www.sap.com/wbobj/blue"',
        "max_len": 30,
    },
    "SRVD/SRV": {
        "name": "Service Definition",
        "creation_path": "ddic/srvd/sources",
        "validation_path": "ddic/srvd/sources/validation",
        "root": "srvd:srvdSource",
        "namespace": 'xmlns:srvd="http://www.sap.com/adt/ddic/srvdsources"',
        "extra": 'srvd:srvdSourceType="S"',
        "max_len": 30,
    },
    "SRVB/SVB": {
        "name": "Service Binding",
        "creation_path": "businessservices/bindings",
        "validation_path": "businessservices/bindings/validation",
        "root": "srvb:serviceBinding",
        "namespace": 'xmlns:srvb="http://www.sap.com/adt/ddic/ServiceBindings"',
        "max_len": 26,
    },
    "DTEL/DE": {
        "name": "Data Element",
        "creation_path": "ddic/dataelements",
        "validation_path": "ddic/dataelements/validation",
        "root": "blue:wbobj",
        "namespace": 'xmlns:blue="http://www.sap.com/wbobj/dictionary/dtel"',
        "max_len": 30,
    },
    "DOMA/DD": {
        "name": "Domain",
        "creation_path": "ddic/domains",
        "validation_path": "ddic/domains/validation",
        "root": "domain:domain",
        "namespace": 'xmlns:domain="http://www.sap.com/dictionary/domain"',
        "max_len": 30,
    },
}


CREATABLE_ALIASES = {
    "CLAS": "CLAS/OC",
    "CLASS": "CLAS/OC",
    "INTF": "INTF/OI",
    "INTERFACE": "INTF/OI",
    "PROG": "PROG/P",
    "DDLS": "DDLS/DF",
    "DCLS": "DCLS/DL",
    "DDLX": "DDLX/EX",
    "DEVC": "DEVC/K",
    "PACKAGE": "DEVC/K",
    "TABL": "TABL/DT",
    "TABLE": "TABL/DT",
    "SRVD": "SRVD/SRV",
    "SRVB": "SRVB/SVB",
    "DTEL": "DTEL/DE",
    "DOMA": "DOMA/DD",
}


GENERATOR_ALIASES = {
    "ui-service": "uiservice",
    "x-ui-service": "uiservice",
    "uiservice": "uiservice",
    "webapi-service": "webapiservice",
    "webapiservice": "webapiservice",
}


GENERATOR_DESCRIPTIONS = {
    "ui-service": {
        "title": "OData UI Service",
        "description": (
            "Creates RAP repository objects for a business object and an OData UI service, "
            "including service binding, service definition, behavior definitions, CDS views, "
            "metadata extension, and behavior pool."
        ),
        "referencedObjectTypes": "TABL;BDEF;DDLS",
    },
    "webapi-service": {
        "title": "OData Web API Service",
        "description": (
            "Creates RAP repository objects for a business object and an OData Web API service "
            "without UI-specific metadata annotations."
        ),
        "referencedObjectTypes": "TABL",
    },
    "x-ui-service": {
        "title": "OData UI Service from Scratch",
        "description": (
            "Creates a full RAP UI service from scratch, including persistent and draft tables, "
            "CDS views, behavior definitions, service definition, service binding, and behavior pool."
        ),
        "referencedObjectTypes": "",
    },
}
