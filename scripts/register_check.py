from app import app
import sqlite3, os

with app.test_client() as c:
    r = c.post('/admin-secret/register', data={'username': 'routeadmin', 'password': 'routetest'}, follow_redirects=True)
    print('POST status:', r.status_code)
    print('Response snippet:', r.data.decode()[:200])

DB = os.path.join(os.path.dirname(__file__), 'curling_masters.db')
print('DB path:', DB)
# WAL checkpoint
conn = sqlite3.connect(DB)
cur = conn.cursor()
try:
    cur.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    conn.commit()
    print('checkpoint done')
except Exception as e:
    print('checkpoint error', e)
cur.execute('SELECT * FROM managers')
rows = cur.fetchall()
print('raw rows after route POST + checkpoint:', rows)
conn.close()

# Also print ORM view
from models import Manager
from app import app
with app.app_context():
    print('ORM managers:', [(m.manager_id, m.username) for m in Manager.query.all()])
