from flask import Flask, request, jsonify, render_template, redirect
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant
from twilio.twiml.voice_response import VoiceResponse, Dial
from datetime import datetime
from dotenv import load_dotenv
import os
from models import db, SMSMessage, CallLog, Voicemail
from twilio.rest import Client



load_dotenv()

account_sid = os.environ['TWILIO_ACCOUNT_SID']
auth_token = os.environ['TWILIO_AUTH_TOKEN']
api_key = os.environ['TWILIO_API_KEY_SID']
api_key_secret = os.environ['TWILIO_API_KEY_SECRET']
twiml_app_sid = os.environ['TWIML_APP_SID']
twilio_number = os.environ['TWILIO_NUMBER']
TWILIO_NUMBERS = os.getenv("TWILIO_NUMBERS", twilio_number).split(",")
client = Client(account_sid, auth_token)

# Flask app config
app = Flask(__name__, static_url_path='/static')
db_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'instance', 'twilio.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
socketio = SocketIO(app, async_mode='eventlet')

@app.context_processor
def inject_twilio_numbers():
    return dict(twilio_numbers=TWILIO_NUMBERS)

@app.route('/')
def home():
    return redirect(f'/dashboard?from={TWILIO_NUMBERS[0]}')

@app.route('/dashboard')
def dashboard():
    from_number = request.args.get('from')
    print("Initial FROM number:", from_number)
    # Ensure default +E.164 format
    if not from_number:
        from_number = TWILIO_NUMBERS[0].strip()
    elif not from_number.startswith('+'):
        from_number = from_number.strip()
        if not from_number.startswith('+'):
            from_number = f"+{from_number}"
    print("Filtered FROM number:", from_number)

    sms_page = int(request.args.get('sms_page', 1))
    call_page = int(request.args.get('call_page', 1))
    per_page = 5

    # === SMS from DB ===
    sms_query = SMSMessage.query.filter(
        (SMSMessage.to_number == from_number) | (SMSMessage.from_number == from_number)
    ).order_by(SMSMessage.id.desc())
    sms_combined = sms_query.all()
    sms_paginated = sms_combined[(sms_page - 1) * per_page: sms_page * per_page]
    # === CALLS from DB ===
    call_query = CallLog.query.filter(
        (CallLog.to_number == from_number) | (CallLog.from_number == from_number)
    ).order_by(CallLog.id.desc())
    print(call_query)
    call_combined = call_query.all()
    calls_paginated = call_combined[(call_page - 1) * per_page: call_page * per_page]

    return render_template('dashboard.html',
        title='Dashboard',
        sms_page=sms_page,
        call_page=call_page,
        selected_number=from_number,
        has_more_sms=len(sms_combined) > sms_page * per_page,
        has_more_calls=len(call_combined) > call_page * per_page,
        messages=[{
            'from': m.from_number,
            'to': m.to_number,
            'body': m.body,
            'date': m.date
        } for m in sms_paginated],
        call_logs=[{
            'from': c.from_number,
            'to': c.to_number,
            'status': c.status,
            'duration': c.duration,
            'recording_url': c.recording_url,
            'date': c.start_time
        } for c in calls_paginated]
    )


@app.route('/token')
def get_token():
    identity_number = request.args.get('identity', twilio_number)
    identity = identity_number.replace('+', '').replace(' ', '')
    access_token = AccessToken(account_sid, api_key, api_key_secret, identity=identity)
    voice_grant = VoiceGrant(outgoing_application_sid=twiml_app_sid, incoming_allow=True)
    access_token.add_grant(voice_grant)
    return jsonify({'token': access_token.to_jwt(), 'identity': identity})

@app.route('/call')
def call_page():
    return render_template('call.html', title='Call')

@app.route('/sms')
def sms_page():
    return render_template('sms.html', title='SMS')

