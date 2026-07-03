from dataclasses import dataclass

from pydantic import BaseModel, Field

from src.markdown_parser import ParsedDatabaseSpec, build_context_for_llm
from src.llm import chat_json
from src.profiling_types import get_profiling_type


class ProfilingQuestion(BaseModel):
    profiling_type: str = Field(description="Profiling category id")
    question: str = Field(description="Human-readable profiling question")
    sql_query: str = Field(description="T-SQL query to answer the question")
    target_table: str = ""
    target_column: str = ""
    priority: str = "medium"
    rationale: str = ""


class ProfilingResult(BaseModel):
    questions: list[ProfilingQuestion]


SYSTEM_PROMPT = """You are a senior data quality engineer specializing in SQL Server data profiling.

Given a database specification (schema, business rules, edge cases), generate actionable data profiling questions.
Each question must include a valid T-SQL query runnable in SQL Server Management Studio (SSMS).

Rules:
- Use only tables and columns present in the specification. If unsure, use plausible names from the spec.
- SQL must be T-SQL compatible (SQL Server).
- Prefer SELECT-only diagnostic queries; avoid INSERT/UPDATE/DELETE.
- Cover the requested profiling types thoroughly.
- Return ONLY valid JSON matching the schema below.

JSON schema:
{
  "questions": [
    {
      "profiling_type": "<type id>",
      "question": "<clear profiling question>",
      "sql_query": "<T-SQL query>",
      "target_table": "<table or empty>",
      "target_column": "<column or empty>",
      "priority": "high|medium|low",
      "rationale": "<why this check matters>"
    }
  ]
}
"""


@dataclass
class GenerationConfig:
    questions_per_type: int = 5
    model: str | None = None
    temperature: float = 0.2
    max_tokens: int | None = None


def generate_profiling_questions(
    spec: ParsedDatabaseSpec,
    selected_type_ids: list[str],
    config: GenerationConfig | None = None,
) -> list[ProfilingQuestion]:
    config = config or GenerationConfig()
    context = build_context_for_llm(spec, selected_type_ids)

    type_details = []
    for type_id in selected_type_ids:
        pt = get_profiling_type(type_id)
        if pt:
            type_details.append(f"- {pt.id}: {pt.label} — {pt.focus}")

    user_prompt = f"""Generate approximately {config.questions_per_type} profiling questions per selected type.

Selected profiling types:
{chr(10).join(type_details)}

Database specification:
{context}

Return a JSON object with key "questions" containing all generated items."""

    raw = chat_json(
        SYSTEM_PROMPT,
        user_prompt,
        model=config.model,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )
    if isinstance(raw, list):
        payload = {"questions": raw}
    else:
        payload = raw

    result = ProfilingResult.model_validate(payload)
    allowed = set(selected_type_ids)
    return [q for q in result.questions if q.profiling_type in allowed or not allowed]


INFERENCE_SYSTEM_PROMPT = """You are a senior data quality and schema analyst.
Your task is to analyze a database's schema metadata (tables, columns, types, keys) and corresponding sample data to infer potential business rules and edge cases/anomalies that are worth profiling.

Return ONLY a valid JSON object matching the schema below:
{
  "business_rules": [
    "A concise business rule statement based on types, keys, and patterns in data"
  ],
  "edge_cases": [
    "A potential edge case or exception scenario to check (e.g. boundary conditions, missing fields, format violations)"
  ]
}
"""

def infer_rules_and_edge_cases(
    schema_samples: list[dict],
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = None,
) -> tuple[list[str], list[str]]:
    import json
    
    formatted_parts = []
    for item in schema_samples:
        tbl_name = item["table_name"]
        cols = item["columns"]
        row_count = item["row_count"]
        samples = item["sample_rows"]
        
        table_desc = [f"Table: {tbl_name} (Total Rows: {row_count})"]
        table_desc.append("Columns:")
        for c in cols:
            pk_str = " (Primary Key)" if c["is_primary_key"] else ""
            fk_str = f" (FK referencing {c['referenced_table']})" if c["referenced_table"] else ""
            null_str = "Nullable" if c["is_nullable"] else "Not Null"
            table_desc.append(f" - {c['column_name']}: {c['data_type']} ({null_str}){pk_str}{fk_str}")
            
        if samples:
            table_desc.append("Sample Data (Up to 5 rows):")
            for row in samples:
                table_desc.append(f"  {json.dumps(row)}")
        else:
            table_desc.append("Sample Data: (No rows)")
            
        formatted_parts.append("\n".join(table_desc))

    formatted_tables = "\n\n".join(formatted_parts)
    
    user_prompt = f"""Analyze the following database tables (schema and sample data):

{formatted_tables}

Infer approximately 5-10 business rules and 5-10 potential edge cases for these tables based on their columns, relationship keys, and the sample values provided.
Return the results in the requested JSON format."""

    raw = chat_json(
        INFERENCE_SYSTEM_PROMPT,
        user_prompt,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    
    business_rules = raw.get("business_rules", []) if isinstance(raw, dict) else []
    edge_cases = raw.get("edge_cases", []) if isinstance(raw, dict) else []
    
    return business_rules, edge_cases
