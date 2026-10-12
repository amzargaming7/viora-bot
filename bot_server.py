import os
import re
import json
import time
import requests
from flask import Flask, request, jsonify, send_file, send_from_directory

app = Flask(__name__)

PORT = int(os.environ.get("PORT", 10000))
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "viora_verify_secret")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "1282282738312539")

ACTIVATIONS_FILE = "activations.json"
device_activations = {}

def load_activations():
    global device_activations
    if os.path.exists(ACTIVATIONS_FILE):
        try:
            with open(ACTIVATIONS_FILE, "r") as f:
                device_activations = json.load(f)
        except Exception as e:
            print(f"[STORE] Error loading activations: {e}")
            device_activations = {}

def save_activations():
    try:
        with open(ACTIVATIONS_FILE, "w") as f:
            json.dump(device_activations, f, indent=2)
    except Exception as e:
        print(f"[STORE] Error saving activations: {e}")

load_activations()

def is_bsuid(identifier):
    if not identifier:
        return False
    # Meta BSUID format: "MY.2906829746353050" or contains letters/dots
    return "." in identifier or any(c.isalpha() for c in identifier)

def send_whatsapp_text(target, text):
    if not WHATSAPP_TOKEN or not target:
        print(f"[SEND_TEXT] Missing token or target: target={target}")
        return False
    
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "type": "text",
        "text": {"body": text}
    }
    
    # Meta Username Privacy / BSUID compatibility:
    # Use "recipient" for BSUID, "to" for standard E.164 phone numbers
    if is_bsuid(target):
        payload["recipient"] = target
    else:
        payload["to"] = target
        
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=20)
        print(f"[SEND_TEXT] Status: {res.status_code}, Body: {res.text}")
        return res.status_code in [200, 201]
    except Exception as e:
        print(f"[SEND_TEXT] Exception: {e}")
        return False

def send_whatsapp_video(target, video_path, caption):
    if not WHATSAPP_TOKEN or not target:
        return False, "Missing token or target"
        
    # 1. Upload media to WhatsApp Cloud API
    upload_url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/media"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    
    try:
        with open(video_path, "rb") as vf:
            files = {
                "file": (os.path.basename(video_path), vf, "video/mp4"),
                "messaging_product": (None, "whatsapp"),
                "type": (None, "video/mp4")
            }
            upload_res = requests.post(upload_url, headers=headers, files=files, timeout=120)
            
        if upload_res.status_code not in [200, 201]:
            return False, f"Media upload failed: {upload_res.text}"
            
        media_id = upload_res.json().get("id")
        if not media_id:
            return False, "No media ID returned"
            
        # 2. Send media message
        msg_url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
        msg_headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "type": "video",
            "video": {
                "id": media_id,
                "caption": caption
            }
        }
        if is_bsuid(target):
            payload["recipient"] = target
        else:
            payload["to"] = target
            
        msg_res = requests.post(msg_url, headers=msg_headers, json=payload, timeout=30)
        return msg_res.status_code in [200, 201], msg_res.text
    except Exception as e:
        return False, str(e)

