#!/usr/bin/env python3
"""
Slack Gateway with GitHub Issue Creation
Architecture with multiple classes for better organization
"""

import asyncio
import json
import logging
import os
import sys
import websockets
from websockets.exceptions import ConnectionClosed
import aiohttp
from typing import Dict, Optional, List
from datetime import datetime
from dataclasses import dataclass

# Add parent directory to path to import indexer
PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PARENT_DIR)
from indexer.opensearch_indexer import OpenSearchIndexer, create_slack_parent_document, create_slack_comment_document
from assigner.assigner import IssueAssigner
from logging_config import setup_logger
from token_manager import TokenManager as CentralTokenManager

# ======================== Configuration ========================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(SCRIPT_DIR, 'slack_gateway.log')

# API endpoints
SLACK_API_BASE = "https://slack.com/api"
GITHUB_API_BASE = "https://api.github.com"
GITHUB_REPO = os.environ.get('GITHUB_REPO', 'wazuh/community-dev')

# Setup logging using centralized config
logger = setup_logger("Collector.Slack", log_file=LOG_FILE)


# ======================== Data Classes ========================

@dataclass
class SlackMessage:
    """Represents a Slack message"""
    user: str
    channel: str
    text: str
    ts: str
    thread_ts: Optional[str] = None
    channel_name: Optional[str] = None
    user_name: Optional[str] = None
    team_domain: Optional[str] = None
    
    @property
    def is_thread_reply(self) -> bool:
        """Check if this is a thread reply"""
        return self.thread_ts is not None and self.thread_ts != self.ts
    
    def get_permalink(self) -> Optional[str]:
        """Build Slack permalink for this message"""
        if not self.team_domain:
            return None
        # Convert timestamp: "1760450458.359049" -> "1760450458359049"
        ts_for_url = self.ts.replace('.', '')
        return f"https://{self.team_domain}.slack.com/archives/{self.channel}/p{ts_for_url}"
    
    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            'user': self.user,
            'channel': self.channel,
            'text': self.text,
            'ts': self.ts,
            'thread_ts': self.thread_ts,
            'channel_name': self.channel_name,
            'user_name': self.user_name,
            'team_domain': self.team_domain
        }


# ======================== OpenSearch-based Message Tracking ========================
# Note: Message tracking is now handled entirely through OpenSearch
# - Parent messages are indexed with document_type="parent"
# - Thread replies are indexed with document_type="child" and routing="parent_message_id"
# - No local database needed


# ======================== Token Manager (uses centralized) ========================

class TokenManager:
    """Wrapper for centralized token manager"""
    
    def __init__(self, central_manager: Optional[CentralTokenManager] = None):
        if central_manager is None:
            central_manager = CentralTokenManager()
        
        self.slack_bot_token = central_manager.require_token('slack_bot')
        self.slack_app_token = central_manager.require_token('slack_app')
        self.github_token = central_manager.get_token('github')


# ======================== Slack API Client ========================

class SlackAPIClient:
    """Handles Slack REST API calls"""
    
    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self.headers = {
            'Authorization': f'Bearer {bot_token}',
            'Content-Type': 'application/json'
        }
    
    async def auth_test(self) -> dict:
        """Test authentication"""
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{SLACK_API_BASE}/auth.test", headers=self.headers) as response:
                return await response.json()
    
    async def get_channels(self) -> List[dict]:
        """Get list of channels the bot is member of"""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{SLACK_API_BASE}/conversations.list?exclude_archived=true&types=public_channel",
                #f"{SLACK_API_BASE}/conversations.list?exclude_archived=true&types=public_channel, private_channel",
                headers=self.headers
            ) as response:
                data = await response.json()
                #print(data)
                if data.get('ok'):
                    return [ch for ch in data.get('channels', []) if ch.get('is_member', False)]
                return []
    
    async def get_user_info(self, user_id: str) -> dict:
        """Get user information"""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{SLACK_API_BASE}/users.info?user={user_id}",
                headers=self.headers
            ) as response:
                data = await response.json()
                if data.get('ok'):
                    return data.get('user', {})
                return {}
    
    async def get_channel_info(self, channel_id: str) -> dict:
        """Get channel information"""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{SLACK_API_BASE}/conversations.info?channel={channel_id}",
                headers=self.headers
            ) as response:
                data = await response.json()
                if data.get('ok'):
                    return data.get('channel', {})
                return {}


