from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class SMSMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sid = db.Column(db.String(64))
    from_number = db.Column(db.String(50))
    to_number = db.Column(db.String(50))
    body = db.Column(db.Text)
    status = db.Column(db.String(50))
    direction = db.Column(db.String(50))
    date = db.Column(db.String(50))

class CallLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sid = db.Column(db.String(64))
    from_number = db.Column(db.String(50))
    to_number = db.Column(db.String(50))
    status = db.Column(db.String(50))
    duration = db.Column(db.String(10))
    start_time = db.Column(db.String(50))
    end_time = db.Column(db.String(50))
    direction = db.Column(db.String(50))
    price = db.Column(db.String(50))
    recording_url = db.Column(db.Text)

class Voicemail(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sid = db.Column(db.String(64))
    from_number = db.Column(db.String(50))
    to_number = db.Column(db.String(50))
    date = db.Column(db.String(50))
    recording_url = db.Column(db.Text)
