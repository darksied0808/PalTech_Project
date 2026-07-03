from dataclasses import dataclass


@dataclass(frozen=True)
class ProfilingType:
    id: str
    label: str
    description: str
    focus: str


PROFILING_TYPES: list[ProfilingType] = [
    ProfilingType(
        id="completeness",
        label="Completeness",
        description="Null rates, missing values, and required-field coverage",
        focus="Identify columns that should never be null, partial record coverage, and gaps in mandatory fields.",
    ),
    ProfilingType(
        id="uniqueness",
        label="Uniqueness",
        description="Duplicate detection and primary-key integrity",
        focus="Find duplicate keys, composite uniqueness violations, and near-duplicate records.",
    ),
    ProfilingType(
        id="validity",
        label="Validity",
        description="Format, range, and domain conformance",
        focus="Validate data types, allowed value sets, regex patterns, numeric ranges, and date formats.",
    ),
    ProfilingType(
        id="consistency",
        label="Consistency",
        description="Cross-column and cross-table rule alignment",
        focus="Check that related columns agree (e.g. start_date <= end_date) and derived fields match source columns.",
    ),
    ProfilingType(
        id="referential_integrity",
        label="Referential Integrity",
        description="Foreign-key and orphan-record checks",
        focus="Detect orphan records, broken FK relationships, and mismatched lookup values.",
    ),
    ProfilingType(
        id="business_rules",
        label="Business Rules",
        description="Domain-specific logic from the markdown spec",
        focus="Translate documented business rules into concrete validation questions and SQL checks.",
    ),
    ProfilingType(
        id="edge_cases",
        label="Edge Cases",
        description="Boundary conditions and exception scenarios",
        focus="Cover documented edge cases: zero values, negative amounts, future dates, sentinel codes, and rare states.",
    ),
    ProfilingType(
        id="distribution",
        label="Distribution & Statistics",
        description="Cardinality, skew, outliers, and value frequency",
        focus="Profile value distributions, top-N categories, outliers, and unexpected cardinality.",
    ),
    ProfilingType(
        id="timeliness",
        label="Timeliness",
        description="Freshness, staleness, and temporal gaps",
        focus="Check record recency, stale data, gaps in time series, and future-dated records.",
    ),
]


def get_profiling_type(type_id: str) -> ProfilingType | None:
    return next((t for t in PROFILING_TYPES if t.id == type_id), None)


def profiling_type_choices() -> dict[str, str]:
    return {t.id: f"{t.label} — {t.description}" for t in PROFILING_TYPES}