@app.route("/", methods=["GET"])
def home():
    if os.path.exists("viora_web.html"):
        return send_file("viora_web.html")
    return "<h1>Viora Cloud Bot & OTA Server is Running</h1><p>Status: Healthy</p>"

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)
    if not data:
        return "OK", 200

    print(f"[WEBHOOK EVENT RAW] {json.dumps(data)}")

    try:
        entries = data.get("entry", [])
        for entry in entries:
            for change in entry.get("changes", []):
                val = change.get("value", {})
                contacts = val.get("contacts", [])
                contact_wa_id = contacts[0].get("wa_id") if contacts else None
                contact_user_id = contacts[0].get("user_id") if contacts else None
                contact_name = contacts[0].get("profile", {}).get("name", "") if contacts else ""
                contact_username = contacts[0].get("profile", {}).get("username", "") if contacts else ""

                for msg in val.get("messages", []):
                    # Robust Sender ID extraction:
                    # 1. Phone number (from msg.get("from") or contact.get("wa_id"))
                    # 2. Meta BSUID / User ID (from msg.get("from_user_id") or contact.get("user_id"))
                    sender = (msg.get("from") or 
                              contact_wa_id or 
                              msg.get("from_user_id") or 
                              contact_user_id)
                    
                    msg_body = msg.get("text", {}).get("body", "").strip() if msg.get("type") == "text" else ""

                    print(f"[INCOMING MSG] From: {sender} | Body: {msg_body}")

                    # Detect activation key format: <key> or hex string 16-40 chars
                    m = re.search(r"<([a-zA-Z0-9]{16,40})>", msg_body)
                    if not m:
                        m = re.search(r"([a-fA-F0-9]{20})", msg_body)

                    if m and sender:
                        device_key = m.group(1).lower()
                        device_activations[device_key] = {
                            "target": sender,
                            "type": "user_id" if is_bsuid(sender) else "phone",
                            "timestamp": time.time(),
                            "name": contact_name,
                            "username": contact_username
                        }
                        save_activations()
                        print(f"[ACTIVATION] Key found: {device_key} for target: {sender}")

                        confirmation_text = (
                            "Viora Bot Activated\n\n"
                            f"Key: {device_key}\n"
                            "Status: Active for 24 hours\n\n"
                            "Your video will be sent here automatically after conversion in Viora."
                        )
                        send_whatsapp_text(sender, confirmation_text)
                        print(f"[REPLY SENT] Confirmation sent to {sender}")
    except Exception as e:
        print(f"[WEBHOOK ERROR] {e}")

    return "OK", 200

# Device lookup endpoints (supports both /api/device/<key> and /get_phone)
@app.route("/api/device/<key>", methods=["GET"])
@app.route("/get_phone", methods=["GET"])
def check_device(key=None):
    if not key:
        key = request.args.get("key", "").strip()
    key = key.lower()
    
    data = device_activations.get(key)
    if not data:
        return jsonify({"status": "not_found", "message": "Key not activated"}), 404
        
    elapsed = time.time() - data.get("timestamp", 0)
    if elapsed > 24 * 3600:
        return jsonify({"status": "expired", "message": "Key expired after 24h"}), 404
        
    target = data.get("target", "")
    return jsonify({
        "status": "active",
        "phone": target,
        "user_id": target,
        "is_bsuid": is_bsuid(target),
        "expires_in": int(24 * 3600 - elapsed)
    }), 200

# In-App OTA Update Endpoint
@app.route("/api/version", methods=["GET"])
def get_version():
    return jsonify({
        "version_code": 1,
        "version_name": "1.0",
        "download_url": "https://viora-bot.onrender.com/download/viora.apk",
        "changelog": (
            "Viora v1.0 Official Release\n"
            "- PureStatus 1152x1920 HD Status Engine\n"
            "- WhatsApp Username Privacy / BSUID Auto-Detection\n"
            "- Direct WhatsApp Bot Delivery with HD Badge\n"
            "- Built-in In-App OTA Auto-Updater"
        )
    }), 200

@app.route("/download/viora.apk", methods=["GET"])
def download_apk():
    apk_paths = ["viora.apk", "app-release.apk", "app-debug.apk"]
    for p in apk_paths:
        if os.path.exists(p):
            return send_file(p, as_attachment=True, download_name="viora.apk")
    return jsonify({"error": "APK not yet uploaded to server root. Please place viora.apk in server directory."}), 404

# Video Upload endpoint from Viora Android App
@app.route("/upload", methods=["POST"])
@app.route("/upload_video", methods=["POST"])
def upload_video():
    device_key = request.form.get("device_key", "").strip().lower()
    if not device_key:
        return jsonify({"status": "error", "message": "device_key required"}), 400
        
    data = device_activations.get(device_key)
    if not data:
        return jsonify({"status": "error", "message": "Device key not activated"}), 403
        
    target = data.get("target")
    if not target:
        return jsonify({"status": "error", "message": "Target user not found"}), 403
        
    if "file" not in request.files:
        return jsonify({"status": "error", "message": "No video file provided"}), 400
        
    file = request.files["file"]
    save_path = f"/tmp/{int(time.time())}_{device_key}.mp4"
    file.save(save_path)
    
    caption = "Your HD video is ready. Tap Forward and choose My Status to post."
    ok, resp = send_whatsapp_video(target, save_path, caption)
    
    if os.path.exists(save_path):
        os.remove(save_path)
        
    if ok:
        return jsonify({"status": "success", "message": "Video sent to WhatsApp"}), 200
    else:
        return jsonify({"status": "error", "message": resp}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
