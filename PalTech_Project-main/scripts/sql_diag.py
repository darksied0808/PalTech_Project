import sys
from pathlib import Path
import os
import socket
import traceback

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.sql_server import SqlServerConfig
import pyodbc

cfg = SqlServerConfig.from_env()
print('Env values:')
print(' SQL_SERVER=', os.getenv('SQL_SERVER'))
print(' SQL_DATABASE=', os.getenv('SQL_DATABASE'))
print(' SQL_DRIVER=', os.getenv('SQL_DRIVER'))
print(' SQL_USERNAME=', os.getenv('SQL_USERNAME'))
print(' SQL_PASSWORD=', '***' if os.getenv('SQL_PASSWORD') else None)
print(' PROFILING_TABLE=', os.getenv('PROFILING_TABLE'))

print('\nConfig.connection_string (no credentials masked):')
print(cfg.connection_string())

print('\nODBC drivers available:')
try:
    drivers = pyodbc.drivers()
    for d in drivers:
        print(' -', d)
except Exception:
    print('Could not enumerate ODBC drivers:')
    traceback.print_exc()

# Helper to test TCP port
def check_port(host, port=1433, timeout=3):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, None
    except Exception as e:
        return False, str(e)

server = cfg.server
hosts_to_try = []
if server:
    hosts_to_try.append(server)
# add common loopbacks
hosts_to_try += ['localhost', '127.0.0.1']

print('\nChecking TCP connectivity to port 1433:')
for h in dict.fromkeys(hosts_to_try):
    ok, msg = check_port(h, 1433)
    print(f' {h}:', 'open' if ok else f'closed ({msg})')

print('\nTrying ODBC connections with variants (timeout=5s):')
variants = []
base_driver = cfg.driver
# Try trusted connection
variants.append(f"DRIVER={{{base_driver}}};SERVER={server};DATABASE={cfg.database};TrustServerCertificate=yes;Trusted_Connection=yes;Connection Timeout=5")
# Try with explicit port
variants.append(f"DRIVER={{{base_driver}}};SERVER={server},1433;DATABASE={cfg.database};TrustServerCertificate=yes;Trusted_Connection=yes;Connection Timeout=5")
# Try loopback
variants.append(f"DRIVER={{{base_driver}}};SERVER=127.0.0.1,1433;DATABASE={cfg.database};TrustServerCertificate=yes;Trusted_Connection=yes;Connection Timeout=5")
# Try with username/password if provided
if cfg.username:
    variants.append(f"DRIVER={{{base_driver}}};SERVER={server};DATABASE={cfg.database};UID={cfg.username};PWD={cfg.password or ''};TrustServerCertificate=yes;Connection Timeout=5")

for i, cs in enumerate(variants, 1):
    print(f'\nVariant {i}:')
    print(cs)
    try:
        conn = pyodbc.connect(cs)
        cur = conn.cursor()
        cur.execute('SELECT 1')
        print(' -> Connection succeeded and query returned')
        conn.close()
    except Exception:
        print(' -> Connection failed:')
        traceback.print_exc()

print('\nDiagnostic complete.')
