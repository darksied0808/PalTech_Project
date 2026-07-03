import os
import re
from contextlib import contextmanager
from dataclasses import dataclass

import pyodbc

from src.profiler import ProfilingQuestion


def _qualified_name(schema: str, table: str) -> str:
    return f"[{schema}].[{table}]"


def build_create_table_sql(schema: str, table: str) -> str:
    qualified = _qualified_name(schema, table)
    return f"""
IF NOT EXISTS (
    SELECT 1 FROM sys.tables t
    JOIN sys.schemas s ON t.schema_id = s.schema_id
    WHERE s.name = '{schema}' AND t.name = '{table}'
)
BEGIN
    CREATE TABLE {qualified} (
        Id INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        ProfilingType NVARCHAR(100) NOT NULL,
        Question NVARCHAR(MAX) NOT NULL,
        SqlQuery NVARCHAR(MAX) NOT NULL,
        TargetTable NVARCHAR(255) NULL,
        TargetColumn NVARCHAR(255) NULL,
        Priority NVARCHAR(50) NOT NULL DEFAULT 'medium',
        Rationale NVARCHAR(MAX) NULL,
        SourceSession NVARCHAR(255) NULL,
        CreatedAt DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
"""


@dataclass
class SqlServerConfig:
    server: str
    database: str
    driver: str = "ODBC Driver 17 for SQL Server"
    username: str | None = None
    password: str | None = None
    table: str = "dbo.DataProfilingQuestions"

    @classmethod
    def from_env(cls) -> "SqlServerConfig":
        return cls(
            server=os.getenv("SQL_SERVER", "localhost"),
            database=os.getenv("SQL_DATABASE", "master"),
            driver=os.getenv("SQL_DRIVER", "ODBC Driver 17 for SQL Server"),
            username=os.getenv("SQL_USERNAME") or None,
            password=os.getenv("SQL_PASSWORD") or None,
            table=os.getenv("PROFILING_TABLE", "dbo.DataProfilingQuestions"),
        )

    def connection_string(self) -> str:
        parts = [
            f"DRIVER={{{self.driver}}}",
            f"SERVER={self.server}",
            f"DATABASE={self.database}",
            "TrustServerCertificate=yes",
        ]
        if self.username:
            parts.append(f"UID={self.username}")
            parts.append(f"PWD={self.password or ''}")
        else:
            parts.append("Trusted_Connection=yes")
        return ";".join(parts)


def parse_table_name(qualified: str) -> tuple[str, str]:
    if "." in qualified:
        schema, table = qualified.split(".", 1)
        schema, table = schema.strip("[]"), table.strip("[]")
    else:
        schema, table = "dbo", qualified.strip("[]")
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", schema):
        raise ValueError(f"Invalid schema name: {schema}")
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", table):
        raise ValueError(f"Invalid table name: {table}")
    return schema, table


