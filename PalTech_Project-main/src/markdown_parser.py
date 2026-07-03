import re
from dataclasses import dataclass, field


@dataclass
class ParsedDatabaseSpec:
    raw_content: str
    schema_sections: list[str] = field(default_factory=list)
    business_rules: list[str] = field(default_factory=list)
    edge_cases: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)


SECTION_ALIASES = {
    "schema": ("schema", "database schema", "table schema", "tables", "data model", "erd"),
    "business_rules": (
        "business rules",
        "business rule",
        "rules",
        "constraints",
        "validation rules",
    ),
    "edge_cases": ("edge cases", "edge case", "exceptions", "boundary conditions", "corner cases"),
}


def _normalize_heading(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", text.lower()).strip()


def _classify_heading(heading: str) -> str | None:
    normalized = _normalize_heading(heading)
    for section, aliases in SECTION_ALIASES.items():
        if any(alias in normalized or normalized in alias for alias in aliases):
            return section
    return None


def _extract_tables_and_columns(content: str) -> tuple[list[str], list[str]]:
    tables: set[str] = set()
    columns: set[str] = set()

    for match in re.finditer(r"\b(?:CREATE\s+TABLE|FROM|JOIN|INTO|UPDATE)\s+([\w\[\]\.]+)", content, re.I):
        name = match.group(1).strip("[]")
        if "." in name:
            tables.add(name.split(".")[-1])
        else:
            tables.add(name)

    for match in re.finditer(r"\|\s*(\w+)\s*\|", content):
        col = match.group(1)
        if col.lower() not in {"column", "field", "name", "type", "description", "nullable", "key"}:
            columns.add(col)

    for match in re.finditer(r"\b(\w+)\s+(?:INT|BIGINT|VARCHAR|NVARCHAR|DATE|DATETIME|DECIMAL|FLOAT|BIT|CHAR)\b", content, re.I):
        columns.add(match.group(1))

    return sorted(tables), sorted(columns)


def parse_markdown_spec(content: str) -> ParsedDatabaseSpec:
    spec = ParsedDatabaseSpec(raw_content=content)
    spec.tables, spec.columns = _extract_tables_and_columns(content)

    lines = content.splitlines()
    current_section: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer, current_section
        if not buffer or not current_section:
            buffer = []
            return
        text = "\n".join(buffer).strip()
        if current_section == "schema":
            spec.schema_sections.append(text)
        elif current_section == "business_rules":
            spec.business_rules.extend(_split_bullets(text))
        elif current_section == "edge_cases":
            spec.edge_cases.extend(_split_bullets(text))
        buffer = []

    for line in lines:
        heading_match = re.match(r"^#{1,3}\s+(.+)$", line.strip())
        if heading_match:
            flush()
            current_section = _classify_heading(heading_match.group(1))
            continue
        if current_section:
            buffer.append(line)

    flush()

    if not spec.schema_sections and not spec.business_rules and not spec.edge_cases:
        spec.schema_sections.append(content)

    return spec


def _split_bullets(text: str) -> list[str]:
    items: list[str] = []
    for line in text.splitlines():
        cleaned = re.sub(r"^[\-\*\d+\.]+\s*", "", line.strip())
        if cleaned:
            items.append(cleaned)
    return items


def build_context_for_llm(spec: ParsedDatabaseSpec, selected_type_ids: list[str]) -> str:
    from src.profiling_types import get_profiling_type

    parts = ["# Database specification summary\n"]

    if spec.tables:
        parts.append("## Known tables\n" + ", ".join(spec.tables))
    if spec.columns:
        parts.append("## Known columns\n" + ", ".join(spec.columns[:80]))

    if spec.schema_sections:
        parts.append("## Schema\n" + "\n\n".join(spec.schema_sections))

    if spec.business_rules:
        parts.append("## Business rules\n" + "\n".join(f"- {r}" for r in spec.business_rules))

    if spec.edge_cases:
        parts.append("## Edge cases\n" + "\n".join(f"- {e}" for e in spec.edge_cases))

    if selected_type_ids:
        parts.append("## Selected profiling focus\n")
        for type_id in selected_type_ids:
            pt = get_profiling_type(type_id)
            if pt:
                parts.append(f"- **{pt.label}**: {pt.focus}")

    return "\n\n".join(parts)
