from flask import Flask, request, jsonify, render_template,redirect
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant
from twilio.twiml.voice_response import VoiceResponse, Dial
from twilio.rest import Client
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta
import sendgrid
from sendgrid.helpers.mail import Mail
from datetime import timezone
from flask_socketio import SocketIO, emit



load_dotenv()

account_sid = os.environ['TWILIO_ACCOUNT_SID']
auth_token = os.environ['TWILIO_AUTH_TOKEN']
api_key = os.environ['TWILIO_API_KEY_SID']
api_key_secret = os.environ['TWILIO_API_KEY_SECRET']
twiml_app_sid = os.environ['TWIML_APP_SID']
twilio_number = os.environ['TWILIO_NUMBER']
sendgrid_key = os.environ['SENDGRID_API_KEY']
client = Client(account_sid, auth_token)

app = Flask(__name__, static_url_path='/static')
socketio = SocketIO(app)

inbox_messages = []
voicemails = []
call_logs = []  # Optional for future use
TWILIO_NUMBERS = os.getenv("TWILIO_NUMBERS", twilio_number).split(",")

@app.context_processor
def inject_twilio_numbers():
    return dict(twilio_numbers=TWILIO_NUMBERS)

def send_email_notification(subject, content, to_email):
    try:
        sg = sendgrid.SendGridAPIClient(api_key=sendgrid_key)
        message = Mail(
            from_email='your@email.com',
            to_emails=to_email,
            subject=subject,
            plain_text_content=content
        )
        sg.send(message)
    except Exception as e:
        print("SendGrid Error:", e)

@app.route('/')
def home():
    return redirect('/dashboard')

@app.route('/dashboard')
def dashboard():
    from_filter = request.args.get('from', twilio_number)
    sms_page = int(request.args.get('sms_page', 1))
    call_page = int(request.args.get('call_page', 1))
    per_page = 5

    client = Client(account_sid, auth_token)

    def normalize(n):
        return ''.join(filter(str.isdigit, n))[-10:] if n else ''

    filter_digits = normalize(from_filter)

    # === Fetch SMS Logs ===
    sms_logs = []
    for number in TWILIO_NUMBERS:
        try:
            sms_logs += client.messages.list(to=number.strip(), limit=100)
            sms_logs += client.messages.list(from_=number.strip(), limit=100)
        except Exception as e:
            print(f"Failed to fetch SMS logs for {number}:", e)

    sms_combined = sorted([
        m for m in sms_logs
        if m.date_sent and (
            normalize(m.from_) == filter_digits or normalize(m.to) == filter_digits
        )
    ], key=lambda m: m.date_sent, reverse=True)

    # === Fetch Call Logs ===
    call_logs = []
    for number in TWILIO_NUMBERS:
        try:
            call_logs += client.calls.list(to=number.strip(), limit=100)
            call_logs += client.calls.list(from_=number.strip(), limit=100)
        except Exception as e:
            print(f"Failed to fetch call logs for {number}:", e)

    print("FROM FILTER:", from_filter, "→ Digits:", filter_digits)
    print("Total calls fetched:", len(call_logs))

    for c in call_logs:
        print("  CALL from:", getattr(c, 'from_', ''), "| to:", getattr(c, 'to', ''))

    call_combined = sorted([
        c for c in call_logs
        if c.start_time and (
            normalize(getattr(c, 'from_', '')) == filter_digits or
            normalize(getattr(c, 'to', '')) == filter_digits
        )
    ], key=lambda c: c.start_time, reverse=True)

    print("Filtered calls:", len(call_combined))

    # === Attach recordings
    call_data = []
    for c in call_combined:
        rec_url = None
        try:
            recs = client.recordings.list(call_sid=c.sid)
            if recs:
                rec = recs[0]
                rec_url = f"https://api.twilio.com{rec.uri.replace('.json', '.mp3')}"
        except Exception as e:
            print("Recording fetch error:", e)

        call_data.append({
            'from': getattr(c, 'from_formatted', getattr(c, 'from_', 'Unknown')),
            'to': getattr(c, 'to_formatted', getattr(c, 'to', 'Unknown')),
            'date': c.start_time.strftime('%Y-%m-%d %H:%M:%S') if c.start_time else 'N/A',
            'status': c.status,
            'duration': c.duration or '0',
            'recording_url': rec_url
        })


    sms_paginated = sms_combined[(sms_page - 1) * per_page: sms_page * per_page]
    calls_paginated = call_data[(call_page - 1) * per_page: call_page * per_page]

    return render_template('dashboard.html',
        title='Dashboard',
        sms_page=sms_page,
        call_page=call_page,
        has_more_sms=len(sms_combined) > sms_page * per_page,
        has_more_calls=len(call_data) > call_page * per_page,
        messages=[{
            'from': m.from_,
            'to': m.to,
            'body': m.body,
            'date': m.date_sent.strftime('%Y-%m-%d %H:%M:%S') if m.date_sent else 'N/A'
        } for m in sms_paginated],
        voicemails=[],
        call_logs=calls_paginated
    )



