import sys
def log(*args, **kwargs):
    kwargs['flush'] = True
    print(*args, **kwargs)
"""
Viora HD WhatsApp Bot Server
============================
Handles:
1. Meta WhatsApp Webhook (verification and activation messages).
2. Automatic registration: When user sends 'Activation Code: <KEY>',
   records KEY -> phone number for 24 hours and replies on WhatsApp.
3. POST /upload endpoint: Receives converted HD video from Viora app,
   uploads to Meta WhatsApp Cloud API, and sends it to the user.
"""

import os
import json
import time
import re
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ==========================================
# META WHATSAPP CLOUD API CONFIGURATION
# ==========================================
ACCESS_TOKEN = os.environ.get(
    "META_ACCESS_TOKEN",
    "EAAXNjPMdkMIBSjm7i8HsAUMCaC17YAPRp4OrEQZAhwIe3d9pwHIsgPKwOIFZB5eg8fz4P1yJU8mtT8RIy8JdZChZBIq0CscY5PlZA04IBt9WmF97Ud6sfoVGUQxXAZBmvikepqo2q5yBtOh66xA1JgfDdxBL5Ihxbvsoa4djqMLXFp5D447n7OSqiqsbmGnAZDZD"
)
PHONE_NUMBER_ID = os.environ.get("META_PHONE_NUMBER_ID", "1282282738312539")
VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN", "viora_secret_verify_token_2026")

DB_FILE = "users_db.json"
WINDOW_24H_SECONDS = 24 * 3600

def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_db(db):
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=2)

def send_whatsapp_text(recipient_phone, text):
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient_phone,
        "type": "text",
        "text": {"body": text}
    }
    res = requests.post(url, headers=headers, json=payload, timeout=15)
    return res.status_code, res.text

def upload_and_send_video(recipient_phone, video_path, caption=""):
    media_url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/media"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    log(f"[UPLOAD STEP 1] Uploading media to {media_url}...")
    with open(video_path, "rb") as f:
        files = {
            "file": (os.path.basename(video_path), f, "video/mp4")
        }
        data = {
            "messaging_product": "whatsapp",
            "type": "video/mp4"
        }
        res_upload = requests.post(media_url, headers=headers, files=files, data=data, timeout=60)
    
    log(f"[UPLOAD STEP 1 RESULT] Status: {res_upload.status_code}, Body: {res_upload.text}")
    if res_upload.status_code not in (200, 201):
        raise RuntimeError(f"Meta Media Upload failed: {res_upload.text}")
    
    media_id = res_upload.json().get("id")
    log(f"[UPLOAD STEP 2] Sending media_id {media_id} to recipient {recipient_phone}...")

    msg_url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    msg_headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    msg_payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient_phone,
        "type": "video",
        "video": {
            "id": media_id,
            "caption": caption if caption else "Your HD video is ready. Tap Forward and choose My Status to post."
        }
    }
    res_send = requests.post(msg_url, headers=msg_headers, json=msg_payload, timeout=20)
    log(f"[UPLOAD STEP 2 RESULT] Status: {res_send.status_code}, Body: {res_send.text}")
    if res_send.status_code not in (200, 201):
        raise RuntimeError(f"Meta Send Video failed: {res_send.text}")
    
    return res_send.json()

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "service": "Viora HD WhatsApp Bot",
        "status": "online",
        "phone_number_id": PHONE_NUMBER_ID
    })

@app.route("/status", methods=["GET"])
def server_status():
    db = load_db()
    return jsonify({
        "status": "online",
        "active_users": len(db),
        "phone_number_id": PHONE_NUMBER_ID
    })

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        log("[WEBHOOK] Verified successfully by Meta")
        return challenge, 200
    log("[WEBHOOK] Verification failed. Token mismatch.")
    return "Forbidden", 403

@app.route("/webhook", methods=["POST"])
def receive_webhook():
    data = request.get_json(silent=True) or {}
    log("[WEBHOOK EVENT RAW]", json.dumps(data))

    try:
        entries = data.get("entry", [])
        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                statuses = value.get("statuses", [])
                for st in statuses:
                    log(f"[MESSAGE STATUS] ID: {st.get('id')} | Status: {st.get('status')} | Recipient: {st.get('recipient_id')} | Errors: {st.get('errors')}")

                messages = value.get("messages", [])
                for msg in messages:
                    sender = msg.get("from")
                    msg_type = msg.get("type")
                    
                    if msg_type == "text":
                        body = msg.get("text", {}).get("body", "").strip()
                        log(f"[INCOMING MSG] From: {sender} | Body: {body}")

                        match = re.search(r"Activation Code:\s*<([a-zA-Z0-9_-]+)>", body)
                        if not match:
                            match = re.search(r"<([a-zA-Z0-9_-]{10,40})>", body)
                        
                        if match:
                            device_key = match.group(1)
                            log(f"[ACTIVATION] Key found: {device_key} for phone: {sender}")
                            
                            db = load_db()
                            db[device_key] = {
                                "phone": sender,
                                "activated_at": int(time.time()),
                                "last_seen": int(time.time())
                            }
                            save_db(db)

                            reply_text = f"""Viora Bot Activated

Key: {device_key}
Status: Active for 24 hours

Your video will be sent here automatically after conversion in Viora."""
                            send_whatsapp_text(sender, reply_text)
                            log(f"[REPLY SENT] Confirmation sent to {sender}")
                        else:
                            reply_text = "To activate your device, please open Viora and tap Activate WhatsApp Bot."
                            send_whatsapp_text(sender, reply_text)

    except Exception as e:
        log("[ERROR IN WEBHOOK]", str(e))

    return "EVENT_RECEIVED", 200

@app.route("/upload", methods=["POST"])
def upload_video_from_app():
    device_key = request.form.get("device_key")
    if not device_key:
        return jsonify({"status": "error", "message": "device_key is required"}), 400
    
    if "video" not in request.files:
        return jsonify({"status": "error", "message": "Video file not found"}), 400
    
    db = load_db()
    user_info = db.get(device_key)
    
    if not user_info:
        return jsonify({
            "status": "error",
            "message": "Device not activated. Please tap Activate WhatsApp Bot in Viora first."
        }), 403
    
    activated_at = user_info.get("activated_at", 0)
    if time.time() - activated_at > WINDOW_24H_SECONDS:
        return jsonify({
            "status": "error",
            "message": "Activation expired. Please tap Activate WhatsApp Bot in Viora again."
        }), 403
    
    recipient_phone = user_info.get("phone")
    video_file = request.files["video"]
    
    temp_path = f"/tmp/viora_{int(time.time())}_{video_file.filename}"
    video_file.save(temp_path)

    try:
        log(f"[UPLOAD] Sending video for key {device_key} to {recipient_phone}...")
        res = upload_and_send_video(recipient_phone, temp_path)
        log(f"[UPLOAD SUCCESS] Result from Meta: {json.dumps(res)}")
        return jsonify({
            "status": "success",
            "recipient": recipient_phone,
            "meta_response": res
        }), 200
    except Exception as e:
        log(f"[UPLOAD ERROR] {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    log(f"Viora Bot Server running on port {port}")
    app.run(host="0.0.0.0", port=port)
