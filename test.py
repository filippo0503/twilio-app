# test_db_query.py
from models import db, CallLog
from flask import Flask

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///twilio.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

with app.app_context():
    results = CallLog.query.all()
    print(f"Total call records: {len(results)}")
    for c in results[:3]:
        print(c.from_number, c.to_number, c.status, c.duration)
