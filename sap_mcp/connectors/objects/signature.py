from __future__ import annotations

import re
from typing import Any

from sap_mcp.connectors.core.registry import ADT_PATH_REGISTRY_BY_ALIAS
from sap_mcp.errors import ValidationError

# ── Constants ──────────────────────────────────────────────────────────────────

_SECTION_TO_KIND = {
    "IMPORTING": "importing",
    "EXPORTING": "exporting",
    "CHANGING": "changing",
    "RETURNING": "returning",
    "RAISING": "raising",
    "EXCEPTIONS": "exceptions",
}

# ── Public helpers (shared with tests) ─────────────────────────────────────────


def normalize_abap_source(text: str) -> str:
    """Normalize line endings to \\n."""
    return text.replace("\r\n", "\n")


def remove_abap_comments(source: str) -> str:
    """Remove ABAP line comments (* and ") preserving code structure."""
    lines = source.split("\n")
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        # Full-line * comment — skip unless it's a pseudo-comment
        if stripped.startswith("*") and not stripped.startswith("*#"):
            result.append("")
            continue

        # Hunt for the first " that is not inside a string literal
        out: list[str] = []
        in_string = False
        i = 0
        while i < len(line):
            ch = line[i]
            if ch == "|" and i + 1 < len(line) and line[i + 1] == "|":
                in_string = not in_string
                out.append(ch)
            elif ch == '"' and not in_string:
                break
            else:
                out.append(ch)
            i += 1
        result.append("".join(out).rstrip())
    return "\n".join(result)


def find_method_declaration(source: str, method_name: str) -> dict[str, Any] | None:
    """Locate an ABAP method declaration and return its kind and body text.

    Returns ``None`` when the method is not found.
    """
    upper_source = source.upper()
    escaped = re.escape(method_name.upper())

    pattern = re.compile(
        r"(?P<keyword>CLASS-METHODS|METHODS)\s+" + escaped + r"\b",
    )
    match = pattern.search(upper_source)
    if not match:
        return None

    start = match.start()
    end = _find_declaration_end(source, start)
    if end is None:
        return None

    declaration = source[start:end]
    keyword = match.group("keyword").upper()
    kind = "static" if keyword == "CLASS-METHODS" else "instance"

    body = declaration[match.end() - start:].strip()
    return {"kind": kind, "body": body}


def parse_method_sections(body: str) -> dict[str, Any]:
    """Parse the parameter sections of a method declaration body."""
    result: dict[str, Any] = {
        "importing": [],
        "exporting": [],
        "changing": [],
        "returning": None,
        "exceptions": [],
        "raising": [],
    }

    # Split body into sections on section-keyword boundaries.
    # We walk line-by-line so keywords on their own line trigger a section change.
    lines = body.split("\n")
    current_section: str | None = None
    section_lines: list[str] = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        upper_line = line.upper()

        # Skip PREFERRED PARAMETER — it doesn't carry parameter info
        if upper_line.startswith("PREFERRED PARAMETER"):
            continue

        # Detect section keyword
        keyword = _detect_section_keyword(upper_line)
        if keyword:
            _flush_section(result, current_section, section_lines)
            current_section = _SECTION_TO_KIND[keyword]
            # If there is trailing content on the keyword line, treat it as
            # part of the new section (e.g. "RETURNING VALUE(result) TYPE string")
            rest = line[len(keyword):].strip()
            section_lines = [rest] if rest else []
        else:
            section_lines.append(line)

    _flush_section(result, current_section, section_lines)
    return result