# ======================== GitHub Ticket Creator ========================

class GitHubTicketCreator:
    """Creates GitHub issues from Slack messages"""
    
    def __init__(self, github_token: Optional[str], repo: str = GITHUB_REPO):
        # Clean the token to remove any whitespace or newlines
        self.github_token = ''.join(github_token.split()) if github_token else None
        self.repo = repo
        self.enabled = self.github_token is not None and len(self.github_token) > 0
        
        # Initialize OpenSearch indexer
        self.indexer = OpenSearchIndexer()
        
        # Cache for user names to avoid repeated API calls
        self.user_cache = {}
        
        if not self.enabled:
            logger.warning("⚠️  GitHub integration disabled (no token found)")
        else:
            logger.info(f"✅ GitHub integration enabled for repo: {repo}")
    
    async def replace_user_mentions(self, content: str, api_client) -> str:
        """Replace Slack user mentions <@U123456> with actual usernames"""
        import re
        
        # Find all user mentions in the format <@U123456>
        mention_pattern = r'<@([UW][A-Z0-9]+)>'
        mentions = re.findall(mention_pattern, content)
        
        # Resolve each user ID
        for user_id in mentions:
            # Check cache first
            if user_id in self.user_cache:
                username = self.user_cache[user_id]
            else:
                # Fetch from API
                user_info = await api_client.get_user_info(user_id)
                username = user_info.get('name', None)
                if username:
                    self.user_cache[user_id] = username
            
            if username:
                # Replace <@U123456> with @username
                content = content.replace(f'<@{user_id}>', f'@{username}')
            else:
                # If resolution fails, keep the mention but make it clearer
                content = content.replace(f'<@{user_id}>', f'@user-{user_id}')
        
        return content
    
    async def process_message(self, message: SlackMessage, api_client=None) -> Optional[dict]:
        """Process a Slack message: create issue or add comment"""
        if not self.enabled:
            logger.debug("GitHub integration disabled, skipping")
            return None
        
        # Check if this is a thread reply
        if message.is_thread_reply:
            return await self._add_thread_comment(message, api_client)
        else:
            return await self._create_parent_issue(message, api_client)
    
    async def _create_parent_issue(self, message: SlackMessage, api_client=None) -> Optional[dict]:
        """Create a GitHub issue for a parent message"""
        # Resolve user mentions in content
        if api_client:
            resolved_content = await self.replace_user_mentions(message.text, api_client)
            message.text = resolved_content
        
        # Build issue title and body
        title = self._build_title(message)
        body = self._build_body(message)
        labels = self._get_labels(message)
        
        logger.info(f"📝 Creating new GitHub issue for message {message.ts}")
        logger.debug(f"🔍 Repository: {self.repo}")
        logger.debug(f"🔍 Title: {title}")
        logger.debug(f"🔍 Labels: {labels}")
        logger.debug(f"🔍 Token prefix: {self.github_token[:10]}..." if self.github_token else "No token")
        
        headers = {
            'Authorization': f'token {self.github_token}',
            'Accept': 'application/vnd.github.v3+json',
            'Content-Type': 'application/json'
        }
        
        payload = {
            'title': title,
            'body': body,
            'labels': labels
        }
        
        try:
            url = f"{GITHUB_API_BASE}/repos/{self.repo}/issues"
            logger.debug(f"🔍 POST {url}")
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    headers=headers,
                    json=payload
                ) as response:
                    if response.status == 201:
                        issue_data = await response.json()
                        issue_number = issue_data['number']
                        issue_url = issue_data['html_url']
                        
                        # Index parent document in OpenSearch
                        try:
                            parent_doc = create_slack_parent_document(
                                message_ts=message.ts,
                                channel_id=message.channel,
                                channel_name=message.channel_name or message.channel,
                                user_id=message.user,
                                user_name=message.user_name or message.user,
                                content=message.text,
                                permalink=message.get_permalink(),
                                github_issue_number=issue_number,
                                github_issue_url=issue_url,
                                labels=labels
                            )
                            self.indexer.index_parent(parent_doc)
                        except Exception as e:
                            logger.error(f"❌ Error indexing parent document: {e}")
                        
                        # Auto-assign issue to user with available quota
                        try:
                            assigner = IssueAssigner()
                            assigner.assign_issue(issue_number)
                            logger.info(f"✅ Auto-assigned issue #{issue_number} to user with available quota")
                        except Exception as e:
                            logger.warning(f"⚠️  Failed to auto-assign issue #{issue_number}: {e}")
                        
                        logger.info(f"✅ Created GitHub issue #{issue_number}: {title}")
                        return issue_data
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ Failed to create GitHub issue")
                        logger.error(f"   Status: {response.status}")
                        logger.error(f"   URL: {url}")
                        logger.error(f"   Repository: {self.repo}")
                        logger.error(f"   Response: {error_text}")
                        logger.error(f"   Headers: {dict(response.headers)}")
                        return None
        except Exception as e:
            logger.error(f"❌ Exception creating GitHub issue: {e}")
            return None
    
    async def _add_thread_comment(self, message: SlackMessage, api_client=None) -> Optional[dict]:
        """Add a comment to the parent issue for a thread reply"""
        # Resolve user mentions in content
        if api_client:
            resolved_content = await self.replace_user_mentions(message.text, api_client)
            message.text = resolved_content
        
        # Find the parent issue from OpenSearch
        logger.debug(f"🔍 Searching OpenSearch for parent message: slack_{message.thread_ts}")
        parent_doc = await self.indexer.get_parent_document(f"slack_{message.thread_ts}")
        
        if not parent_doc:
            logger.warning(f"⚠️  No parent document found in OpenSearch for thread {message.thread_ts}")
            logger.info(f"   Tried message_id: slack_{message.thread_ts}")
            return None
        
        issue_number = parent_doc.get('github_issue_number')
        issue_url = parent_doc.get('github_issue_url')
        channel_name = parent_doc.get('channel', message.channel)
        
        logger.debug(f"✅ Found parent in OpenSearch: Issue #{issue_number}")
        
        # Build comment body
        comment_body = self._build_comment_body(message)
        
        logger.info(f"💬 Adding comment to issue #{issue_number} for thread reply")
        
        headers = {
            'Authorization': f'token {self.github_token}',
            'Accept': 'application/vnd.github.v3+json',
            'Content-Type': 'application/json'
        }
        
        payload = {
            'body': comment_body
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{GITHUB_API_BASE}/repos/{self.repo}/issues/{issue_number}/comments",
                    headers=headers,
                    json=payload
                ) as response:
                    if response.status == 201:
                        comment_data = await response.json()
                        
                        # Index comment document in OpenSearch
                        try:
                            comment_doc = create_slack_comment_document(
                                message_ts=message.ts,
                                thread_ts=message.thread_ts,
                                channel_id=message.channel,
                                user_id=message.user,
                                user_name=message.user_name or message.user,
                                content=message.text,
                                permalink=message.get_permalink(),
                                github_comment_id=comment_data.get('id'),
                                github_issue_number=issue_number,
                                github_issue_url=issue_url,
                                channel_name=channel_name
                            )
                            parent_id = f"slack_{message.channel}_{message.thread_ts}"
                            self.indexer.index_comment(comment_doc, parent_id)
                        except Exception as e:
                            logger.error(f"❌ Error indexing comment document: {e}")
                        
                        logger.info(f"✅ Added comment to issue #{issue_number}")
                        return comment_data
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ Failed to add comment: {response.status} - {error_text}")
                        return None
        except Exception as e:
            logger.error(f"❌ Exception adding comment: {e}")
            return None
    
    def _build_title(self, message: SlackMessage) -> str:
        """Build issue title from message (without platform/channel brackets)"""
        # Convert Slack format to GitHub Markdown for title
        converted_text = SlackToMarkdownConverter.convert(message.text)
        # Remove newlines from title and truncate
        title = converted_text.replace('\n', ' ').strip()
        text_preview = title[:100] if len(title) > 100 else title
        return text_preview
    
    def _build_body(self, message: SlackMessage) -> str:
        """Build issue body from message"""
        user_info = f"@{message.user_name}" if message.user_name else message.user
        channel_info = f"#{message.channel_name}" if message.channel_name else message.channel
        
        # Convert Slack format to GitHub Markdown
        converted_text = SlackToMarkdownConverter.convert(message.text)
        
        # Get permalink
        permalink = message.get_permalink()
        permalink_line = f"**Permalink:** {permalink}\n" if permalink else ""
        
        body = f"""## Slack Message

**Channel:** {channel_info}
**User:** {user_info}
**Timestamp:** {message.ts}
{permalink_line}
### Message Content:

{converted_text}

"""
        return body
    
    def _build_comment_body(self, message: SlackMessage) -> str:
        """Build comment body for thread replies"""
        user_info = f"@{message.user_name}" if message.user_name else message.user
        
        # Convert Slack format to GitHub Markdown
        converted_text = SlackToMarkdownConverter.convert(message.text)
        
        # Get permalink
        permalink = message.get_permalink()
        permalink_line = f"**Permalink:** {permalink}\n\n" if permalink else ""
        
        body = f"""### Thread Reply from {user_info}

**User:** {user_info}
**Timestamp:** {message.ts}
{permalink_line}{converted_text}

"""
        return body
    
    def _get_labels(self, message: SlackMessage) -> List[str]:
        """Determine labels for the issue"""
        labels = ['platform/slack']
        
        # Add channel-specific label
        if message.channel_name:
            labels.append(f'slack/channel/{message.channel_name}')
        
        return labels


