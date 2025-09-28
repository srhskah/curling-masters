import sqlite3, os, time
DB = os.path.join(os.path.dirname(__file__), 'curling_masters.db')
print('DB:', DB)
for name in [DB, DB+'-wal', DB+'-shm']:
    try:
        st = os.stat(name)
        print(name, 'size', st.st_size, 'mtime', time.ctime(st.st_mtime))
    except FileNotFoundError:
        print(name, 'MISSING')

conn = sqlite3.connect(DB)
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
print('tables:', cur.fetchall())
try:
    cur.execute('PRAGMA table_info(managers)')
    print('managers schema:', cur.fetchall())
except Exception as e:
    print('schema error', e)
try:
    cur.execute('SELECT COUNT(*) FROM managers')
    print('managers count raw:', cur.fetchone())
except Exception as e:
    print('select error', e)
conn.close()