@app.route('/handle_calls', methods=['POST'])
def handle_calls():
    from_number = request.form.get('From')
    to_number = request.form.get('To')

    response = VoiceResponse()
    dial = Dial(timeout=20, callerId=from_number, answerOnBridge=True)

    if to_number and to_number.startswith('client:'):
        dial.client(to_number.replace('client:', ''))
    else:
        dial.number(to_number or twilio_number)

    response.append(dial)
    response.pause(length=2)
    response.say(
        "Hi, you've reached our company. We're unable to take your call right now. "
        "Please leave your name, number, and a brief message after the tone. Thank you.",
        voice='Polly.Joanna',
        language='en-US'
    )
    response.record(
        action='/voicemail_saved',
        method='POST',
        maxLength=60,
        playBeep=True,
        timeout=5
    )
    return str(response)


@app.route('/send_sms', methods=['POST'])
def send_sms():
    to_number = request.form.get('to')
    message_body = request.form.get('message')
    from_number = request.form.get('from', twilio_number)

    if not from_number.startswith('+'):
        from_number = f"+{from_number}"

    try:
        message = client.messages.create(
            body=message_body,
            from_=from_number,
            to=to_number
        )

        # Save to DB
        msg = SMSMessage(
            from_number=from_number,
            to_number=to_number,
            body=message_body,
            date=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        )
        db.session.add(msg)
        db.session.commit()

        return jsonify({'status': 'sent', 'sid': message.sid})

    except Exception as e:
        print("SMS send error:", e)
        return jsonify({'status': 'error', 'message': str(e)}), 500
    
    
@app.route('/receive_sms', methods=['POST'])
def receive_sms():
    from_number = request.form.get('From')
    to_number = request.form.get('To')
    body = request.form.get('Body')

    print(f"📩 Incoming SMS from {from_number} to {to_number}: {body}")

    # Save to database
    new_sms = SMSMessage(
        from_number=from_number,
        to_number=to_number,
        body=body,
        date=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )
    db.session.add(new_sms)
    db.session.commit()

    # Optionally emit live notification
    socketio.emit('new_sms', {
        'from': from_number,
        'to': to_number,
        'body': body,
        'date': new_sms.date
    })

    return ('', 204)

@app.route('/voicemail_saved', methods=['POST'])
def voicemail_saved():
    from_number = request.form.get('From')
    to_number = request.form.get('To')
    call_sid = request.form.get('CallSid')
    recording_url = request.form.get('RecordingUrl')
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Normalize numbers
    def normalize(num):
        if num and not num.startswith('+'):
            return f'+1{num}'
        return num

    from_number = normalize(from_number)
    to_number = normalize(to_number)
    full_recording_url = f"{recording_url}.mp3" if recording_url else None

    print(full_recording_url)

    # Try to fetch call details from Twilio to store final status, duration, etc.
    try:
        call = Client(account_sid, auth_token).calls(call_sid).fetch()
        call_log = CallLog(
            sid=call.sid,
            from_number=from_number,
            to_number=to_number or twilio_number,
            status=call.status,
            duration=call.duration,
            start_time=call.start_time.strftime('%Y-%m-%d %H:%M:%S') if call.start_time else timestamp,
            end_time=call.end_time.strftime('%Y-%m-%d %H:%M:%S') if call.end_time else timestamp,
            direction=call.direction,
            price=call.price,
            recording_url=full_recording_url
        )
        db.session.add(call_log)
    except Exception as e:
        print("⚠️ Could not fetch call from Twilio:", e)

    # Save voicemail
    voicemail = Voicemail(
        sid=call_sid,
        from_number=from_number,
        to_number=to_number or twilio_number,
        date=timestamp,
        recording_url=full_recording_url
    )
    db.session.add(voicemail)
    db.session.commit()

    # Emit to UI
    # Emit call update for live dashboard
    socketio.emit('new_call', {
        'from': from_number,
        'to': to_number,
        'status': call.status,
        'duration': call.duration,
        'recording_url': full_recording_url,
        'date': call.start_time.strftime('%Y-%m-%d %H:%M:%S') if call.start_time else timestamp
    })


    return '', 200


@app.route('/voicemails')
def get_voicemails():
    vms = Voicemail.query.order_by(Voicemail.id.desc()).limit(50).all()
    return jsonify([{
        'from': v.from_number,
        'to': v.to_number,
        'url': v.recording_url,
        'date': v.date
    } for v in vms])

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
