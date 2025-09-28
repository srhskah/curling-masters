from app import app, db
import os
with app.app_context():
    print('SQLALCHEMY_DATABASE_URI =', app.config.get('SQLALCHEMY_DATABASE_URI'))
    print('engine url:', db.engine.url)
    print('cwd files:')
    for f in os.listdir('.'):
        print(' -', f)
