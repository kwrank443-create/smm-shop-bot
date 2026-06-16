#!/bin/bash
export PYTHONPATH=/home/workspace/smm-bot
cd /home/workspace/smm-bot

# Load .env if exists
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

exec python3 bot/main.py