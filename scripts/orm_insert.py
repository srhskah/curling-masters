from app import app, commit_with_retry
from models import Manager
import sqlite3, os
with app.app_context():
    m = Manager(username='manualtest')
    m.set_password('x')
    from db import db
    db.session.add(m)
    commit_with_retry()
    print('ORM count now:', Manager.query.count())

DB = os.path.join(os.path.dirname(__file__), 'curling_masters.db')
conn = sqlite3.connect(DB)
cur = conn.cursor()
cur.execute('SELECT * FROM managers')
print('raw rows after ORM insert:', cur.fetchall())
conn.close()