def parse_parameter_line(line: str) -> dict[str, Any] | None:
    """Parse a single ABAP parameter declaration line.

    Returns a dict with keys: *name*, *type*, *optional*, *default*, *pass_by*.
    Returns ``None`` when the line does not look like a parameter declaration.
    """
    raw = line.strip().rstrip(".")
    if not raw:
        return None

    # Extract VALUE(name) wrapper → pass_by = value
    pass_by = "reference"
    value_name: str | None = None
    value_match = re.match(r"VALUE\s*\(\s*([A-Z0-9_]+)\s*\)", raw, re.IGNORECASE)
    if value_match:
        pass_by = "value"
        value_name = value_match.group(1).upper()

    # Strip leading "!" alias marker
    stripped = raw.lstrip("!")
    upper_stripped = stripped.upper()

    # Determine the parameter name
    name: str | None = None
    if value_name:
        name = value_name
    else:
        # The name is the first identifier before TYPE/LIKE
        name_match = re.match(r"([A-Z0-9_]+)", upper_stripped)
        if name_match:
            name = name_match.group(1)

    if not name:
        return None

    # Detect OPTIONAL
    optional = False
    rest = upper_stripped

    # Remove the name part and VALUE() from rest
    if value_match:
        rest = upper_stripped[value_match.end():].strip()
    else:
        name_match = re.match(r"[A-Z0-9_]+\s*", upper_stripped)
        if name_match:
            rest = upper_stripped[name_match.end():].strip()

    # Check for OPTIONAL keyword
    if re.search(r"\bOPTIONAL\b", rest):
        optional = True
        rest = re.sub(r"\bOPTIONAL\b", "", rest).strip()

    # Extract DEFAULT value
    default_value: str | None = None
    default_match = re.search(r"\bDEFAULT\s+(\S+)", rest)
    if default_match:
        default_value = default_match.group(1)
        rest = rest[:default_match.start()].strip()

    # Extract TYPE or LIKE
    raw_type: str = "ANY"
    type_match = re.match(r"(?:TYPE|LIKE)\s+(.+)$", rest, re.IGNORECASE)
    if type_match:
        raw_type = type_match.group(1).strip()

    return {
        "name": name,
        "type": raw_type or "ANY",
        "optional": optional,
        "default": default_value,
        "pass_by": pass_by,
    }


# ── Internal helpers ───────────────────────────────────────────────────────────


def _find_declaration_end(text: str, start: int) -> int | None:
    """Find the position past the period that terminates a method declaration."""
    i = start
    paren_depth = 0
    in_string = False

    while i < len(text):
        ch = text[i]
        if ch == "(" and not in_string:
            paren_depth += 1
        elif ch == ")" and not in_string:
            paren_depth -= 1
        elif ch == "|" and i + 1 < len(text) and text[i + 1] == "|":
            in_string = not in_string
        elif ch == "." and paren_depth == 0 and not in_string:
            return i + 1
        i += 1
    return None


def _detect_section_keyword(upper_line: str) -> str | None:
    """Return the section keyword (e.g. 'IMPORTING') if *upper_line* starts one."""
    # Split by whitespace — the first word is the candidate keyword
    first_word = upper_line.split()[0] if upper_line else ""
    if first_word in _SECTION_TO_KIND:
        return first_word
    # Some declarations put VALUE(...) after IMPORTING on the same line:
    #   IMPORTING VALUE(name) TYPE ...
    for kw in _SECTION_TO_KIND:
        if upper_line.startswith(kw) and not upper_line[len(kw):].strip().startswith("_"):
            rest = upper_line[len(kw):].strip()
            if rest.startswith("VALUE(") or rest.startswith("!"):
                return kw
    return None


def _flush_section(
    result: dict[str, Any],
    section: str | None,
    lines: list[str],
) -> None:
    """Parse accumulated parameter lines into *result* under *section*."""
    if not section or not lines:
        return

    joined = " ".join(lines)
    if section == "returning":
        parsed = parse_parameter_line(joined)
        if parsed:
            result["returning"] = parsed
        return

    if section in ("raising", "exceptions"):
        # RAISING line may have multiple comma-separated entries
        names: list[str] = []
        for line in lines:
            names.extend(
                n.strip().upper()
                for n in line.replace(",", " ").split()
                if n.strip()
            )
        result[section].extend(n for n in names if n)
        return

    # importing / exporting / changing
    for line in lines:
        # A single line may contain multiple comma-separated declarations
        candidates = re.split(r",\s*(?=[!A-Z])", line.strip())
        for candidate in candidates:
            parsed = parse_parameter_line(candidate)
            if parsed:
                result[section].append(parsed)


def _extract_class_source(source: str) -> str | None:
    """Return the class definition source (after the class ... definition line)."""
    match = re.search(
        r"CLASS\s+\w+\s+DEFINITION\b",
        source.upper(),
    )
    if not match:
        return None
    return source[match.start():]


def _extract_parent_class(source: str) -> str | None:
    """Extract the parent class name from a class definition source."""
    match = re.search(
        r"\binheriting\s+from\s+([A-Z0-9_]+)\b",
        source,
        re.IGNORECASE,
    )
    return match.group(1) if match else None


# ── Mixin ──────────────────────────────────────────────────────────────────────


