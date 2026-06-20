from __future__ import annotations

import re
from collections.abc import Mapping
from hashlib import sha1
from typing import Any

from sap_mcp.errors import ValidationError


FUNCTION_PARAM_TYPES = {"I": "importing", "E": "exporting", "C": "changing", "T": "tables", "X": "exceptions"}
FUNCTION_MODULE_SELECT = "SELECT PARAMETER, PARAMTYPE, OPTIONAL, DEFAULTVAL, STRUCTURE FROM FUPARAREF WHERE FUNCNAME = '{name}' AND R3STATE = 'A' ORDER BY PARAMTYPE, PPOSITION"
INPUT_PARAM_TYPES = {"I", "C"}
OUTPUT_PARAM_TYPES = {"E", "C", "T"}
CLASS_TEMPLATE = """\
CLASS {class_name} DEFINITION
  PUBLIC
  FINAL
  CREATE PUBLIC.
  PUBLIC SECTION.
    INTERFACES if_oo_adt_classrun.
ENDCLASS.

CLASS {class_name} IMPLEMENTATION.
  METHOD if_oo_adt_classrun~main.
{body}
  ENDMETHOD.
ENDCLASS."""


class FunctionModuleMixin:
    async def function_metadata(self, function_name: str) -> dict[str, Any]:
        name = self._function_name(function_name)
        preview = await self.data_preview("freestyle", FUNCTION_MODULE_SELECT.format(name=name), top=500)
        rows = preview.get("rows", [])
        if not rows:
            raise ValidationError(f"Function module {name} was not found or has no active parameter interface")
        return {"function_name": name, "parameters": [self._parameter_info(row) for row in rows]}

    async def call_function(
        self,
        function_name: str,
        importing: dict[str, Any] | None = None,
        changing: dict[str, Any] | None = None,
        tables: dict[str, list[dict[str, Any]]] | None = None,
        destination: str | None = None,
        commit: bool = False,
    ) -> dict[str, Any]:
        metadata = await self.function_metadata(function_name)
        class_name = self._function_runner_name(metadata["function_name"])
        source = self._function_runner_source(class_name, metadata, importing or {}, changing or {}, tables or {}, destination, commit)
        await self.create_object("CLAS", class_name, "$TMP", f"MCP FM runner {metadata['function_name']}", "Create MCP function runner", source)
        try:
            await self.activate_object("CLAS", class_name, "Activate MCP function runner")
            execution = await self.execute("class", class_name)
        finally:
            await self.delete_object("CLAS", class_name, "Delete MCP function runner")
        parsed_output = self._parse_function_output(str(execution.get("output") or ""))
        return {
            "function_name": metadata["function_name"],
            "called": True,
            "commit_executed": commit,
            "generated_class": class_name,
            "result": parsed_output,
            "execution": execution,
        }

    @staticmethod
    def _function_name(function_name: str) -> str:
        name = function_name.strip().upper()
        if not re.fullmatch(r"[A-Z0-9_/]+", name):
            raise ValidationError("function_name must contain only letters, digits, underscore, or slash")
        return name

    @staticmethod
    def _parameter_info(row: dict[str, Any]) -> dict[str, Any]:
        code = str(row.get("PARAMTYPE") or "").strip().upper()
        return {
            "name": str(row.get("PARAMETER") or "").strip().upper(),
            "kind": FUNCTION_PARAM_TYPES.get(code, code.lower()),
            "kind_code": code,
            "optional": str(row.get("OPTIONAL") or "").strip().upper() == "X",
            "default": str(row.get("DEFAULTVAL") or "").strip(),
            "associated_type": str(row.get("STRUCTURE") or "").strip(),
        }

    def _function_runner_source(
        self,
        class_name: str,
        metadata: dict[str, Any],
        importing: dict[str, Any],
        changing: dict[str, Any],
        tables: dict[str, list[dict[str, Any]]],
        destination: str | None,
        commit: bool,
    ) -> str:
        params = [param for param in metadata["parameters"] if param["kind_code"] in FUNCTION_PARAM_TYPES]
        self._validate_function_inputs(params, importing, changing)
        lines: list[str] = []
        # Declarations
        lines.extend(self._parameter_declaration(param) for param in params if param["kind_code"] in {"I", "E", "C", "T"})
        # Value assignments
        lines.extend(self._parameter_assignments(params, importing, changing, tables))
        # CALL FUNCTION
        lines.extend(self._call_function_lines(metadata["function_name"], params, destination))
        # Capture sy-subrc
        lines.append("DATA lv_subrc TYPE sy-subrc.")
        lines.append("lv_subrc = sy-subrc.")
        # Output via out->write
        lines.extend(self._output_write_lines(params, commit))
        body = "\n".join(f"    {line}" for line in lines)
        return CLASS_TEMPLATE.format(class_name=class_name.lower(), body=body)

    def _validate_function_inputs(
        self,
        params: list[dict[str, Any]],
        importing: dict[str, Any],
        changing: dict[str, Any],
    ) -> None:
        provided = {"I": {k.upper() for k in importing}, "C": {k.upper() for k in changing}}
        missing = [
            p["name"]
            for p in params
            if p["kind_code"] in provided and not p["optional"] and not p["default"] and p["name"] not in provided[p["kind_code"]]
        ]
        if missing:
            raise ValidationError(f"Missing required function parameters: {', '.join(missing)}")

    @staticmethod
    def _parameter_declaration(param: dict[str, Any]) -> str:
        prefix = "lt" if param["kind_code"] == "T" else "lv"
        abap_name = FunctionModuleMixin._abap_identifier(param["name"])
        associated_type = param["associated_type"] or "string"
        if param["kind_code"] == "T":
            return f"DATA {prefix}_{abap_name} TYPE STANDARD TABLE OF {associated_type.lower()}."
        return f"DATA {prefix}_{abap_name} TYPE {associated_type.lower()}."

    def _parameter_assignments(
        self,
        params: list[dict[str, Any]],
        importing: dict[str, Any],
        changing: dict[str, Any],
        tables: dict[str, list[dict[str, Any]]],
    ) -> list[str]:
        values = {"I": {k.upper(): v for k, v in importing.items()}, "C": {k.upper(): v for k, v in changing.items()}}
        table_values = {k.upper(): v for k, v in tables.items()}
        lines: list[str] = []
        for param in params:
            name = param["name"]
            abap_name = self._abap_identifier(name)
            if param["kind_code"] in INPUT_PARAM_TYPES and name in values[param["kind_code"]]:
                lines.extend(self._assign_value(f"lv_{abap_name}", values[param["kind_code"]][name]))
            if param["kind_code"] == "T" and name in table_values:
                lines.extend(self._assign_table(f"lt_{abap_name}", table_values[name]))
        return lines

    def _assign_value(self, target: str, value: Any) -> list[str]:
        if isinstance(value, Mapping):
            return [line for field, item in value.items() for line in self._assign_value(f"{target}-{self._abap_component(field)}", item)]
        if isinstance(value, list):
            raise ValidationError("Use tables for table parameters; scalar IMPORTING/CHANGING parameters cannot be arrays")
        return [f"{target} = {self._abap_literal(value)}."]

    def _assign_table(self, target: str, rows: list[dict[str, Any]]) -> list[str]:
        if not isinstance(rows, list):
            raise ValidationError("TABLES parameters must be arrays of row objects")
        lines: list[str] = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValidationError("TABLES parameter rows must be objects")
            row_fields = " ".join(f"{self._abap_component(field)} = {self._abap_literal(value)}" for field, value in row.items())
            lines.append(f"APPEND VALUE #( {row_fields} ) TO {target}.")
        return lines

    @staticmethod
    def _call_function_lines(function_name: str, params: list[dict[str, Any]], destination: str | None) -> list[str]:
        destination_clause = f" DESTINATION '{FunctionModuleMixin._escape_abap_string(destination)}'" if destination else ""
        lines = [f"CALL FUNCTION '{function_name}'{destination_clause}"]
        groups = (("I", "EXPORTING", "lv"), ("E", "IMPORTING", "lv"), ("C", "CHANGING", "lv"), ("T", "TABLES", "lt"))
        for code, keyword, prefix in groups:
            entries = [p for p in params if p["kind_code"] == code]
            if entries:
                lines.append(f"  {keyword}")
                lines.extend(f"    {p['name']} = {prefix}_{FunctionModuleMixin._abap_identifier(p['name'])}" for p in entries)
        lines.append("  EXCEPTIONS")
        lines.append("    OTHERS = 1.")
        return lines

    @staticmethod
    def _output_write_lines(params: list[dict[str, Any]], commit: bool) -> list[str]:
        lines = [
            "DATA lv_xml TYPE string.",
            "out->write( '---MCP-FUNCTION-RESULT-BEGIN---' ).",
            "out->write( |SY-SUBRC={ lv_subrc }| ).",
        ]
        for param in params:
            if param["kind_code"] not in OUTPUT_PARAM_TYPES:
                continue
            prefix = "lt" if param["kind_code"] == "T" else "lv"
            abap_name = FunctionModuleMixin._abap_identifier(param["name"])
            lines.extend([
                "CLEAR lv_xml.",
                f"CALL TRANSFORMATION id SOURCE data = {prefix}_{abap_name} RESULT XML lv_xml.",
                f"out->write( '---PARAM {param['kind']} {param['name']}---' ).",
                "out->write( lv_xml ).",
            ])
        if commit:
            lines.append("COMMIT WORK AND WAIT.")
            lines.append("out->write( 'COMMIT=EXECUTED' ).")
        lines.append("out->write( '---MCP-FUNCTION-RESULT-END---' ).")
        return lines

    @staticmethod
    def _function_runner_name(function_name: str) -> str:
        safe_name = re.sub(r"[^A-Z0-9]", "_", function_name.upper())
        digest = sha1(function_name.encode("utf-8")).hexdigest()[:8].upper()
        return f"ZCL_FM_MCP_{safe_name[:12]}_{digest}"[:30]

    @staticmethod
    def _parse_function_output(output: str) -> dict[str, Any]:
        result: dict[str, Any] = {"sy_subrc": None, "parameters": {}, "raw_output": output}
        subrc_match = re.search(r"SY-SUBRC=(\d+)", output)
        if subrc_match:
            result["sy_subrc"] = int(subrc_match.group(1))
        matches = list(re.finditer(r"---PARAM (\w+) ([A-Z0-9_]+)---", output))
        for index, match in enumerate(matches):
            start = match.end() + 1  # skip newline after marker
            end = matches[index + 1].start() if index + 1 < len(matches) else max(output.rfind("---MCP-FUNCTION-RESULT-END---"), start)
            xml_text = output[start:end].strip()
            # Collapse newline-joined XML fragments back to single line
            xml_text = re.sub(r"\s+", " ", xml_text).strip()
            result["parameters"][match.group(2)] = {"kind": match.group(1), "xml": xml_text}
        return result

    @staticmethod
    def _abap_identifier(name: str) -> str:
        return re.sub(r"[^a-z0-9_]", "_", name.lower())[:24]

    @staticmethod
    def _abap_component(name: str) -> str:
        component = re.sub(r"[^A-Za-z0-9_]", "_", str(name).strip().upper())
        if not component:
            raise ValidationError("Structure component names cannot be empty")
        return component

    @staticmethod
    def _abap_literal(value: Any) -> str:
        if isinstance(value, bool):
            return "abap_true" if value else "abap_false"
        if isinstance(value, int | float):
            return str(value)
        return f"'{FunctionModuleMixin._escape_abap_string(str(value))}'"

    @staticmethod
    def _escape_abap_string(value: str | None) -> str:
        return (value or "").replace("'", "''")
