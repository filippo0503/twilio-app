from sqlalchemy import create_engine, Column, Integer, String, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv
from twilio.rest import Client
import os

load_dotenv()

# === Setup DB ===
Base = declarative_base()
engine = create_engine('sqlite:///instance/twilio.db')
Session = sessionmaker(bind=engine)
session = Session()

# === Twilio credentials ===
account_sid = os.environ['TWILIO_ACCOUNT_SID']
auth_token = os.environ['TWILIO_AUTH_TOKEN']
twilio_number = os.environ['TWILIO_NUMBER']
TWILIO_NUMBERS = os.getenv("TWILIO_NUMBERS", twilio_number).split(",")
client = Client(account_sid, auth_token)

# === Models ===
class SMSMessage(Base):
    __tablename__ = 'sms_message'
    id = Column(Integer, primary_key=True)
    sid = Column(String(64))
    from_number = Column(String(50))
    to_number = Column(String(50))
    body = Column(Text)
    status = Column(String(50))
    direction = Column(String(50))
    date = Column(String(50))

class CallLog(Base):
    __tablename__ = 'call_log'
    id = Column(Integer, primary_key=True)
    sid = Column(String(64))
    from_number = Column(String(50))
    to_number = Column(String(50))
    status = Column(String(50))
    duration = Column(String(10))
    start_time = Column(String(50))
    end_time = Column(String(50))
    direction = Column(String(50))
    price = Column(String(50))
    recording_url = Column(Text)

class Voicemail(Base):
    __tablename__ = 'voicemail'
    id = Column(Integer, primary_key=True)
    sid = Column(String(64))
    from_number = Column(String(50))
    to_number = Column(String(50))
    date = Column(String(50))
    recording_url = Column(Text)

# === Create tables if not exists ===
Base.metadata.create_all(engine)

# === Normalize phone number ===
def normalize_number(num):
    digits = ''.join(filter(str.isdigit, str(num)))
    if not digits:
        return num
    return f"+{digits}" if str(num).startswith('+') else f"+1{digits[-10:]}"


# === Sync SMS ===
print("📩 Syncing SMS messages...")
for number in TWILIO_NUMBERS:
    try:
        messages = client.messages.list(to=number.strip(), limit=100) + \
                   client.messages.list(from_=number.strip(), limit=100)
        for m in messages:
            exists = session.query(SMSMessage).filter_by(sid=m.sid).first()
            if not exists:
                session.add(SMSMessage(
                    sid=m.sid,
                    from_number=normalize_number(m.from_),
                    to_number=normalize_number(m.to),
                    body=m.body,
                    status=m.status,
                    direction=m.direction,
                    date=m.date_sent.strftime('%Y-%m-%d %H:%M:%S') if m.date_sent else None
                ))
    except Exception as e:
        print(f"❌ Error fetching SMS for {number}:", e)


# === Sync Calls ===
print("📞 Syncing Call logs...")
for number in TWILIO_NUMBERS:
    try:
        calls = client.calls.list(to=number.strip(), limit=100) + \
                client.calls.list(from_=number.strip(), limit=100)
        for c in calls:
            exists = session.query(CallLog).filter_by(sid=c.sid).first()
            if not exists:
                recs = client.recordings.list(call_sid=c.sid)
                rec_url = f"https://api.twilio.com{recs[0].uri.replace('.json', '.mp3')}" if recs else None
                session.add(CallLog(
                    sid=c.sid,
                    from_number=normalize_number(getattr(c, 'from_formatted', getattr(c, 'from', ''))),
                    to_number=normalize_number(getattr(c, 'to_formatted', getattr(c, 'to', ''))),
                    status=c.status,
                    duration=c.duration,
                    start_time=c.start_time.strftime('%Y-%m-%d %H:%M:%S') if c.start_time else None,
                    end_time=c.end_time.strftime('%Y-%m-%d %H:%M:%S') if c.end_time else None,
                    direction=c.direction,
                    price=c.price,
                    recording_url=rec_url
                ))
    except Exception as e:
        print(f"❌ Error fetching Calls for {number}:", e)

# === Sync Voicemails ===
print("🔊 Syncing Voicemails...")
voicemail_calls = session.query(CallLog).filter(CallLog.recording_url != None).all()
for call in voicemail_calls:
    exists = session.query(Voicemail).filter_by(sid=call.sid).first()
    if not exists:
        session.add(Voicemail(
            sid=call.sid,
            from_number=call.from_number,
            to_number=call.to_number,
            date=call.start_time,
            recording_url=call.recording_url
        ))

session.commit()
print("✅ Sync complete.")
