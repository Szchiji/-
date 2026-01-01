#!/bin/bash
# Start the bot in the background
python bot/main.py &
# Start the web server in the foreground
gunicorn web.app:app --bind 0.0.0.0:${PORT:-8080}