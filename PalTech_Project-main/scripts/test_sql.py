import sys
from pathlib import Path

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from src.sql_server import SqlServerConfig, SqlServerWriter

cfg = SqlServerConfig.from_env()
print('Connection string:')
print(cfg.connection_string())
print('\nTesting connection...')
writer = SqlServerWriter(cfg)
import pyodbc
import traceback

# Try with a short connection timeout to fail fast
conn_str = cfg.connection_string() + ";Connection Timeout=5"
print('Using connection string with timeout:')
print(conn_str)
try:
	conn = pyodbc.connect(conn_str)
	cur = conn.cursor()
	cur.execute('SELECT 1')
	print('OK: True')
	print('Message: Connected and query succeeded')
	conn.close()
except Exception as exc:
	print('OK: False')
	print('Message: Exception during connect:')
	traceback.print_exc()
