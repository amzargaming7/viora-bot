# Viora HD Bot Cloud Server
Deploy on Render.com:
- Build Command: pip install -r requirements.txt
- Start Command: gunicorn --timeout 120 --access-logfile - --log-file - bot_server:app
