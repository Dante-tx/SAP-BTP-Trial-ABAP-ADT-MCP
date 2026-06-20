from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from sap_mcp.errors import SapBackendError, ValidationError


class AdtSyntaxCheckMixin:
    async def syntax_check(
        self,
        source: str,
        object_type: str,
        name: str,
    ) -> dict[str, Any]:
        """Run ABAP syntax check on source code without activating.

        ADT: POST /sap/bc/adt/check

        The request sends the source as plain text with headers identifying the object.
        The response contains structured XML with errors/warnings.
        """
        resolved_name = await self._resolve_repository_object_name(object_type, name)
        object_name = (resolved_name or name).strip().upper()
        if not object_name:
            raise ValidationError("name is required")
        adt_object_type = self._adt_object_type(object_type)
        adt_object_name = self._adt_object_name(object_type, object_name)

        findings: list[dict[str, Any]] = []
        status_code = 200
        mode = "adt_check"
        try:
            response = await self._request(
                "POST",
                "/sap/bc/adt/check",
                content=source.encode("utf-8"),
                headers={
                    "Content-Type": "text/plain; charset=utf-8",
                    "adtObjectType": adt_object_type,
                    "adtObjectName": adt_object_name,
                },
                accept="application/xml, application/*, */*",
            )
            status_code = response.status_code
            findings = self._parse_syntax_check_result(response.text)
        except SapBackendError as error:
            if error.details.get("status_code") != 404:
                raise
            mode = "local_static_fallback"
            findings = self._local_static_syntax_findings(source)
        result = {
            "object_type": adt_object_type,
            "name": adt_object_name,
            "checked": True,
            "findings": findings,
            "counts": self._count_severities(findings),
            "status_code": status_code,
            "mode": mode,
        }
        if object_name != adt_object_name:
            result["resolved_name"] = object_name
        return result

    def _local_static_syntax_findings(self, source: str) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        stack: list[tuple[str, int]] = []
        pairs = {
            "(": ")",
            "[": "]",
            "{": "}",
        }
        closers = {value: key for key, value in pairs.items()}
        cds_context = self._looks_like_cds_source(source)
        for line_number, line in enumerate(source.splitlines(), start=1):
            for column, char in enumerate(line, start=1):
                if char in pairs:
                    stack.append((char, line_number))
                elif char in closers:
                    if not stack or stack[-1][0] != closers[char]:
                        findings.append({
                            "line": line_number,
                            "column": column,
                            "severity": "error",
                            "type": "E",
                            "message": f"Unmatched closing delimiter '{char}'",
                        })
                    else:
                        stack.pop()
            stripped = line.strip()
            if stripped and not stripped.startswith("@") and not stripped.startswith("//"):
                if cds_context and self._is_cds_multiline_declaration(stripped):
                    continue
                if self._looks_like_statement_needing_period(stripped):
                    findings.append({
                        "line": line_number,
                        "column": len(line),
                        "severity": "warning",
                        "type": "W",
                        "message": "Statement may be missing a terminating period",
                    })
        for opener, line_number in stack:
            findings.append({
                "line": line_number,
                "column": 0,
                "severity": "error",
                "type": "E",
                "message": f"Unclosed delimiter '{opener}'",
            })
        return findings

    @staticmethod
    def _looks_like_cds_source(source: str) -> bool:
        lowered = source.lower()
        return "define view" in lowered or "define root view" in lowered or "define view entity" in lowered

    @staticmethod
    def _is_cds_multiline_declaration(stripped: str) -> bool:
        lowered = stripped.lower()
        return lowered.startswith("define ") and " as select from " in lowered

    @staticmethod
    def _looks_like_statement_needing_period(stripped: str) -> bool:
        if stripped.endswith((".", ",", "{", "}", "(", ")")):
            return False
        if stripped.endswith(";") and not stripped.count("'") % 2:
            return False
        first_token = stripped.split(maxsplit=1)[0].lower()
        return first_token in {
            "class", "interface", "method", "data", "types", "select", "update", "insert",
            "delete", "modify", "loop", "read", "if", "elseif", "endif", "endloop", "try",
            "catch", "endtry", "define", "expose", "key",
        }

    def _parse_syntax_check_result(self, text: str) -> list[dict[str, Any]]:
        """Parse syntax check result XML.

        Expected structure:
        <abapCheckResult>
          <item>
            <COL>1</COL>
            <LIN>15</LIN>
            <TYPE>E</TYPE>
            <TEXT>Syntax error message</TEXT>
            <ID>ABAP</ID>
            <NUMBER>001</NUMBER>
            <HAS_FIX>false</HAS_FIX>
          </item>
          ...
        </abapCheckResult>

        TYPE values: E=Error, W=Warning, I=Info
        """
        if not text.strip():
            return []

        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return [{"raw": text.strip()}]

        findings: list[dict[str, Any]] = []
        for item in root.iter():
            tag = item.tag.rsplit("}", 1)[-1]
            if tag.lower() not in ("item", "checkitem", "error", "finding"):
                continue

            finding: dict[str, Any] = {}
            for child in item:
                child_tag = child.tag.rsplit("}", 1)[-1].lower()
                child_text = (child.text or "").strip()

                if child_tag == "lin":
                    finding["line"] = self._safe_int(child_text, 0)
                elif child_tag in ("col", "column"):
                    finding["column"] = self._safe_int(child_text, 0)
                elif child_tag in ("type", "severity"):
                    finding["type"] = child_text
                    finding["severity"] = {"E": "error", "W": "warning", "I": "info", "A": "abort"}.get(
                        child_text.upper(), child_text
                    )
                elif child_tag in ("text", "message", "shorttext"):
                    finding["message"] = child_text
                elif child_tag == "id":
                    finding["id"] = child_text
                elif child_tag in ("number", "code"):
                    finding["code"] = child_text
                elif child_tag == "has_fix":
                    finding["has_fix"] = child_text.lower() == "true"
                elif child_text:
                    finding[child_tag] = child_text

            if finding.get("message") or finding.get("line"):
                findings.append(finding)

        if findings:
            return findings

        # Fallback: try to parse as a generic attributes-only item
        for item in root.iter():
            tag = item.tag.rsplit("}", 1)[-1]
            if tag.lower() in ("item", "checkitem"):
                finding = {self._clean_xml_name(k).lower(): v for k, v in item.attrib.items()}
                if finding:
                    finding.setdefault("message", finding.pop("text", finding.pop("shorttext", "")))
                    finding.setdefault("line", self._safe_int(finding.pop("lin", finding.pop("line", "0")), 0))
                    findings.append(finding)

        return findings

    def _count_severities(self, findings: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {"error": 0, "warning": 0, "info": 0}
        for f in findings:
            sev = (f.get("severity") or f.get("type") or "").lower()
            if sev in ("e", "error"):
                counts["error"] += 1
            elif sev in ("w", "warning"):
                counts["warning"] += 1
            elif sev in ("i", "info"):
                counts["info"] += 1
        return counts

    @staticmethod
    def _safe_int(value: str, default: int = 0) -> int:
        try:
            return int(value)
        except (ValueError, TypeError):
            return default