# ======================== Slack to Markdown Converter ========================

class SlackToMarkdownConverter:
    """Converts Slack's mrkdwn format to GitHub Markdown"""
    
    @staticmethod
    def convert(text: str) -> str:
        """Convert Slack format to GitHub Markdown"""
        if not text:
            return text
        
        import re
        
        # 1. Convert HTML entities (Slack uses these)
        text = text.replace('&amp;', '&')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        
        # 2. Convert Slack links <url|text> to Markdown [text](url)
        # Handle links with text
        text = re.sub(r'<(https?://[^|>]+)\|([^>]+)>', r'[\2](\1)', text)
        # Handle bare links <url>
        text = re.sub(r'<(https?://[^>]+)>', r'\1', text)
        
        # 3. Convert user mentions <@U123> to @username (or just @U123 if no name available)
        # This will need username lookup in actual implementation
        text = re.sub(r'<@([UW][A-Z0-9]+)>', r'@\1', text)
        
        # 4. Convert channel mentions <#C123|channel-name> to #channel-name
        text = re.sub(r'<#[A-Z0-9]+\|([^>]+)>', r'#\1', text)
        # Handle channel mentions without name
        text = re.sub(r'<#([A-Z0-9]+)>', r'#\1', text)
        
        # 5. Convert special mentions
        text = re.sub(r'<!here>', '@here', text)
        text = re.sub(r'<!channel>', '@channel', text)
        text = re.sub(r'<!everyone>', '@everyone', text)
        
        # 6. Convert usergroup mentions <!subteam^ID|name> to @name
        text = re.sub(r'<!subteam\^[A-Z0-9]+\|([^>]+)>', r'@\1', text)
        text = re.sub(r'<!subteam\^([A-Z0-9]+)>', r'@\1', text)
        
        # 7. Convert Slack strikethrough ~text~ to GitHub ~~text~~
        text = re.sub(r'~([^~]+)~', r'~~\1~~', text)
        
        # 8. Slack bold is *text*, GitHub prefers **text** (though both work)
        # We need to be careful not to convert italic markers
        # Convert isolated *bold* to **bold**
        text = re.sub(r'(?<!\*)\*([^\*\n]+)\*(?!\*)', r'**\1**', text)
        
        # 9. Block quotes are the same (>) - no conversion needed
        
        # 10. Code blocks are the same (```) - no conversion needed
        
        # 11. Inline code is the same (`) - no conversion needed
        
        return text


