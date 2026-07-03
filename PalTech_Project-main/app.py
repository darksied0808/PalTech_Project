import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from src.markdown_parser import parse_markdown_spec, _split_bullets, ParsedDatabaseSpec
from src.profiler import GenerationConfig, generate_profiling_questions, infer_rules_and_edge_cases
from src.profiling_types import profiling_type_choices
from src.sql_server import SqlServerConfig, SqlServerWriter, is_query_safe
from src.llm import check_model_available, chat_text

st.set_page_config(
    page_title="Data Profiler",
    page_icon="📊",
    layout="wide",
)

st.title("Data Profiler")
st.caption("Generate data profiling questions from a markdown database spec using Gemini API and save to SQL Server.")

with st.sidebar:
    st.header("Gemini LLM")
    
    # Gemini API Key
    api_key = st.text_input(
        "Gemini API Key",
        value=os.getenv("GOOGLE_API_KEY", ""),
        type="password",
        help="Get your API key from https://ai.google.dev/"
    )
    if api_key:
        os.environ["GOOGLE_API_KEY"] = api_key
    
    # Model selection
    model_options = {
        "Gemini 2.5 Flash": "gemini-2.5-flash",
        "Gemini 2.5 Pro": "gemini-2.5-pro",
        "Gemini 2.0 Flash": "gemini-2.0-flash",
        "Gemini 3.5 Flash": "gemini-3.5-flash",
        "Custom": None,
    }
    
    model_preset = st.selectbox("Model", options=list(model_options.keys()), index=0)
    if model_preset == "Custom":
        model = st.text_input("Model ID", value=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
    else:
        model = model_options[model_preset]
        st.caption(f"Using: {model}")
    
    # Generation parameters
    try:
        default_temp = float(os.getenv("GEMINI_TEMPERATURE", "0.2"))
    except Exception:
        default_temp = 0.2
    temperature = st.slider("Temperature", min_value=0.0, max_value=1.0, value=default_temp, step=0.05)
    
    try:
        default_max = int(os.getenv("GEMINI_MAX_TOKENS", "2048"))
    except Exception:
        default_max = 2048
    max_tokens = st.slider("Max tokens", min_value=64, max_value=50000, value=default_max, step=256)
    
    # Store in environment
    os.environ["GEMINI_MODEL"] = model
    os.environ["GEMINI_TEMPERATURE"] = str(temperature)
    os.environ["GEMINI_MAX_TOKENS"] = str(max_tokens)
    
    if st.button("Check model"):
        if not api_key:
            st.error("Please enter your Gemini API key first.")
        else:
            ok, msg = check_model_available(model)
            if ok:
                st.success(msg)
            else:
                st.error(msg)

    st.divider()
    st.header("SQL Server")
    sql_server = st.text_input("Server", value=os.getenv("SQL_SERVER", "localhost"))
    sql_driver = st.selectbox(
        "ODBC Driver",
        ["ODBC Driver 17 for SQL Server", "ODBC Driver 18 for SQL Server", "SQL Server"],
        index=0,
    )
    auth_mode = st.radio("Authentication", ["Windows", "SQL Login"], horizontal=True)
    sql_username = ""
    sql_password = ""
    if auth_mode == "SQL Login":
        sql_username = st.text_input("Username", value=os.getenv("SQL_USERNAME", ""))
        sql_password = st.text_input("Password", type="password", value=os.getenv("SQL_PASSWORD", ""))

    # Fetch database names dynamically
    db_list = []
    if sql_server:
        temp_cfg = SqlServerConfig(
            server=sql_server,
            database="master",
            driver=sql_driver,
            username=sql_username or None,
            password=sql_password or None,
            table="dbo.DataProfilingQuestions",
        )
        try:
            writer = SqlServerWriter(temp_cfg)
            db_list = writer.list_databases()
        except Exception:
            db_list = []

    if db_list:
        default_db = os.getenv("SQL_DATABASE", "")
        default_idx = 0
        if default_db in db_list:
            default_idx = db_list.index(default_db)
        sql_database = st.selectbox("Database", options=db_list, index=default_idx)
    else:
        sql_database = st.text_input("Database", value=os.getenv("SQL_DATABASE", ""))

    profiling_table = st.text_input("Target table", value=os.getenv("PROFILING_TABLE", "dbo.DataProfilingQuestions"))

    if st.button("Test SQL connection"):
        cfg = SqlServerConfig(
            server=sql_server,
            database=sql_database or "master",
            driver=sql_driver,
            username=sql_username or None,
            password=sql_password or None,
            table=profiling_table,
        )
        ok, msg = SqlServerWriter(cfg).test_connection()
        st.success(msg) if ok else st.error(msg)

# Initialize session state variables if they don't exist
if "db_inferred_rules" not in st.session_state:
    st.session_state.db_inferred_rules = []
if "db_inferred_edge_cases" not in st.session_state:
    st.session_state.db_inferred_edge_cases = []
if "db_schema_markdown" not in st.session_state:
    st.session_state.db_schema_markdown = ""
if "db_schema_samples" not in st.session_state:
    st.session_state.db_schema_samples = []
if "db_tables" not in st.session_state:
    st.session_state.db_tables = []
if "db_columns" not in st.session_state:
    st.session_state.db_columns = []
if "current_spec" not in st.session_state:
    st.session_state.current_spec = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

edited_rules = []
edited_edge_cases = []


tab_generator, tab_assistant = st.tabs(["📋 Profiling Question Generator", "💬 Conversational Assistant"])

with tab_generator:
    col_upload, col_types = st.columns([2, 1])

    with col_upload:
        st.subheader("1. Schema & Rules Source")
        spec_source = st.radio(
            "Select specification source:",
            ["Extract from Live SQL Server Database", "Upload Markdown Specification File"],
            index=0,
            horizontal=True
        )
        
        markdown_content = ""
        db_mode_active = (spec_source == "Extract from Live SQL Server Database")
        
        if db_mode_active:
            st.markdown("### Database Schema Extraction")
            if not sql_database:
                st.warning("Please configure SQL Server and Database in the sidebar.")
            else:
                cfg = SqlServerConfig(
                    server=sql_server,
                    database=sql_database,
                    driver=sql_driver,
                    username=sql_username or None,
                    password=sql_password or None,
                    table=profiling_table,
                )
                writer = SqlServerWriter(cfg)
                try:
                    tables_list = writer.list_tables()
                except Exception as e:
                    st.error(f"Could not fetch tables list: {e}")
                    tables_list = []
                    
                if tables_list:
                    selected_tables = st.multiselect(
                        "Select tables to profile & analyze:",
                        options=tables_list,
                        default=tables_list[:3] if len(tables_list) >= 3 else tables_list
                    )
                    
                    privacy_mode = st.checkbox("Privacy Mode: Exclude actual data rows from LLM context", value=False)
                    
                    analyze_clicked = st.button("Analyze Schema & Sample Data", type="secondary", disabled=not selected_tables)
                    
                    if analyze_clicked:
                        with st.spinner("Connecting and profiling selected tables..."):
                            try:
                                # 1. Fetch schemas and sample rows
                                schema_samples = []
                                for t_name in selected_tables:
                                    sample_data = writer.get_table_schema_and_sample(t_name, exclude_samples=privacy_mode)
                                    schema_samples.append(sample_data)
                                
                                st.session_state.db_schema_samples = schema_samples
                                
                                # 2. Extract unique tables and columns list
                                tables_found = []
                                columns_found = []
                                for item in schema_samples:
                                    tables_found.append(item["table_name"])
                                    for c in item["columns"]:
                                        columns_found.append(c["column_name"])
                                st.session_state.db_tables = tables_found
                                st.session_state.db_columns = columns_found
                                
                                # 3. Generate schema markdown for the context and visual preview
                                schema_parts = []
                                for item in schema_samples:
                                    t_name = item["table_name"]
                                    schema_parts.append(f"### {t_name}")
                                    schema_parts.append("| Column | Type | Nullable | Description |")
                                    schema_parts.append("|--------|------|----------|-------------|")
                                    for c in item["columns"]:
                                        pk_desc = "Primary key" if c["is_primary_key"] else ""
                                        fk_desc = f"FK to {c['referenced_table']}" if c["referenced_table"] else ""
                                        desc = " & ".join([x for x in [pk_desc, fk_desc] if x]) or ""
                                        null_str = "YES" if c["is_nullable"] else "NO"
                                        schema_parts.append(f"| {c['column_name']} | {c['data_type']} | {null_str} | {desc} |")
                                    schema_parts.append("")
                                st.session_state.db_schema_markdown = "\n".join(schema_parts)
                                
                                # 4. Infer rules and edge cases using Gemini API
                                if not api_key:
                                    st.error("Please configure Gemini API key in the sidebar to infer rules.")
                                else:
                                    inferred_rules, inferred_edge_cases = infer_rules_and_edge_cases(
                                        schema_samples=schema_samples,
                                        model=model,
                                        temperature=temperature,
                                        max_tokens=max_tokens
                                    )
                                    st.session_state.db_inferred_rules = inferred_rules
                                    st.session_state.db_inferred_edge_cases = inferred_edge_cases
                                    st.success("Inferred business rules and edge cases from live data successfully!")
                            except Exception as e:
                                st.error(f"Failed to analyze tables: {e}")
                    
                    # Render the editable text areas if we have analyzed schema
                    if st.session_state.db_schema_markdown:
                        with st.expander("Preview Extracted Schema", expanded=False):
                            st.markdown(st.session_state.db_schema_markdown)
                            
                        rules_txt = st.text_area(
                            "Inferred Business Rules (Feel free to edit or add new rules):",
                            value="\n".join(f"- {r}" for r in st.session_state.db_inferred_rules),
                            height=180,
                        )
                        edge_cases_txt = st.text_area(
                            "Inferred & Declared Edge Cases (Feel free to edit or add edge cases):",
                            value="\n".join(f"- {e}" for e in st.session_state.db_inferred_edge_cases),
                            height=180,
                        )
                        
                        # Split bullets back to lists
                        edited_rules = _split_bullets(rules_txt)
                        edited_edge_cases = _split_bullets(edge_cases_txt)
                        st.session_state.current_spec = ParsedDatabaseSpec(
                            raw_content="",
                            schema_sections=[st.session_state.db_schema_markdown],
                            business_rules=edited_rules,
                            edge_cases=edited_edge_cases,
                            tables=list(st.session_state.db_tables),
                            columns=list(st.session_state.db_columns)
                        )
                else:
                    st.info("No tables found in this database.")
        else:
            # Markdown file upload mode
            uploaded = st.file_uploader("Markdown file (.md)", type=["md", "markdown", "txt"])
            sample_path = ROOT / "sample_schema.md"
            use_sample = st.checkbox("Use bundled sample_schema.md", value=uploaded is None)

            if uploaded:
                markdown_content = uploaded.read().decode("utf-8")
            elif use_sample and sample_path.exists():
                markdown_content = sample_path.read_text(encoding="utf-8")

            if markdown_content:
                with st.expander("Preview markdown", expanded=False):
                    st.markdown(markdown_content[:4000] + ("..." if len(markdown_content) > 4000 else ""))
                st.session_state.current_spec = parse_markdown_spec(markdown_content)

    with col_types:
        st.subheader("2. Choose profiling types")
        choices = profiling_type_choices()
        default_types = ["completeness", "validity", "business_rules", "edge_cases"]
        selected_types = st.multiselect(
            "Profiling types",
            options=list(choices.keys()),
            default=[t for t in default_types if t in choices],
            format_func=lambda k: choices[k],
        )
        questions_per_type = st.slider("Questions per type", min_value=1, max_value=10, value=5)

    if "generated_questions" not in st.session_state:
        st.session_state.generated_questions = []

    st.subheader("3. Generate & save")

    btn_col1, btn_col2 = st.columns(2)

    can_generate = False
    if db_mode_active:
        can_generate = bool(st.session_state.db_schema_markdown)
    else:
        can_generate = bool(markdown_content)

    generate_clicked = btn_col1.button("Generate profiling questions", type="primary", disabled=not can_generate or not selected_types)
    save_clicked = btn_col2.button("Save to SQL Server", disabled=not st.session_state.generated_questions)

    if generate_clicked:
        with st.spinner("Generating questions..."):
            if not api_key:
                st.error("Please enter your Gemini API key in the sidebar.")
            else:
                ok, msg = check_model_available(model)
                if not ok:
                    st.error(msg)
                else:
                    if db_mode_active:
                        spec = ParsedDatabaseSpec(
                            raw_content="",
                            schema_sections=[st.session_state.db_schema_markdown],
                            business_rules=edited_rules,
                            edge_cases=edited_edge_cases,
                            tables=list(st.session_state.db_tables),
                            columns=list(st.session_state.db_columns)
                        )
                    else:
                        spec = parse_markdown_spec(markdown_content)

                    config = GenerationConfig(
                        questions_per_type=questions_per_type,
                        model=model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    try:
                        questions = generate_profiling_questions(spec, selected_types, config)
                        st.session_state.generated_questions = questions
                        st.session_state.current_spec = spec
                        st.success(f"Generated {len(questions)} profiling questions.")
                    except Exception as exc:
                        st.error(f"Generation failed: {exc}")

    if st.session_state.generated_questions:
        st.subheader("Generated questions")
        rows = [
            {
                "Type": q.profiling_type,
                "Question": q.question,
                "Table": q.target_table,
                "Column": q.target_column,
                "Priority": q.priority,
                "SQL": q.sql_query,
            }
            for q in st.session_state.generated_questions
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)

        for i, q in enumerate(st.session_state.generated_questions):
            with st.expander(f"{q.profiling_type}: {q.question[:80]}"):
                st.write(q.rationale or "_No rationale provided_")
                st.code(q.sql_query, language="sql")
                
                if st.button("Run Diagnostic Query", key=f"run_diag_{i}"):
                    is_safe, keyword = is_query_safe(q.sql_query)
                    if not is_safe:
                        st.error("⚠️ Security Guard: Query contains modify keywords and was blocked from automatic execution.")
                    else:
                        if not sql_database:
                            st.error("Please configure SQL Server and Database in the sidebar to run the query.")
                        else:
                            cfg = SqlServerConfig(
                                server=sql_server,
                                database=sql_database,
                                driver=sql_driver,
                                username=sql_username or None,
                                password=sql_password or None,
                                table=profiling_table,
                            )
                            writer = SqlServerWriter(cfg)
                            with st.spinner("Running query..."):
                                try:
                                    cols, data = writer.execute_custom_query(q.sql_query)
                                    if cols:
                                        import pandas as pd
                                        df = pd.DataFrame(data, columns=cols)
                                        st.success(f"Query returned {len(df)} rows.")
                                        st.dataframe(df, use_container_width=True)
                                    else:
                                        st.success("Query executed successfully (no rows returned).")
                                except Exception as err:
                                    st.error(f"Query failed: {err}")

    if save_clicked and st.session_state.generated_questions:
        if not sql_database:
            st.error("Set a target database in the sidebar before saving.")
        else:
            cfg = SqlServerConfig(
                server=sql_server,
                database=sql_database,
                driver=sql_driver,
                username=sql_username or None,
                password=sql_password or None,
                table=profiling_table,
            )
            writer = SqlServerWriter(cfg)
            session_id = f"data-profiler-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
            try:
                writer.ensure_table()
                count = writer.insert_questions(st.session_state.generated_questions, source_session=session_id)
                st.success(f"Inserted {count} rows into {profiling_table} (session: {session_id}).")
                st.info("Open SSMS and run: SELECT * FROM " + profiling_table + " ORDER BY Id DESC")
            except Exception as exc:
                st.error(f"Save failed: {exc}")

with tab_assistant:
    st.subheader("💬 Conversational Data Profiling Assistant")
    st.caption("Ask questions about your database schema, business rules, anomalies, or profiling queries.")
    
    if not st.session_state.current_spec:
        st.info("Please load or analyze a database specification in the first tab to start using the assistant.")
    else:
        # We have a spec! Let's display the chatbot.
        
        # 1. Option to select an active profiling question
        selected_q = None
        if st.session_state.generated_questions:
            q_options = ["None (General Schema Context)"] + [f"{i+1}. {q.profiling_type}: {q.question}" for i, q in enumerate(st.session_state.generated_questions)]
            selected_q_idx_str = st.selectbox("Select a profiling question context (optional):", options=q_options, index=0)
            if selected_q_idx_str != "None (General Schema Context)":
                idx = int(selected_q_idx_str.split(".")[0]) - 1
                selected_q = st.session_state.generated_questions[idx]
        
        # 2. Option to input anomaly details or sample row
        anomaly_details = st.text_area(
            "Provide anomaly details or a sample row (optional):",
            placeholder="e.g. Email: 'john..doe@domain', Status: 'active', CountryCode: 'XYZ'",
            help="Providing the actual data that triggered the query allows the assistant to explain exactly which business rules or schema constraints were violated.",
            height=80
        )
        
        # Helper to send prompt to LLM
        def ask_assistant(user_message_text):
            from src.markdown_parser import build_context_for_llm
            spec_context = build_context_for_llm(st.session_state.current_spec, [])
            
            active_q_context = ""
            if selected_q:
                active_q_context = f"""
### Active Profiling Question Context:
- **Type**: {selected_q.profiling_type}
- **Question**: {selected_q.question}
- **SQL Query**:
```sql
{selected_q.sql_query}
```
- **Rationale**: {selected_q.rationale}
- **Target Table**: {selected_q.target_table}
- **Target Column**: {selected_q.target_column}
"""
            
            anomaly_context = ""
            if anomaly_details:
                anomaly_context = f"\n### Anomaly / Sample Row Details:\n{anomaly_details}\n"
                
            system_instruction = """You are a senior data quality engineer and assistant.
You help users analyze their database, understand profiling queries, explain anomalies, and suggest new profiling questions.

Guidelines:
- Explain SQL queries clearly, breaking down joins, filters, and aggregations.
- For anomalies, inspect the schema, business rules, and constraints. Tell the user exactly why the provided anomaly or row is invalid (e.g. which rule it breaks, format mismatch).
- For suggestions, propose new profiling ideas with sample T-SQL queries that use table/column names from the schema.
- Keep responses clean, formatted in beautiful Markdown, and technical but easy to understand."""

            full_user_prompt = f"""Database Schema & Business Rules Spec:
{spec_context}
{active_q_context}
{anomaly_context}
---
User Question: {user_message_text}
"""
            with st.spinner("Assistant is thinking..."):
                try:
                    response_text = chat_text(
                        system_prompt=system_instruction,
                        user_prompt=full_user_prompt,
                        model=model,
                        temperature=temperature,
                        max_tokens=max_tokens
                    )
                    return response_text
                except Exception as e:
                    return f"Error communicating with Gemini API: {e}"

        # 3. Quick action buttons
        st.write("**Quick Actions:**")
        q_col1, q_col2, q_col3, q_col4 = st.columns(4)
        
        quick_query = None
        
        if q_col1.button("Why was this anomaly flagged?", disabled=not selected_q, use_container_width=True, key="btn_why_flagged"):
            quick_query = "Why was this anomaly flagged?"
        if q_col2.button("Explain this SQL.", disabled=not selected_q, use_container_width=True, key="btn_explain_sql"):
            quick_query = "Explain this SQL."
        if q_col3.button("Suggest another profiling question.", use_container_width=True, key="btn_suggest_q"):
            if selected_q and selected_q.target_table:
                quick_query = f"Suggest another profiling question for the table '{selected_q.target_table}'."
            else:
                quick_query = "Suggest another profiling question."
        if q_col4.button("Show similar queries.", disabled=not selected_q, use_container_width=True, key="btn_similar_q"):
            quick_query = "Show similar queries to the active query."

        # Process chat input or quick queries
        chat_input = st.chat_input("Ask a question about the schema, SQL, or anomalies...")
        
        user_msg = quick_query or chat_input
        
        if user_msg:
            st.session_state.chat_history.append({"role": "user", "content": user_msg})
            assistant_resp = ask_assistant(user_msg)
            st.session_state.chat_history.append({"role": "assistant", "content": assistant_resp})
            st.rerun()

        # Render chat history
        st.divider()
        if st.session_state.chat_history:
            if st.button("Clear Chat", key="btn_clear_chat"):
                st.session_state.chat_history = []
                st.rerun()
                
            for msg in st.session_state.chat_history:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])
        else:
            st.info("Ask a question or select a quick action above to start the conversation.")

