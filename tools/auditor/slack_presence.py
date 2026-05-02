#!/usr/bin/env python3
"""
Slack Presence Tracker using Polling
Tracks user presence (active/away) via periodic API calls
"""

import time
import logging
import os
import sys 
from dotenv import load_dotenv

from typing import Dict, Set
from datetime import datetime

# Third-party libraries
try:
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError
except ImportError as e:
    print(f"❌ Missing dependencies: {e}")
    print("Install with: pip install slack-sdk")
    exit(1)

# ======================== Configuration ========================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SLACK_BOT_TOKEN_FILE = os.path.join(SCRIPT_DIR, '.token_slack')
LOG_FILE = os.path.join(SCRIPT_DIR, 'slack_presence.log')

# API endpoints
SLACK_API_BASE = "https://slack.com/api"

# Polling configuration
POLL_INTERVAL = 60  # Check presence every 60 seconds
MAX_USERS_TO_TRACK = 3000  # Track more users (auditor handles all)

# Setup logging
load_dotenv()
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="a"),
        logging.StreamHandler()
    ]
)



# ======================== Presence Tracker ========================

class PresenceTracker:
    """Tracks user presence via periodic polling using slack_sdk (like auditor.py)"""
    
    def __init__(self, bot_token: str):
        logging.debug("🔧 Initializing Slack client...")
        self.bot_client = WebClient(token=bot_token)
        self.user_presences = {}  # user_id -> {"presence": "active/away", "last_check": timestamp}
        self.user_names = {}  # user_id -> username
        self.tracked_users: Set[str] = set()  # Users we actively track
        self.running = True
        logging.info("✅ Slack client initialized")
    
    def get_all_users(self):
        """Get all users in the workspace (similar to auditor.py)"""
        try:
            logging.info("📋 Fetching Slack members from API...")
            response = self.bot_client.users_list(limit=1000)
            
            if not response.get('ok'):
                logging.error(f"Failed to get users list: {response.get('error')}")
                return
            
            members = response.get('members', [])
            total_users = len(members)
            logging.debug(f"   Retrieved {total_users} total users from Slack")
            
            # Filter real users (not bots, not deleted)
            real_users = []
            for member in members:
                if member.get('deleted'):
                    continue
                if member.get('is_bot'):
                    continue
                
                user_id = member.get('id')
                username = member.get('name', user_id)
                
                self.user_names[user_id] = username
                real_users.append(user_id)
            
            logging.info(f"👥 Found {len(real_users)} real users (excluding bots and deleted)")
            
            # Track up to MAX_USERS_TO_TRACK users
            self.tracked_users = set(real_users[:MAX_USERS_TO_TRACK])
            
            if len(real_users) > MAX_USERS_TO_TRACK:
                logging.warning(f"⚠️  Tracking only first {MAX_USERS_TO_TRACK} users")
            
        except SlackApiError as e:
            logging.error(f"❌ Slack API error: {e}")
    
    def get_user_presence(self, user_id: str) -> str:
        """Get presence for a specific user (same as auditor.py)"""
        try:
            response = self.bot_client.users_getPresence(user=user_id)
            presence = response['presence']
            logging.debug(f"      Presence for {user_id}: {presence}")
            return presence
        except SlackApiError as e:
            logging.debug(f"      Failed to get presence for {user_id}: {e}")
            return "away"
    
    def format_user(self, user_id: str) -> str:
        """Format user ID with name if available"""
        username = self.user_names.get(user_id, user_id)
        return f"{username} ({user_id})"
    
    def poll_presence(self):
        """Poll presence for all tracked users"""
        if not self.tracked_users:
            logging.warning("⚠️  No users to track")
            return
        
        logging.debug(f"🔍 Polling presence for {len(self.tracked_users)} users...")
        
        changes = 0
        for user_id in self.tracked_users:
            
            if user_id != 'UMNGTMEBD':
                continue  # Skip a specific user for testing
            presence = self.bot_client.users_getPresence(user=user_id)
            print(presence)
            print("PRESENCIA DE PEDRO")
            dnd = self.bot_client.dnd_info(user=user_id)
            
            # Format timestamps to readable dates
            dnd_data = dnd.data if hasattr(dnd, 'data') else dnd
            if 'next_dnd_start_ts' in dnd_data:
                start_ts = dnd_data['next_dnd_start_ts']
                end_ts = dnd_data.get('next_dnd_end_ts')
                start_dt = datetime.fromtimestamp(start_ts).strftime('%Y-%m-%d %H:%M:%S')
                end_dt = datetime.fromtimestamp(end_ts).strftime('%Y-%m-%d %H:%M:%S') if end_ts else 'N/A'
                print(f"DND Info: {dnd_data}")
                print(f"  → next_dnd_start: {start_dt} (timestamp: {start_ts})")
                print(f"  → next_dnd_end: {end_dt} (timestamp: {end_ts})")
            else:
                print(f"DND Info: {dnd_data}")
            
            if presence:
                old_state = self.user_presences.get(user_id, {})
                old_presence = old_state.get("presence")
                
                # Detect state change
                if old_presence and old_presence != presence:
                    emoji = "🟢" if presence == "active" else "⚪"
                    user_str = self.format_user(user_id)
                    logging.info(f"{emoji} Presence change: {user_str}: {old_presence} → {presence}")
                    changes += 1
                elif not old_presence:
                    # First time seeing this user
                    emoji = "🟢" if presence == "active" else "⚪"
                    user_str = self.format_user(user_id)
                    logging.info(f"{emoji} Initial presence: {user_str}: {presence}")
                
                # Update state
                self.user_presences[user_id] = {
                    "presence": presence,
                    "last_check": datetime.now()
                }
            
            # Small delay to avoid rate limits (100 requests/min = ~0.6s per request)
            time.sleep(0.7)
        
        if changes > 0:
            logging.info(f"📊 Detected {changes} presence changes")
        else:
            logging.debug(f"📊 No presence changes detected")
        
        # Summary
        active_count = sum(1 for p in self.user_presences.values() if p.get("presence") == "active")
        away_count = sum(1 for p in self.user_presences.values() if p.get("presence") == "away")
        logging.info(f"📊 Current status: {active_count} active, {away_count} away")
    
    def run(self):
        """Run the presence tracker with periodic polling"""
        try:
            # Get initial user list
            self.get_all_users()
            
            # Initial poll
            logging.info(f"🔄 Starting initial presence poll...")
            self.poll_presence()
            
            # Start polling loop
            logging.info(f"⏱️  Starting polling loop (interval: {POLL_INTERVAL}s)")
            
            while self.running:
                time.sleep(POLL_INTERVAL)
                self.poll_presence()
        
        except KeyboardInterrupt:
            logging.info("🛑 Received interrupt signal")
            self.running = False
        except Exception as e:
            logging.error(f"❌ Error in polling loop: {e}")
            raise


