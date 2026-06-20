from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from sap_mcp.connectors.core.registry import ADT_BASE_PATH, ADT_PATH_REGISTRATIONS
from sap_mcp.errors import AuthorizationError, SapBackendError, ValidationError

# Pattern to find INCLUDE statements in ABAP: INCLUDE zsome_name.
_INCLUDE_STMT_RE = re.compile(r'^\s*INCLUDE\s+(\w[\w/]*\w)\s*\.', re.IGNORECASE | re.MULTILINE)


class AdtActivationMixin:
    async def activate_object(
        self, object_type: str, name: str, reason: str, cascade: bool = False
    ) -> dict[str, Any]:
        resolved_name = await self._resolve_repository_object_name(object_type, name)
        object_name = resolved_name or name
        objects = [{"type": object_type, "name": object_name}]
        if cascade:
            includes = await self._discover_includes(object_type, object_name)
            for incl in includes:
                objects.append({"type": "INCL", "name": incl})
        result = await self.activate_objects(objects, reason)
        obj_results = result.get("object_results", [])
        my_result = obj_results[0] if obj_results else {}
        return {
            "activated": result.get("activated", True),
            "object_type": object_type, "name": object_name.upper(),
            "status_code": result["status_code"],
            "activation_state": my_result.get("state"),
            "activation_state_text": my_result.get("state_text"),
            "messages": my_result.get("messages", []),
            "cascaded_objects": [r for r in obj_results[1:]] if cascade and len(obj_results) > 1 else [],
        }

    async def _discover_includes(self, object_type: str, name: str) -> list[str]:
        """Read source and extract INCLUDE names (works for PROG, FUGR, etc.)."""
        try:
            source_result = await self.read_source(object_type=object_type, name=name, scope="main")
            source = source_result.get("source", "")
            return sorted(set(
                m.strip().upper() for m in _INCLUDE_STMT_RE.findall(source)
            ))
        except (SapBackendError, AttributeError):
            return []

    async def activate_objects(self, objects: list[dict[str, str]], reason: str) -> dict[str, Any]:
        if not self.config.allow_activate:
            raise AuthorizationError("ABAP activation is disabled by configuration")
        if not reason.strip():
            raise ValidationError("Activation reason is required")
        references = []
        for item in objects or []:
            object_type = (item.get("type") or item.get("object_type") or "").strip()
            name = (item.get("name") or "").strip()
            if not object_type or not name:
                raise ValidationError("Each object must contain name and type/object_type")
            resolved_name = await self._resolve_repository_object_name(object_type, name)
            object_name = resolved_name or name
            uri = self._object_path(object_type, object_name)
            await self._assert_object_write_allowed(object_type, object_name)
            adt_type = self._adt_object_type(object_type)
            references.append({
                "object_type": adt_type,
                "type": adt_type,
                "name": self._adt_object_name(object_type, object_name),
                "resolved_name": object_name.upper(),
                "uri": uri,
            })
        if not references:
            raise ValidationError("At least one object is required")
        body = self._object_references_xml(references)
        response = await self._request(
            "POST", f"{ADT_BASE_PATH}/activation", params={"method": "activate"},
            content=body.encode("utf-8"), headers={"Content-Type": "application/xml"},
        )
        object_results, all_activated = self._parse_activation_result(response.text, references)
        return {
            "activated": all_activated, "count": len(references), "objects": references,
            "object_results": object_results,
            "messages": [m for r in object_results for m in r["messages"]],
            "status_code": response.status_code,
        }

    async def activate_uris(self, uris: list[str], reason: str) -> dict[str, Any]:
        objects = []
        for uri in uris:
            ref = self._object_ref_from_any_uri(uri)
            objects.append({"type": ref["type"], "name": ref["name"]})
        return await self.activate_objects(objects, reason)

    def _parse_activation_result(self, xml_text: str, references: list[dict[str, str]]) -> tuple[list[dict[str, Any]], bool]:
        try:
            root = ET.fromstring(xml_text)
        except (ET.ParseError, TypeError):
            return self._activation_fallback_results(references, "Could not parse activation result")

        # Collect all messages from known activation message tags
        messages = self._collect_activation_messages(root)
        error_types = {"A", "E", "X", "ERROR"}

        # Check per-object activation state from atom:entry elements
        # Use local-name matching to be robust against namespace prefix variations
        per_object_states: dict[str, dict[str, Any]] = {}
        for element in root.iter():
            if self._xml_local_name(element.tag) != "entry":
                continue
            entry_title = ""
            for child in element:
                if self._xml_local_name(child.tag) == "title" and child.text:
                    entry_title = child.text.strip().upper()
                if self._xml_local_name(child.tag) == "content":
                    # Content may have nested properties
                    for inner in child.iter():
                        if self._xml_local_name(inner.tag) == "properties":
                            exec_attr = inner.attrib.get("activationExecuted", "")
                            per_object_states.setdefault(entry_title, {})["activation_executed"] = exec_attr
                        if self._xml_local_name(inner.tag) == "message":
                            sev = inner.attrib.get("severity", inner.attrib.get("type", ""))
                            txt = inner.text or ""
                            per_object_states.setdefault(entry_title, {}).setdefault("messages", []).append(
                                {"severity": sev, "text": txt})
            if entry_title and entry_title not in per_object_states:
                # Also check root-level properties elements
                pass

        # Build per-reference results
        object_results = []
        for ref in references:
            ref_name = ref.get("resolved_name", ref["name"]).upper()
            obj_state = per_object_states.get(ref_name, {})

            # Messages related to this object
            related = [
                m for m in messages
                if ref_name in (m.get("objDescr", "") or "").upper()
                or ref_name in (m.get("name", "") or "").upper()
            ]
            if not related and not obj_state.get("messages"):
                related = messages  # only one object — all messages apply

            # Determine activation state
            exec_flag = obj_state.get("activation_executed", "").lower()
            if exec_flag == "false":
                obj_activated = False
                state = "E"
                state_text = "Activation failed"
            elif exec_flag == "true":
                obj_activated = True
                state = "S"
                state_text = "Activated"
            elif any(
                (m.get("severity") or m.get("type") or "").upper() in error_types
                for m in related
            ):
                obj_activated = False
                state = "E"
                state_text = "Activation failed"
            else:
                obj_activated = not any(
                    (m.get("severity") or m.get("type") or "").upper() in error_types
                    for m in related
                )
                state = "S" if obj_activated else "E"
                state_text = "Activated" if obj_activated else "Activation failed"
                if not related and not obj_state:
                    state_text += " (no confirmation — may be false positive)"

            object_results.append({
                "object_type": ref["object_type"], "name": ref["name"],
                "state": state, "state_text": state_text,
                "activated": obj_activated,
                "messages": related,
            })

        all_activated = all(r["activated"] for r in object_results)
        return object_results, all_activated

    def _collect_activation_messages(self, root: ET.Element) -> list[dict[str, Any]]:
        """Collect activation messages from all known XML structures."""
        messages: list[dict[str, Any]] = []
        seen = set()
        for element in root.iter():
            tag = self._xml_local_name(element.tag)
            if tag in {"msg", "message", "error"}:
                msg = self._activation_message(element)
                key = (msg.get("text", ""), msg.get("severity", ""), msg.get("type", ""))
                if key not in seen:
                    seen.add(key)
                    messages.append(msg)
            # Also collect text from properties sub-elements
            if tag == "properties":
                for child in element:
                    child_tag = self._xml_local_name(child.tag)
                    if child_tag in {"messages", "errors"}:
                        for sub in child:
                            sub_msg = self._activation_message(sub)
                            if sub_msg:
                                key = (sub_msg.get("text", ""),)
                                if key not in seen:
                                    seen.add(key)
                                    messages.append(sub_msg)
        return messages

    def _activation_fallback_results(self, references: list[dict[str, str]], state_text: str) -> tuple[list[dict[str, Any]], bool]:
        return [
            {"object_type": r["object_type"], "name": r["name"],
             "state": "UNKNOWN", "state_text": state_text, "activated": False, "messages": []}
            for r in references
        ], False

    def _activation_message(self, element: ET.Element) -> dict[str, str]:
        message = {self._xml_local_name(key): value for key, value in element.attrib.items()}
        text_parts = []
        if element.text and element.text.strip():
            text_parts.append(element.text.strip())
        for child in element.iter():
            if child is not element and child.text and child.text.strip():
                text_parts.append(child.text.strip())
        if text_parts:
            message["text"] = " ".join(text_parts)
        hint = self._activation_message_hint(message.get("text", ""))
        if hint:
            message["hint"] = hint
        return message

    def _activation_attr(self, element: ET.Element, name: str) -> str:
        return next((v for k, v in element.attrib.items() if self._xml_local_name(k) == name), "")

    def _activation_message_hint(self, text: str) -> str | None:
        normalized = text.casefold()
        if "reported was already declared" in normalized or "failed was already declared" in normalized:
            return "In RAP handler methods, REPORTED and FAILED are framework context identifiers; do not redeclare them as local DATA variables."
        if "statement before modify" in normalized and "period missing" in normalized:
            return "The parser may report a missing period for unsupported strict-mode EML syntax. Check the MODIFY statement shape before only adding punctuation."
        if "field @lt_items is unknown" in normalized or "field @lt_" in normalized:
            return "In EML UPDATE/MODIFY payload clauses, host-variable @ prefixes are often not used the same way as ABAP SQL."
        return None
