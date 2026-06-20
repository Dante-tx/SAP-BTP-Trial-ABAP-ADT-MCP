from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from typing import Any

from sap_mcp.connectors.core.registry import ADT_BASE_PATH


class AdtQualityMixin:
    async def run_unit_tests(
        self, objects: list[dict[str, str]] | None, packages: list[str] | None,
        include_subpackages: bool, title: str, wait_seconds: int,
    ) -> dict[str, Any]:
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<aunit:run title="{self._xml_escape(title or "MCP ABAP Unit Run")}" context="MCP" '
            'xmlns:aunit="http://www.sap.com/adt/api/aunit">'
            "<aunit:options>"
            '<aunit:measurements type="none"/>'
            '<aunit:scope ownTests="true" foreignTests="true"/>'
            '<aunit:riskLevel harmless="true" dangerous="true" critical="true"/>'
            '<aunit:duration short="true" medium="true" long="true"/>'
            "</aunit:options>"
            f"{self._object_set_xml(objects, packages, include_subpackages)}"
            "</aunit:run>"
        )
        response = await self._request(
            "POST", f"{ADT_BASE_PATH}/api/abapunit/runs",
            content=body.encode("utf-8"),
            headers={"Content-Type": "application/vnd.sap.adt.api.abapunit.run.v1+xml; charset=utf-8"},
            accept="application/vnd.sap.adt.api.abapunit.run-status.v1+xml, application/xml, */*",
        )
        run_uri = response.headers.get("location", "")
        result = {"started": True, "kind": "abap_unit", "run_uri": run_uri, "status_code": response.status_code}
        if wait_seconds > 0 and run_uri:
            result["run"] = await self._wait_for_run_result(
                run_uri, "application/vnd.sap.adt.api.abapunit.run-status.v1+xml, application/xml, */*", wait_seconds)
            result_uri = result["run"].get("result_uri")
            if result_uri:
                result["result"] = await self.get_unit_test_result(result_uri)
        return result

    async def get_unit_test_run(self, run_uri: str) -> dict[str, Any]:
        response = await self._request(
            "GET", self._adt_api_path(run_uri),
            accept="application/vnd.sap.adt.api.abapunit.run-status.v1+xml, application/xml, */*",
        )
        parsed = self._parse_run_status(response.text, "abap_unit")
        return {**parsed, "kind": "abap_unit", "run_uri": self._adt_api_path(run_uri), "status_code": response.status_code, "raw_xml": response.text}

    async def get_unit_test_result(self, result_uri: str) -> dict[str, Any]:
        response = await self._request(
            "GET", self._adt_api_path(result_uri),
            accept="application/vnd.sap.adt.api.junit.run-result.v1+xml, application/xml, */*",
        )
        summary = self._parse_junit_result(response.text)
        return {"kind": "abap_unit", "result_uri": self._adt_api_path(result_uri), "status_code": response.status_code, "summary": summary, "raw_xml": response.text}

    async def run_atc_checks(
        self, objects: list[dict[str, str]] | None, packages: list[str] | None,
        include_subpackages: bool, check_variant: str | None, configuration: str | None, wait_seconds: int,
    ) -> dict[str, Any]:
        attrs = []
        if check_variant:
            attrs.append(f'checkVariant="{self._xml_escape(check_variant)}"')
        if configuration:
            attrs.append(f'configuration="{self._xml_escape(configuration)}"')
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<atc:runparameters xmlns:atc="http://www.sap.com/adt/atc" {" ".join(attrs)}>'
            f"{self._object_set_xml(objects, packages, include_subpackages, namespace='objectset')}"
            "</atc:runparameters>"
        )
        response = await self._request(
            "POST", f"{ADT_BASE_PATH}/api/atc/runs", params={"clientWait": "false"},
            content=body.encode("utf-8"),
            headers={"Content-Type": "application/vnd.sap.atc.run.parameters.v1+xml; charset=utf-8"},
            accept="application/vnd.sap.atc.run.v1+xml, application/xml, */*",
        )
        run_uri = response.headers.get("location", "")
        result = {"started": True, "kind": "atc", "run_uri": run_uri, "status_code": response.status_code}
        if wait_seconds > 0 and run_uri:
            result["run"] = await self._wait_for_run_result(run_uri, "application/vnd.sap.atc.run.v1+xml, application/xml, */*", wait_seconds)
            result_uri = result["run"].get("result_uri")
            if result_uri:
                result["result"] = await self.get_atc_result(result_uri)
        return result

    async def get_atc_run(self, run_uri: str) -> dict[str, Any]:
        response = await self._request(
            "GET", self._adt_api_path(run_uri),
            accept="application/vnd.sap.atc.run.v1+xml, application/xml, */*",
        )
        parsed = self._parse_run_status(response.text, "atc")
        return {**parsed, "kind": "atc", "run_uri": self._adt_api_path(run_uri), "status_code": response.status_code, "raw_xml": response.text}

    async def get_atc_result(self, result_uri: str) -> dict[str, Any]:
        response = await self._request(
            "GET", self._adt_api_path(result_uri),
            accept="application/vnd.sap.atc.checkstyle.v1+xml, application/xml, */*",
        )
        summary = self._parse_checkstyle_result(response.text)
        return {"kind": "atc", "result_uri": self._adt_api_path(result_uri), "status_code": response.status_code, "summary": summary, "raw_xml": response.text}

    async def _wait_for_run_result(self, run_uri: str, accept: str, wait_seconds: int) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + max(1, min(wait_seconds, 300))
        last: dict[str, Any] = {}
        while True:
            response = await self._request("GET", self._adt_api_path(run_uri), accept=accept)
            kind = "abap_unit" if "/abapunit/" in run_uri else "atc"
            last = {**self._parse_run_status(response.text, kind), "kind": kind, "run_uri": self._adt_api_path(run_uri), "status_code": response.status_code, "raw_xml": response.text}
            if last.get("result_uri") or asyncio.get_running_loop().time() >= deadline:
                return last
            await asyncio.sleep(2)

    def _parse_run_status(self, text: str, kind: str) -> dict[str, Any]:
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return {"status": "unknown", "finished": False, "result_uri": None}
        progress, phases, result_uri = None, [], None
        for element in root.iter():
            tag = element.tag.rsplit("}", 1)[-1]
            if tag == "progress":
                progress = {self._clean_xml_name(k): v for k, v in element.attrib.items()}
            elif tag == "phase":
                phases.append({self._clean_xml_name(k): v for k, v in element.attrib.items()})
            elif tag == "link":
                href = element.attrib.get("href", "")
                rel = element.attrib.get("rel", "")
                if "/results/" in href or "result" in rel:
                    result_uri = self._adt_api_path(href)
        status = root.attrib.get("status") or (progress or {}).get("status") or (progress or {}).get("description") or "unknown"
        normalized = status.upper().replace(" ", "_")
        finished = normalized in {"FINISHED", "COMPLETED"} or (bool(phases) and all(p.get("status", "").lower() == "completed" for p in phases))
        return {"status": status, "finished": finished, "result_uri": result_uri, "progress": progress or {}, "phases": phases}

    def _parse_junit_result(self, text: str) -> dict[str, Any]:
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return {"parse_error": True, "tests": 0, "failures": 0, "errors": 0, "skipped": 0, "testcases": []}
        summary = {
            "tests": self._xml_int(root.attrib.get("tests")), "asserts": self._xml_int(root.attrib.get("asserts")),
            "failures": self._xml_int(root.attrib.get("failures")), "errors": self._xml_int(root.attrib.get("errors")),
            "skipped": self._xml_int(root.attrib.get("skipped")), "time": root.attrib.get("time"), "testcases": [],
        }
        cases = []
        for testcase in root.iter():
            if testcase.tag.rsplit("}", 1)[-1] != "testcase":
                continue
            findings = []
            for child in testcase:
                tag = child.tag.rsplit("}", 1)[-1]
                if tag in {"failure", "error", "skipped"}:
                    findings.append({"type": tag, "message": child.attrib.get("message", ""), "text": (child.text or "").strip()})
            if findings:
                cases.append({"classname": testcase.attrib.get("classname", ""), "name": testcase.attrib.get("name", ""), "findings": findings})
        summary["testcases"] = cases[:50]
        return summary

    def _parse_checkstyle_result(self, text: str) -> dict[str, Any]:
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return {"parse_error": True, "files": 0, "issues": 0, "severity_counts": {}, "findings": []}
        severity_counts, findings, file_count = {}, [], 0
        for file_element in root.iter():
            if file_element.tag.rsplit("}", 1)[-1] != "file":
                continue
            file_count += 1
            file_name = file_element.attrib.get("name", "")
            for error in file_element:
                if error.tag.rsplit("}", 1)[-1] != "error":
                    continue
                sev = error.attrib.get("severity", "unknown")
                severity_counts[sev] = severity_counts.get(sev, 0) + 1
                findings.append({"file": file_name, "line": error.attrib.get("line", ""), "severity": sev, "source": error.attrib.get("source", ""), "message": error.attrib.get("message", "")})
        return {"files": file_count, "issues": len(findings), "severity_counts": severity_counts, "findings": findings[:100]}

    def _xml_int(self, value: str | None) -> int:
        try:
            return int(value or 0)
        except ValueError:
            return 0
