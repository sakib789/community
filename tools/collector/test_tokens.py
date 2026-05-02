#!/usr/bin/env python3
"""
Test which token works with RTM API
"""
import os
import sys
import asyncio
import aiohttp
import logging

logging.basicConfig(level=logging.INFO, format="%(message)s")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SLACK_BOT_TOKEN_FILE = os.path.join(SCRIPT_DIR, '.token_slack')
SLACK_APP_TOKEN_FILE = os.path.join(SCRIPT_DIR, '.token_slack_app')

async def test_token(token: str, token_name: str):
    """Test if a token can connect to RTM"""
    logging.info(f"\n{'='*60}")
    logging.info(f"Testing {token_name}")
    logging.info(f"Token prefix: {token[:15]}...")
    logging.info(f"{'='*60}")
    
    # Test 1: Auth test
    async with aiohttp.ClientSession() as session:
        async with session.get(
            "https://slack.com/api/auth.test",
            headers={"Authorization": f"Bearer {token}"}
        ) as response:
            auth_data = await response.json()
            
            if auth_data.get('ok'):
                logging.info(f"✅ Auth test passed")
                logging.info(f"   User: {auth_data.get('user')}")
                logging.info(f"   User ID: {auth_data.get('user_id')}")
                logging.info(f"   Team: {auth_data.get('team')}")
                logging.info(f"   URL: {auth_data.get('url')}")
            else:
                logging.error(f"❌ Auth test failed: {auth_data.get('error')}")
                return False
    
    # Test 2: RTM connect
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://slack.com/api/rtm.connect",
            headers={"Authorization": f"Bearer {token}"},
            json={"batch_presence_aware": 1}
        ) as response:
            rtm_data = await response.json()
            
            if rtm_data.get('ok'):
                logging.info(f"✅ RTM connect SUCCESS!")
                logging.info(f"   WebSocket URL: {rtm_data.get('url')[:50]}...")
                return True
            else:
                error = rtm_data.get('error')
                logging.error(f"❌ RTM connect failed: {error}")
                
                if error == 'not_allowed_token_type':
                    logging.error(f"   This token type cannot use RTM API")
                    logging.error(f"   Token type: {token.split('-')[0]}")
                elif error == 'missing_scope':
                    needed = rtm_data.get('needed')
                    provided = rtm_data.get('provided')
                    logging.error(f"   Missing scopes:")
                    logging.error(f"   Needed: {needed}")
                    logging.error(f"   Provided: {provided}")
                
                return False

async def main():
    # Load tokens
    tokens = []
    
    if os.path.exists(SLACK_BOT_TOKEN_FILE):
        with open(SLACK_BOT_TOKEN_FILE, 'r') as f:
            bot_token = f.read().strip()
            tokens.append((bot_token, "Bot Token (.token_slack)"))
    
    if os.path.exists(SLACK_APP_TOKEN_FILE):
        with open(SLACK_APP_TOKEN_FILE, 'r') as f:
            app_token = f.read().strip()
            tokens.append((app_token, "App Token (.token_slack_app)"))
    
    if not tokens:
        logging.error("❌ No tokens found!")
        return
    
    # Test each token
    rtm_works = False
    for token, name in tokens:
        result = await test_token(token, name)
        if result:
            rtm_works = True
            logging.info(f"\n🎉 {name} works with RTM API!")
    
    if not rtm_works:
        logging.info(f"\n{'='*60}")
        logging.info("❌ Neither token works with RTM API")
        logging.info(f"{'='*60}")
        logging.info("\nToken types:")
        logging.info("  xoxb-... = Bot Token (modern) - ❌ No RTM support")
        logging.info("  xoxp-... = User Token (legacy) - ✅ RTM support")
        logging.info("  xapp-... = App-level Token - ❌ No RTM support (Socket Mode only)")
        logging.info("\nTo use RTM API, you need a User Token (xoxp-...)")
        logging.info("Create one at: https://api.slack.com/apps → OAuth & Permissions")

if __name__ == "__main__":
    asyncio.run(main())
