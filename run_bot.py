#!/usr/bin/env python3
"""
SMM Bot + Admin API + Freemodel Proxy Runner
Sets up environment and starts all services.
"""

import sys
import os

# Add the project root to Python path BEFORE any imports
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Set PYTHONPATH environment variable for subprocesses
os.environ['PYTHONPATH'] = project_root

# Load .env file
from dotenv import load_dotenv
load_dotenv(os.path.join(project_root, '.env'))

import asyncio
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def run_all():
    """Run bot + API together."""
    from bot.main import start_bot
    from bot.web.admin import create_admin_app
    import uvicorn
    
    # Start bot in background
    bot_task = asyncio.create_task(start_bot())
    
    # Start API server
    app = create_admin_app()
    config = uvicorn.Config(app, host="0.0.0.0", port=8080, log_level="info")
    server = uvicorn.Server(config)
    
    logger.info("🚀 Starting SMM Bot API on http://0.0.0.0:8080")
    logger.info("🤖 Telegram bot starting...")
    
    # Run both concurrently
    await asyncio.gather(
        bot_task,
        server.serve(),
    )

if __name__ == "__main__":
    try:
        asyncio.run(run_all())
    except KeyboardInterrupt:
        logger.info("Services stopped by user")