from flask import Flask, request, jsonify, render_template
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant
from twilio.twiml.voice_response import VoiceResponse, Dial
from twilio.rest import Client
from dotenv import load_dotenv
import os
from datetime import datetime
import sendgrid
from sendgrid.helpers.mail import Mail

# Load .env variables
load_dotenv()

account_sid = os.environ['TWILIO_ACCOUNT_SID']
auth_token = os.environ['TWILIO_AUTH_TOKEN']
api_key = os.environ['TWILIO_API_KEY_SID']
api_key_secret = os.environ['TWILIO_API_KEY_SECRET']
twiml_app_sid = os.environ['TWIML_APP_SID']
twilio_number = os.environ['TWILIO_NUMBER']
sendgrid_key = os.environ['SENDGRID_API_KEY']

# Flask app
app = Flask(__name__, static_url_path='/static')

# In-memory stores
inbox_messages = []
voicemails = []

# Email utility
def send_email_notification(subject, content, to_email):
    sg = sendgrid.SendGridAPIClient(api_key=sendgrid_key)
    message = Mail(
        from_email='your@email.com',  # Change this
        to_emails=to_email,
        subject=subject,
        plain_text_content=content
    )
    sg.send(message)

# Home (you can customize this or remove)
@app.route('/')
def home():
    return render_template('home.html', title="In browser calls")

@app.route('/call')
def call_page():
    return render_template('call.html', title='Call')


# Token for Twilio Voice SDK
@app.route('/token', methods=['GET'])
def get_token():
    identity = twilio_number
    outgoing_application_sid = twiml_app_sid

    access_token = AccessToken(account_sid, api_key, api_key_secret, identity=identity)
    voice_grant = VoiceGrant(outgoing_application_sid=outgoing_application_sid, incoming_allow=True)
    access_token.add_grant(voice_grant)

    response = jsonify({'token': access_token.to_jwt(), 'identity': identity})
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response

# Send SMS
@app.route('/send_sms', methods=['POST'])
def send_sms():
    to_number = request.form['to']
    message_body = request.form['message']

    client = Client(account_sid, auth_token)
    message = client.messages.create(
        body=message_body,
        from_=twilio_number,
        to=to_number
    )

    return jsonify({'status': 'sent', 'sid': message.sid})

# Receive SMS
@app.route('/receive_sms', methods=['POST'])
def receive_sms():
    from_number = request.form['From']
    body = request.form['Body']

    inbox_messages.append({
        'from': from_number,
        'body': body,
        'date': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

    send_email_notification(
        subject="New SMS Received",
        content=f"From: {from_number}\nMessage: {body}",
        to_email="your@email.com"
    )

    return ('', 204)

# Show inbox
@app.route('/inbox')
def get_inbox():
    return jsonify(inbox_messages[-50:])

# Show voicemail page
@app.route('/voicemail')
def voicemail_page():
    return render_template('voicemail.html')

# Return voicemail list
@app.route('/voicemails')
def get_voicemails():
    return jsonify(voicemails[-50:])

# Save voicemail after recording
@app.route('/voicemail_saved', methods=['POST'])
def voicemail_saved():
    from_number = request.form.get('From')
    recording_url = request.form.get('RecordingUrl')

    voicemails.append({
        'from': from_number,
        'url': f"{recording_url}.mp3",
        'date': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

    send_email_notification(
        subject="📞 New Voicemail Received",
        content=f"You received a voicemail from {from_number}.\nListen here: {recording_url}.mp3",
        to_email="your@email.com"
    )

    return '', 200

# Call handling
@app.route('/handle_calls', methods=['POST'])
def call():
    from_number = request.form.get('From')
    to_number = request.form.get('To')

    response = VoiceResponse()
    dial = Dial(callerId=twilio_number, timeout=20)

    if to_number and to_number != twilio_number:
        dial.number(to_number)
        response.append(dial)
    else:
        response.say("Nobody is available. Please leave a message after the tone.")
        response.record(
            maxLength=30,
            action='/voicemail_saved',
            method='POST',
            playBeep=True
        )

    return str(response)

# Pages
@app.route('/sms')
def sms_page():
    return render_template('sms.html')

# Run the app
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)
