#!/bin/bash
cd /home/workspace/freemodel-proxy && . .venv/bin/activate && python proxy.py --host 127.0.0.1 --port 8765 &
sleep 3
cd /home/workspace/smm-bot && python3 run.py