class SqlServerWriter:
    def __init__(self, config: SqlServerConfig):
        self.config = config
        self.schema, self.table = parse_table_name(config.table)

    @contextmanager
    def connect(self):
        conn = pyodbc.connect(self.config.connection_string(), autocommit=False)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def ensure_table(self) -> None:
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(build_create_table_sql(self.schema, self.table))

    def insert_questions(
        self,
        questions: list[ProfilingQuestion],
        source_session: str = "data-profiler",
    ) -> int:
        if not questions:
            return 0

        qualified = f"[{self.schema}].[{self.table}]"
        insert_sql = f"""
            INSERT INTO {qualified}
                (ProfilingType, Question, SqlQuery, TargetTable, TargetColumn, Priority, Rationale, SourceSession)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """

        with self.connect() as conn:
            cursor = conn.cursor()
            rows = [
                (
                    q.profiling_type,
                    q.question,
                    q.sql_query,
                    q.target_table or None,
                    q.target_column or None,
                    q.priority,
                    q.rationale or None,
                    source_session,
                )
                for q in questions
            ]
            cursor.fast_executemany = True
            cursor.executemany(insert_sql, rows)
            return len(rows)

    def test_connection(self) -> tuple[bool, str]:
        try:
            with self.connect() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.fetchone()
            return True, "Connected successfully"
        except Exception as exc:
            return False, str(exc)

    def list_databases(self) -> list[str]:
        import copy
        cfg_master = copy.copy(self.config)
        cfg_master.database = "master"
        conn = pyodbc.connect(cfg_master.connection_string())
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sys.databases WHERE name NOT IN ('master', 'tempdb', 'model', 'msdb') ORDER BY name")
            return [row[0] for row in cursor.fetchall()]
        finally:
            conn.close()

    def list_tables(self) -> list[str]:
        conn = pyodbc.connect(self.config.connection_string())
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.name + '.' + t.name AS table_name
                FROM sys.tables t
                JOIN sys.schemas s ON t.schema_id = s.schema_id
                WHERE t.is_ms_shipped = 0 AND t.name != 'sysdiagrams'
                ORDER BY s.name, t.name
            """)
            return [row[0] for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_table_schema_and_sample(self, table_name: str) -> dict:
        schema, table = parse_table_name(table_name)
        
        conn = pyodbc.connect(self.config.connection_string())
        try:
            cursor = conn.cursor()
            
            # Fetch columns metadata
            cursor.execute("""
                SELECT 
                    c.name AS column_name,
                    ty.name AS data_type,
                    c.is_nullable,
                    ISNULL((
                        SELECT 1 
                        FROM sys.index_columns ic
                        JOIN sys.indexes i ON ic.object_id = i.object_id AND ic.index_id = i.index_id
                        WHERE i.is_primary_key = 1 AND ic.object_id = t.object_id AND ic.column_id = c.column_id
                    ), 0) AS is_primary_key,
                    ISNULL((
                        SELECT TOP 1 rt.name
                        FROM sys.foreign_key_columns fkc
                        JOIN sys.tables rt ON fkc.referenced_object_id = rt.object_id
                        WHERE fkc.parent_object_id = t.object_id AND fkc.parent_column_id = c.column_id
                    ), '') AS referenced_table
                FROM sys.tables t
                JOIN sys.schemas s ON t.schema_id = s.schema_id
                JOIN sys.columns c ON t.object_id = c.object_id
                JOIN sys.types ty ON c.user_type_id = ty.user_type_id
                WHERE t.name = ? AND s.name = ?
                ORDER BY c.column_id
            """, (table, schema))
            
            columns = []
            for row in cursor.fetchall():
                columns.append({
                    "column_name": row[0],
                    "data_type": row[1],
                    "is_nullable": bool(row[2]),
                    "is_primary_key": bool(row[3]),
                    "referenced_table": row[4]
                })
            
            # Fetch row count
            cursor.execute(f"SELECT COUNT(*) FROM [{schema}].[{table}]")
            row_count = cursor.fetchone()[0]
            
            # Fetch sample rows (top 5) using explicit columns to handle spatial/binary types
            select_cols = []
            for c in columns:
                c_name = c["column_name"]
                c_type = c["data_type"].lower()
                if c_type in ("geography", "geometry", "hierarchyid"):
                    select_cols.append(f"[{c_name}].ToString() AS [{c_name}]")
                elif c_type in ("image", "varbinary", "binary"):
                    select_cols.append(f"'<binary>' AS [{c_name}]")
                elif c_type == "xml":
                    select_cols.append(f"CAST([{c_name}] AS NVARCHAR(MAX)) AS [{c_name}]")
                else:
                    select_cols.append(f"[{c_name}]")
            
            select_query = f"SELECT TOP 5 {', '.join(select_cols)} FROM [{schema}].[{table}]"
            cursor.execute(select_query)
            col_names = [col_desc[0] for col_desc in cursor.description]
            sample_rows = []
            import decimal
            from datetime import datetime, date
            
            for row in cursor.fetchall():
                row_dict = {}
                for col_idx, col_name in enumerate(col_names):
                    val = row[col_idx]
                    if val is None:
                        row_dict[col_name] = None
                    elif isinstance(val, (int, float, str, bool)):
                        row_dict[col_name] = val
                    elif isinstance(val, (datetime, date)):
                        row_dict[col_name] = val.isoformat()
                    elif isinstance(val, decimal.Decimal):
                        row_dict[col_name] = float(val)
                    else:
                        row_dict[col_name] = str(val)
                sample_rows.append(row_dict)
                
            return {
                "table_name": table_name,
                "columns": columns,
                "row_count": row_count,
                "sample_rows": sample_rows
            }
            
        finally:
            conn.close()

    def execute_query(self, query: str, limit: int = 100) -> tuple[list[dict], list[str] | None, str | None]:
        import decimal
        from datetime import datetime, date
        
        conn = None
        try:
            conn = pyodbc.connect(self.config.connection_string())
            cursor = conn.cursor()
            cursor.execute(query)
            
            if cursor.description is None:
                return [], None, "Query executed successfully, but returned no rows."
                
            col_names = [col_desc[0] for col_desc in cursor.description]
            rows = cursor.fetchmany(limit)
            
            results = []
            for row in rows:
                row_dict = {}
                for idx, col_name in enumerate(col_names):
                    val = row[idx]
                    if val is None:
                        row_dict[col_name] = None
                    elif isinstance(val, (int, float, str, bool)):
                        row_dict[col_name] = val
                    elif isinstance(val, (datetime, date)):
                        row_dict[col_name] = val.isoformat()
                    elif isinstance(val, decimal.Decimal):
                        row_dict[col_name] = float(val)
                    else:
                        row_dict[col_name] = str(val)
                results.append(row_dict)
                
            return results, col_names, None
        except Exception as e:
            return [], None, str(e)
        finally:
            if conn:
                conn.close()