# ======================== Token Manager ========================

def load_token() -> str:
    """Load Slack bot token from file"""
    if not os.path.exists(SLACK_BOT_TOKEN_FILE):
        raise FileNotFoundError(f"Slack bot token file not found: {SLACK_BOT_TOKEN_FILE}")
    
    with open(SLACK_BOT_TOKEN_FILE, 'r') as f:
        lines = f.readlines()
        for line in lines:
            line = line.strip()
            if line and not line.startswith('#'):
                token = ''.join(line.split())
                if token:
                    logging.info("✅ Loaded Slack bot token")
                    return token
    
    raise ValueError(f"Slack bot token file is empty or contains only comments: {SLACK_BOT_TOKEN_FILE}")


# ======================== Main ========================

def main():
    """Main function"""
    print("👥 Slack Presence Tracker (Polling)")
    print("📋 Features:")
    print(f"  • Polls presence every {POLL_INTERVAL} seconds")
    print(f"  • Tracks up to {MAX_USERS_TO_TRACK} users")
    print("  • Detects presence changes: active ↔ away")
    print("  • Logs user status: active 🟢 / away ⚪")
    print("🛑 Press Ctrl+C to stop")
    print("-" * 50)
    
    # Load token
    try:
        token = load_token()
    except Exception as e:
        logging.error(f"❌ Failed to load token: {e}")
        return
    
    # Create and run tracker
    tracker = PresenceTracker(token)
    
    try:
        tracker.run()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
        logging.info("User requested shutdown")
    except Exception as e:
        logging.error(f"❌ Unexpected error: {e}")


if __name__ == "__main__":
    main()
