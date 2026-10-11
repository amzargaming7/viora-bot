"""
Viora HD WhatsApp Bot Server (PureStatus Architecture Replica)
==============================================================
Server ini mengendalikan:
1. Webhook Meta WhatsApp API (GET untuk verifikasi, POST untuk terima mesej pengaktifan).
2. Pendaftaran automatik: Bila pengguna hantar "Activation Code: <KEY>",
   server merekodkan <KEY> -> nombor WhatsApp pengguna (sah 24 jam)
   dan membalas terus di WhatsApp: "✅ Activation Berjaya!".
3. Endpoint POST /upload: Menerima video HD yang diconvert dari app Viora bersama device_key,
   kemudian memuat naik ke Meta Cloud API dan menghantar video HD tersebut terus ke WhatsApp pengguna.
"""

import os
import json
import time
import re
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ==========================================
# KONFIGURASI META WHATSAPP CLOUD API
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
    """Menghantar mesej teks WhatsApp melalui Meta Cloud API"""
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
    """Memuat naik fail video ke Meta dan menghantar ke WhatsApp penerima"""
    # 1. Upload media
    media_url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/media"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    with open(video_path, "rb") as f:
        files = {
            "file": (os.path.basename(video_path), f, "video/mp4"),
            "messaging_product": (None, "whatsapp"),
            "type": (None, "video/mp4")
        }
        res_upload = requests.post(media_url, headers=headers, files=files, timeout=60)
    
    if res_upload.status_code not in (200, 201):
        raise RuntimeError(f"Gagal upload media ke Meta: {res_upload.text}")
    
    media_id = res_upload.json().get("id")

    # 2. Send media message
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
            "caption": caption if caption else "🎬 *Viora 1152p HD Video*\n\nTekan *Forward (↪️)* ➔ *My Status* untuk post kualiti HD tanpa pecah!"
        }
    }
    res_send = requests.post(msg_url, headers=msg_headers, json=msg_payload, timeout=20)
    if res_send.status_code not in (200, 201):
        raise RuntimeError(f"Gagal hantar video ke WhatsApp: {res_send.text}")
    
    return res_send.json()

# ==========================================
# 1. WEBHOOK ENDPOINT (VERIFIKASI & MESEJ)
# ==========================================
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    """Endpoint untuk Meta mengesahkan webhook semasa persediaan"""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("[WEBHOOK] Webhook verified berjaya oleh Meta!")
        return challenge, 200
    print("[WEBHOOK] Verification failed. Token mismatch.")
    return "Forbidden", 403

@app.route("/webhook", methods=["POST"])
def receive_webhook():
    """Menerima mesej masuk daripada pengguna WhatsApp"""
    data = request.get_json(silent=True) or {}
    print("[WEBHOOK EVENT]", json.dumps(data, indent=2))

    try:
        entries = data.get("entry", [])
        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                messages = value.get("messages", [])
                for msg in messages:
                    sender = msg.get("from") # Nombor telefon pengguna (cth: 60184741732)
                    msg_type = msg.get("type")
                    
                    if msg_type == "text":
                        body = msg.get("text", {}).get("body", "").strip()
                        print(f"[INCOMING MSG] Daripada: {sender} | Mesej: {body}")

                        # Format mesej activation PureStatus:
                        # "Activation Code:\n<DEVICE_KEY>\n..."
                        match = re.search(r"Activation Code:\s*<([a-zA-Z0-9_-]+)>", body)
                        if not match:
                            match = re.search(r"<([a-zA-Z0-9_-]{10,40})>", body)
                        
                        if match:
                            device_key = match.group(1)
                            print(f"[ACTIVATION] Key dikesan: {device_key} untuk nombor: {sender}")
                            
                            db = load_db()
                            db[device_key] = {
                                "phone": sender,
                                "activated_at": int(time.time()),
                                "last_seen": int(time.time())
                            }
                            save_db(db)

                            reply_text = (
                                "✅ *Viora HD Bot Berjaya Diaktifkan!*\n\n"
                                f"🔑 *Key:* `{device_key}`\n"
                                "⏱️ *Tempoh Sah:* 24 Jam bermula sekarang.\n\n"
                                "Sila kembali ke aplikasi *Viora*, convert video anda, dan video kualiti penuh 1152p HD akan dihantar secara automatik ke sini! 🚀"
                            )
                            send_whatsapp_text(sender, reply_text)
                            print(f"[REPLY SENT] Mesej pengesahan dihantar ke {sender}")
                        else:
                            reply_text = (
                                "👋 Hai! Ini ialah bot penghantaran video HD Viora.\n\n"
                                "Untuk aktifkan peranti anda, sila tekan butang *⚡ Reactivate HD Bot* di dalam aplikasi Viora."
                            )
                            send_whatsapp_text(sender, reply_text)

    except Exception as e:
        print("[ERROR IN WEBHOOK HANDLING]", str(e))

    return "EVENT_RECEIVED", 200

# ==========================================
# 2. UPLOAD ENDPOINT (DIPANGGIL OLEH APP VIORA)
# ==========================================
@app.route("/upload", methods=["POST"])
def upload_video_from_app():
    """
    App Viora memanggil endpoint ini selepas selesai convert:
    POST /upload
    FormData:
      - device_key: <kunci peranti>
      - video: <fail mp4>
    """
    device_key = request.form.get("device_key")
    if not device_key:
        return jsonify({"status": "error", "message": "device_key diperlukan"}), 400
    
    if "video" not in request.files:
        return jsonify({"status": "error", "message": "Fail video tidak dijumpai"}), 400
    
    db = load_db()
    user_info = db.get(device_key)
    
    if not user_info:
        return jsonify({
            "status": "error",
            "message": "Peranti belum diaktifkan di WhatsApp. Sila tekan butang 'Reactivate HD Bot' terlebih dahulu!"
        }), 403
    
    activated_at = user_info.get("activated_at", 0)
    if time.time() - activated_at > WINDOW_24H_SECONDS:
        return jsonify({
            "status": "error",
            "message": "Kunci 24 jam telah tamat tempoh. Sila aktifkan semula di WhatsApp!"
        }), 403
    
    recipient_phone = user_info.get("phone")
    video_file = request.files["video"]
    
    temp_path = f"/tmp/viora_srv_{int(time.time())}_{video_file.filename}"
    video_file.save(temp_path)

    try:
        print(f"[SERVER UPLOAD] Menghantar video untuk key {device_key} ke WhatsApp {recipient_phone}...")
        res = upload_and_send_video(recipient_phone, temp_path)
        return jsonify({
            "status": "success",
            "recipient": recipient_phone,
            "meta_response": res
        }), 200
    except Exception as e:
        print(f"[SERVER UPLOAD ERROR] {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

@app.route("/status", methods=["GET"])
def server_status():
    db = load_db()
    return jsonify({
        "status": "online",
        "active_users": len(db),
        "phone_number_id": PHONE_NUMBER_ID
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Viora Bot Server berjalan di port {port}...")
    print(f"🔗 Webhook Verify Token: {VERIFY_TOKEN}")
    app.run(host="0.0.0.0", port=port)