# ======================== Event Formatter ========================

class SlackEventFormatter:
    """Formats Slack events for display"""
    
    @staticmethod
    def format_event(event_data: Dict) -> str:
        """Format event data for console output"""
        event_type = event_data.get("type", "unknown")
        
        if event_type == "hello":
            return "👋 HELLO - Socket Mode connection established"
            
        elif event_type == "disconnect":
            reason = event_data.get("reason", "unknown")
            return f"🔌 DISCONNECT - Reason: {reason}"
            
        elif event_type == "events_api":
            event = event_data.get("payload", {}).get("event", {})
            return SlackEventFormatter._format_events_api(event)
        
        else:
            return f"📡 {event_type.upper()}"
    
    @staticmethod
    def _format_events_api(event: dict) -> str:
        """Format events_api events"""
        inner_type = event.get("type", "unknown")
        logger.info(f"{event}")

        if inner_type == "message":
            return SlackEventFormatter._format_message(event)
        
        elif inner_type == "reaction_added":
            reaction = event.get("reaction", "")
            user = event.get("user", "Unknown")
            channel = event.get("item", {}).get("channel", "Unknown")
            return f"👍 REACTION_ADD [#{channel}] {user} added :{reaction}:"
        
        elif inner_type == "app_mention":
            user = event.get("user", "Unknown")
            channel = event.get("channel", "Unknown")
            text = event.get("text", "")
            return f"📢 APP_MENTION [#{channel}] {user}: {text[:100]}"
        
        else:
            return f"📡 EVENTS_API.{inner_type.upper()}"
    
    @staticmethod
    def _format_message(event: dict) -> str:
        """Format message events"""
        user = event.get("user", "Unknown")
        channel = event.get("channel", "Unknown")
        text = event.get("text", "")
        thread_ts = event.get("thread_ts")
        ts = event.get("ts")
        
        # Check if it's a thread reply
        is_thread_reply = thread_ts and thread_ts != ts
        
        # Check if it's a bot message
        if event.get("bot_id") or event.get("subtype") == "bot_message":
            bot_username = event.get("username", "Bot")
            return f"🤖 BOT_MESSAGE [#{channel}] {bot_username}: {text[:100]}"
        
        # Check for message subtypes
        subtype = event.get("subtype")
        if subtype == "message_changed":
            return f"✏️  MESSAGE_CHANGED [#{channel}] {user}: {text[:100]}"
        elif subtype == "message_deleted":
            return f"🗑️  MESSAGE_DELETED [#{channel}] {user}"
        elif is_thread_reply:
            return f"� THREAD_REPLY [#{channel}] {user}: {text[:100]}"
        else:
            return f"�📝 NEW_MESSAGE [#{channel}] {user}: {text[:100]}"


