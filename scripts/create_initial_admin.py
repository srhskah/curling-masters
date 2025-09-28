from app import app, commit_with_retry
from models import Manager
from db import db

with app.app_context():
    if Manager.query.first():
        print('管理员已存在:')
        for m in Manager.query.all():
            print(' -', m.manager_id, m.username)
    else:
        m = Manager(username='admin')
        m.set_password('admin')
        db.session.add(m)
        commit_with_retry()
        print('已创建初始管理员 admin / admin')
