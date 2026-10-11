# Viora WhatsApp HD Bot Cloud Server
====================================
Panduan ringkas untuk deploy di Render.com:
1. Upload folder ini ke GitHub repo anda (public atau private).
2. Di Render.com -> New Web Service -> Pilih repo GitHub anda.
3. Build Command: pip install -r requirements.txt
4. Start Command: gunicorn bot_server:app
5. Set Environment Variables di Render:
   - META_ACCESS_TOKEN: EAAXNjPMdkMIBSjm7i8HsAUMCaC17YAPRp4OrEQZAhwIe3d9pwHIsgPKwOIFZB5eg8fz4P1yJU8mtT8RIy8JdZChZBIq0CscY5PlZA04IBt9WmF97Ud6sfoVGUQxXAZBmvikepqo2q5yBtOh66xA1JgfDdxBL5Ihxbvsoa4djqMLXFp5D447n7OSqiqsbmGnAZDZD
   - META_PHONE_NUMBER_ID: 1282282738312539
   - META_VERIFY_TOKEN: viora_secret_verify_token_2026