class AdtSignatureMixin:
    """Describe the signature (parameters) of ABAP callable objects.

    Supports:
    - Function modules (FUGR/FF) via FUPARAREF table query
    - Class methods (CLAS/CI)  via source parsing of the definition include
    - Interface methods (INTF/IF) via source parsing of the definition include
    """

    async def describe_signature(
        self,
        object_type: str,
        name: str,
        method_name: str | None = None,
    ) -> dict[str, Any]:
        # Use ADT_PATH_REGISTRY_BY_ALIAS for correct alias→canonical resolution
        # (notably "fugr/ff" → "FUNC") before falling back to _canonical_type.
        lookup = object_type.strip().lower()
        reg = ADT_PATH_REGISTRY_BY_ALIAS.get(lookup)
        canonical = reg.canonical_type if reg else self._canonical_type(object_type)

        if canonical == "FUNC":
            return await self._describe_function_signature(name)

        if canonical in ("CLAS", "INTF"):
            if not method_name:
                raise ValidationError(
                    f"method_name is required for object type {object_type}"
                )
            return await self._describe_method_signature(canonical, name, method_name.upper())

        raise ValidationError(
            f"Unsupported object type '{object_type}'. "
            "Supported: FUGR/FF (function module), "
            "CLAS/CI (class method), INTF/IF (interface method)"
        )

    async def _describe_function_signature(self, name: str) -> dict[str, Any]:
        metadata = await self.function_metadata(name)
        return {
            "object_type": "FUGR/FF",
            "name": metadata["function_name"],
            "method_name": None,
            "parameters": [
                {
                    "name": p["name"],
                    "kind": p["kind"],
                    "type": p["associated_type"] or "ANY",
                    "optional": p["optional"],
                    "default": p["default"] or None,
                }
                for p in metadata["parameters"]
            ],
        }

    async def _describe_method_signature(
        self,
        canonical: str,
        name: str,
        method_name: str,
        visited: set[str] | None = None,
    ) -> dict[str, Any]:
        visited = visited or set()
        upper_name = name.upper()
        if upper_name in visited:
            raise ValidationError(
                f"Circular inheritance detected for {canonical} {name} "
                f"(already visited: {visited})"
            )
        visited.add(upper_name)

        # Read the definitions include to find the method declaration.
        # Gracefully fallback to main source if definitions include is not available
        # (e.g., some system classes don't expose a separate definitions include).
        source = ""
        source_data = None
        try:
            source_data = await self.read_source(
                object_type=canonical,
                name=name,
                scope="include",
                include_type="definitions",
            )
            source = source_data.get("source", "")
        except Exception:
            pass

        if not source:
            # Fallback: try main source directly
            try:
                source_data = await self.read_source(
                    object_type=canonical,
                    name=name,
                    scope="main",
                )
                source = source_data.get("source", "")
            except Exception:
                pass

        if not source:
            raise ValidationError(
                f"Could not read source for {canonical} {name}"
            )

        source_norm = normalize_abap_source(source)
        source_clean = remove_abap_comments(source_norm)

        decl = find_method_declaration(source_clean, method_name)
        if decl is not None:
            params = parse_method_sections(decl["body"])
            display_type = "CLAS/CI" if canonical == "CLAS" else "INTF/IF"
            return {
                "object_type": display_type,
                "name": name,
                "method_name": method_name,
                "kind": decl["kind"],
                "parameters": params,
            }

        # Method not in definitions include — try the main source (for inherited
        # or redefined methods, or classes without separate definitions include)
        try:
            main_data = await self.read_source(
                object_type=canonical,
                name=name,
                scope="main",
            )
        except Exception:  # ADT can raise 404 on scope=main for some classes
            main_data = {"source": ""}

        main_source = main_data.get("source", "")
        if main_source:
            main_norm = normalize_abap_source(main_source)
            main_clean = remove_abap_comments(main_norm)
            decl = find_method_declaration(main_clean, method_name)
            if decl is not None:
                params = parse_method_sections(decl["body"])
                display_type = "CLAS/CI" if canonical == "CLAS" else "INTF/IF"
                return {
                    "object_type": display_type,
                    "name": name,
                    "method_name": method_name,
                    "kind": decl["kind"],
                    "parameters": params,
                }

        # Method not in current class — try parent class
        if canonical == "CLAS":
            parent_source = main_source or source  # whichever has the class header
            parent_norm = normalize_abap_source(parent_source)
            parent_class = _extract_parent_class(parent_norm)
            if parent_class:
                return await self._describe_method_signature(
                    canonical=canonical,
                    name=parent_class,
                    method_name=method_name,
                    visited=visited,
                )

        raise ValidationError(
            f"Method {method_name} not found in {canonical} {name}"
        )