# ======================== Slack Gateway ========================

class SlackGateway:
    """Main Slack WebSocket Gateway"""
    
    def __init__(self, token_manager: TokenManager):
        self.token_manager = token_manager
        self.app_token = token_manager.slack_app_token
        self.websocket = None
        self.gateway_url = None
        self.team_domain = None  # Will be set after auth_test
        
        # Initialize components
        self.api_client = SlackAPIClient(token_manager.slack_bot_token)
        self.ticket_creator = GitHubTicketCreator(token_manager.github_token)
        self.event_formatter = SlackEventFormatter()
    
    async def test_permissions(self):
        """Test bot permissions and show available channels"""
        auth_data = await self.api_client.auth_test()
        
        if auth_data.get('ok'):
            logger.info(f"🤖 Bot authenticated as: {auth_data.get('user')}")
            logger.info(f"📍 Team: {auth_data.get('team')} | URL: {auth_data.get('url')}")
            
            # Extract team domain from URL (e.g., "https://myteam.slack.com/" -> "myteam")
            url = auth_data.get('url', '')
            if url:
                # Parse domain from URL like "https://myteam.slack.com/"
                import re
                match = re.search(r'https://([^.]+)\.slack\.com', url)
                if match:
                    self.team_domain = match.group(1)
                    logger.info(f"🏢 Team domain: {self.team_domain}")
        else:
            logger.error(f"❌ Auth test failed: {auth_data.get('error')}")
            return False
        
        # Get channels
        channels = await self.api_client.get_channels()
        logger.info(f"📋 Bot is member of {len(channels)} channels:")
        
        for ch in channels[:10]:
            logger.info(f"  #{ch.get('name')} (ID: {ch.get('id')})")
        
        if len(channels) > 10:
            logger.info(f"  ... and {len(channels) - 10} more")
        
        if not channels:
            logger.warning("⚠️  Bot is not a member of any channels!")
            logger.info("💡 Add the bot to channels with: /invite @your_bot_name")
        
        return True
    
    async def get_gateway_url(self) -> str:
        """Get the Socket Mode URL from Slack API"""
        headers = {
            'Authorization': f'Bearer {self.app_token}',
            'Content-Type': 'application/json'
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{SLACK_API_BASE}/apps.connections.open",
                headers=headers
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('ok'):
                        url = data['url']
                        logger.info(f"✅ Got Socket Mode URL")
                        return url
                    else:
                        raise Exception(f"Slack API error: {data.get('error', 'Unknown error')}")
                else:
                    raise Exception(f"Failed to get Socket Mode URL: {response.status}")
    
    async def send_ack(self, envelope_id: str):
        """Acknowledge received events"""
        ack_payload = {"envelope_id": envelope_id}
        await self.websocket.send(json.dumps(ack_payload))
        logger.debug(f"✅ Sent ACK for envelope {envelope_id}")
    
    async def handle_message_event(self, event: dict):
        """Handle message events and create GitHub issues or comments"""
        # Skip bot messages
        if event.get("bot_id") or event.get("subtype") == "bot_message":
            return
        
        # Skip message updates/deletes
        if event.get("subtype") in ["message_changed", "message_deleted"]:
            return
        
        # Create SlackMessage object
        message = SlackMessage(
            user=event.get("user", "Unknown"),
            channel=event.get("channel", "Unknown"),
            text=event.get("text", ""),
            ts=event.get("ts", ""),
            thread_ts=event.get("thread_ts"),
            team_domain=self.team_domain
        )
        
        # Enrich with user and channel info
        try:
            user_info = await self.api_client.get_user_info(message.user)
            message.user_name = user_info.get('name', message.user)
            
            channel_info = await self.api_client.get_channel_info(message.channel)
            message.channel_name = channel_info.get('name', message.channel)
        except Exception as e:
            logger.warning(f"Could not enrich message info: {e}")
        
        # Process message (create issue or add comment)
        if message.is_thread_reply:
            logger.info(f"💬 Thread reply detected in #{message.channel_name}")
        else:
            logger.info(f"📝 New parent message detected in #{message.channel_name}")
        
        await self.ticket_creator.process_message(message, self.api_client)
    
    async def handle_websocket_message(self, message: str):
        """Handle incoming WebSocket messages"""
        try:
            data = json.loads(message)
            event_type = data.get("type", "unknown")
            envelope_id = data.get("envelope_id")
            
            # Send acknowledgment
            if envelope_id:
                await self.send_ack(envelope_id)
            
            # Handle different event types
            if event_type == "hello":
                logger.info("🎉 Socket Mode connection established")
                await self.test_permissions()
            
            elif event_type == "disconnect":
                reason = data.get("reason", "unknown")
                logger.warning(f"🔌 Slack requested disconnect: {reason}")
            
            elif event_type == "events_api":
                # Handle message events
                event = data.get("payload", {}).get("event", {})
                if event.get("type") == "message":
                    await self.handle_message_event(event)
            
            # Print formatted event
            formatted_event = self.event_formatter.format_event(data)
            if formatted_event:
                timestamp = datetime.now().strftime("%H:%M:%S")
                #print(f"[{timestamp}] {formatted_event}")
        
        except json.JSONDecodeError:
            logger.error(f"Failed to decode message: {message[:200]}")
        except Exception as e:
            logger.error(f"Error handling message: {e}")
    
    async def connect(self):
        """Connect to Slack Socket Mode"""
        try:
            # Always get a fresh gateway URL (they expire)
            self.gateway_url = await self.get_gateway_url()
            
            logger.info("🔌 Connecting to Slack Socket Mode...")
            
            # Connect with ping timeout to detect stale connections
            async with websockets.connect(
                self.gateway_url,
                ping_interval=20,
                ping_timeout=10
            ) as websocket:
                self.websocket = websocket
                logger.info("✅ Connected to Slack Socket Mode")
                
                # Wait for messages with a timeout to detect stuck connections
                hello_received = False
                async for message in websocket:
                    if not hello_received:
                        # First message should be hello
                        data = json.loads(message)
                        if data.get("type") == "hello":
                            hello_received = True
                            logger.info("👋 Received hello, connection active")
                    
                    await self.handle_websocket_message(message)
        
        except ConnectionClosed as e:
            logger.warning(f"🔌 Connection closed: {e.code} {e.reason}")
            self.gateway_url = None  # Force new URL on reconnect
        except asyncio.TimeoutError:
            logger.error("⏱️ Connection timeout - no messages received")
            self.gateway_url = None
        except Exception as e:
            logger.error(f"❌ Connection error: {type(e).__name__}: {e}")
            self.gateway_url = None
    
    async def run(self):
        """Run the gateway with auto-reconnect"""
        retry_count = 0
        
        while True:  # Infinite retry loop
            try:
                logger.info(f"🔄 Connection attempt #{retry_count + 1}")
                await self.connect()
                # If connect() returns normally, reset retry count
                retry_count = 0
                logger.info("🔄 Connection ended normally, reconnecting...")
            except KeyboardInterrupt:
                logger.info("🛑 Received interrupt signal")
                raise
            except Exception as e:
                retry_count += 1
                wait_time = min(retry_count * 2, 30)  # Max 30 seconds
                logger.error(f"❌ Connection failed (attempt {retry_count}): {type(e).__name__}: {e}")
                logger.info(f"⏳ Retrying in {wait_time} seconds...")
                await asyncio.sleep(wait_time)
                
                # Reset retry count after too many failures
                if retry_count >= 10:
                    logger.warning("⚠️ Too many failures, resetting retry counter")
                    retry_count = 0
                    await asyncio.sleep(60)  # Longer wait before starting fresh


# ======================== Main ========================

async def main():
    """Main function"""
    print("💬 Slack Gateway with GitHub Integration v2")
    print("📋 Features:")
    print("  • Creates GitHub issues from parent Slack messages")
    print("  • Adds comments to issues from thread replies")
    print("  • Uses labels: platform/slack, slack/channel/{name}")
    print("🛑 Press Ctrl+C to stop")
    print("-" * 50)
    
    # Initialize token manager
    token_manager = TokenManager()
    
    # Create and run gateway
    gateway = SlackGateway(token_manager)
    
    try:
        await gateway.run()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
        logger.info("User requested shutdown")
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")


if __name__ == "__main__":
    # Check dependencies
    try:
        import websockets
        import aiohttp
    except ImportError:
        print("❌ Missing dependencies. Install with:")
        print("pip install websockets aiohttp")
        exit(1)
    
    asyncio.run(main())