@app.route('/dashboard_check')
def dashboard_check():
    try:
        latest_sms = None
        sms_count = 0
        call_count = 0

        for number in TWILIO_NUMBERS:
            msgs = client.messages.list(to=number.strip(), limit=1)
            sms_count += len(msgs)
            if msgs:
                latest_sms = msgs[0]

            call_count += len(client.calls.list(to=number.strip(), limit=1))

        sms_data = {
            'from': latest_sms.from_,
            'to': latest_sms.to,
            'body': latest_sms.body,
            'date': latest_sms.date_sent.strftime('%Y-%m-%d %H:%M:%S') if latest_sms.date_sent else 'N/A'
        } if latest_sms else None

        return {
            'sms_count': sms_count,
            'call_count': call_count,
            'latest_sms': sms_data
        }

    except Exception as e:
        print("Live check error:", e)
        return {'sms_count': 0, 'call_count': 0, 'latest_sms': None}


@app.route('/token', methods=['GET'])
def get_token():
    identity_number = request.args.get('identity', twilio_number)
    identity = identity_number.replace('+', '').replace(' ', '')
    access_token = AccessToken(account_sid, api_key, api_key_secret, identity=identity)
    voice_grant = VoiceGrant(outgoing_application_sid=twiml_app_sid, incoming_allow=True)
    access_token.add_grant(voice_grant)
    return jsonify({'token': access_token.to_jwt(), 'identity': identity})

@app.route('/send_sms', methods=['POST'])
def send_sms():
    to_number = request.form['to']
    message_body = request.form['message']
    from_number = request.form.get('from', twilio_number)

    if not from_number or from_number == 'null':
        return jsonify({'status': 'error', 'message': 'Missing valid From number'}), 400

    print("Sending SMS from:", from_number)

    client = Client(account_sid, auth_token)
    message = client.messages.create(
        body=message_body,
        from_=from_number,
        to=to_number
    )

    return jsonify({'status': 'sent', 'sid': message.sid})

@app.route('/receive_sms', methods=['POST'])
def receive_sms():
    from_number = request.form['From']
    to_number = request.form['To']
    body = request.form['Body']

    inbox_messages.append({
        'from': from_number,
        'to': to_number,
        'body': body,
        'date': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

    send_email_notification(
        subject="New SMS Received",
        content=f"To: {to_number}\nFrom: {from_number}\n\nMessage: {body}",
        to_email="your@email.com"
    )

    socketio.emit('new_sms', {
        'from': from_number,
        'to': to_number,
        'body': body,
        'date': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

    return ('', 204)

@app.route('/inbox')
def get_inbox():
    from_filter = request.args.get('from')
    if from_filter:
        filtered = [msg for msg in inbox_messages if msg.get('to') == from_filter]
        return jsonify(filtered[-50:])
    return jsonify(inbox_messages[-50:])

@app.route('/call')
def call_page():
    return render_template('call.html', title='Call')

@app.route('/handle_calls', methods=['POST'])
def handle_calls():
    from_number = request.form.get('From')
    to_number = request.form.get('To')

    print("📞 Incoming call from:", from_number, "to:", to_number)

    response = VoiceResponse()

    # Attempt to connect the call (you can customize who gets it)
    dial = Dial(timeout=20, callerId=from_number,answerOnBridge=True)

    # Detect if it's a Twilio Client (browser) or phone number
    if to_number and to_number.startswith('client:'):
        dial.client(to_number.replace('client:', ''))  # e.g. client:john
    else:
        dial.number(to_number or twilio_number)  # fallback to Twilio number

    response.append(dial)
    response.pause(length=2)
    # If unanswered, go to voicemail
    response.say(
        "Hi, you've reached Sandy's Company! We're unable to take your call right now, but your call is important to us. Please leave your name, number, and a brief message after the tone, and we'll get back to you as soon as possible. Thank you, and have a great day!   ",
        voice='Polly.Joanna',
        language='en-US')
    response.record(
        action='/voicemail_saved',
        method='POST',
        maxLength=60,
        playBeep=True,
        timeout=5
    )

    return str(response)



@app.route('/voicemail_saved', methods=['POST'])
def voicemail_saved():
    from_number = request.form.get('From')
    recording_url = request.form.get('RecordingUrl')
    voicemails.append({
        'from': from_number,
        'to': twilio_number,
        'url': f"{recording_url}.mp3",
        'date': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'new': True  # ✅ mark as new
    })
    print("success new voice mail")

    socketio.emit('new_voicemail', {
        'from': from_number,
        'to': twilio_number,
        'url': f"{recording_url}.mp3",
        'date': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'new': True
    })



    send_email_notification(
        subject="\ud83d\udcde New Voicemail",
        content=f"You got a voicemail from {from_number}. Listen here: {recording_url}.mp3",
        to_email="your@email.com"
    )

    return '', 200

@app.route('/voicemails')
def get_voicemails():
    return jsonify(voicemails[-50:])

@app.route('/voicemail_check')
def voicemail_check():
    try:
        new_voicemails = [v for v in voicemails if v.get('new')]
        return jsonify({
            'count': len(new_voicemails),
            'latest': new_voicemails[-1] if new_voicemails else None
        })
    except:
        return jsonify({'count': 0, 'latest': None})


@app.route('/sms')
def sms_page():
    return render_template('sms.html', title='SMS')

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)

