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
from indexer.opensearch_indexer import OpenSearchIndexer
from assigner.assigner import IssueAssigner
from logging_config import setup_logger
from token_manager import TokenManager as CentralTokenManager

# Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(SCRIPT_DIR, 'discord_gateway.log')

# Discord API endpoints
DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_GATEWAY_VERSION = 10
DISCORD_ENCODING = "json"

# GitHub API endpoints
GITHUB_API_BASE = "https://api.github.com"
GITHUB_REPO = os.environ.get('GITHUB_REPO', 'wazuh/community-dev')

# Get tokens from centralized token manager
token_manager = CentralTokenManager()
DISCORD_TOKEN = token_manager.require_token('discord')

# Gateway opcodes
GATEWAY_OPCODES = {
    0: "DISPATCH",           # Receive
    1: "HEARTBEAT",          # Send/Receive
    2: "IDENTIFY",           # Send
    #3: "PRESENCE_UPDATE",    # Send
    4: "VOICE_STATE_UPDATE", # Send
    6: "RESUME",             # Send
    7: "RECONNECT",          # Receive
    8: "REQUEST_GUILD_MEMBERS", # Send
    9: "INVALID_SESSION",    # Receive
    10: "HELLO",             # Receive
    11: "HEARTBEAT_ACK",     # Receive
}

# Setup logging using centralized config
logger = setup_logger("Collector.Discord", log_file=LOG_FILE)


# ======================== Data Classes ========================

@dataclass
class DiscordMessage:
    """Represents a Discord message"""
    id: str
    channel_id: str
    author_id: str
    author_username: str
    content: str
    timestamp: str
    guild_id: Optional[str] = None
    channel_name: Optional[str] = None
    thread_id: Optional[str] = None
    
    @property
    def is_thread_reply(self) -> bool:
        """Check if this is in a thread"""
        return self.thread_id is not None
    
    def get_permalink(self) -> str:
        """Build Discord permalink for this message"""
        guild = self.guild_id or '@me'
        return f"https://discord.com/channels/{guild}/{self.channel_id}/{self.id}"


# ======================== Database Manager ========================

# ========================
# Message tracking now handled exclusively via OpenSearch
# Parent-child relationships stored in tickets-raw-v1.0 index
# ========================


# ======================== GitHub Ticket Creator ========================

class GitHubTicketCreator:
    """Creates GitHub issues from Discord messages"""
    
    def __init__(self, github_token: Optional[str], repo: str = GITHUB_REPO):
        self.github_token = ''.join(github_token.split()) if github_token else None
        self.repo = repo
        self.enabled = self.github_token is not None and len(self.github_token) > 0
        
        # Initialize OpenSearch indexer - this is our source of truth
        self.indexer = OpenSearchIndexer()
        
        # Cache for channel names to avoid repeated API calls
        self.channel_cache = {}
        
        # Cache for user names to avoid repeated API calls
        self.user_cache = {}
        
        if not self.enabled:
            logger.warning("⚠️  GitHub integration disabled (no token found)")
        else:
            logger.info(f"✅ GitHub integration enabled for repo: {repo}")
    
    async def get_channel_name(self, channel_id: str) -> Optional[str]:
        """Get channel name from Discord API"""
        # Check cache first
        if channel_id in self.channel_cache:
            return self.channel_cache[channel_id]
        
        try:
            url = f"{DISCORD_API_BASE}/channels/{channel_id}"
            headers = {'Authorization': f'Bot {DISCORD_TOKEN}'}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        channel_name = data.get('name', channel_id)
                        self.channel_cache[channel_id] = channel_name
                        logger.debug(f"✅ Resolved channel {channel_id} -> {channel_name}")
                        return channel_name
                    else:
                        logger.warning(f"⚠️  Could not resolve channel {channel_id}: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"❌ Error resolving channel name: {e}")
            return None
    
    async def get_user_info(self, user_id: str) -> Optional[str]:
        """Get user name from Discord API"""
        # Check cache first
        if user_id in self.user_cache:
            return self.user_cache[user_id]
        
        try:
            url = f"{DISCORD_API_BASE}/users/{user_id}"
            headers = {'Authorization': f'Bot {DISCORD_TOKEN}'}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        username = data.get('username', user_id)
                        self.user_cache[user_id] = username
                        logger.debug(f"✅ Resolved user {user_id} -> {username}")
                        return username
                    else:
                        logger.warning(f"⚠️  Could not resolve user {user_id}: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"❌ Error resolving user name: {e}")
            return None
    
    async def replace_user_mentions(self, content: str) -> str:
        """Replace Discord user mentions <@123456> with actual usernames"""
        import re
        
        # Find all user mentions in the format <@123456>
        mention_pattern = r'<@(\d+)>'
        mentions = re.findall(mention_pattern, content)
        
        # Resolve each user ID
        for user_id in mentions:
            username = await self.get_user_info(user_id)
            if username:
                # Replace <@123456> with @username
                content = content.replace(f'<@{user_id}>', f'@{username}')
            else:
                # If resolution fails, keep the mention but make it clearer
                content = content.replace(f'<@{user_id}>', f'@user-{user_id}')
        
        return content
    
    async def process_message(self, message: DiscordMessage) -> Optional[dict]:
        """Process a Discord message: create issue or add comment"""
        if not self.enabled:
            logger.debug("GitHub integration disabled, skipping")
            return None
        
        # For Discord, threads are separate from parent messages
        # We'll treat thread_id as the parent message ID
        if message.is_thread_reply:
            return await self._add_thread_comment(message)
        else:
            return await self._create_parent_issue(message)
    
    async def _create_parent_issue(self, message: DiscordMessage) -> Optional[dict]:
        """Create a GitHub issue for a parent message"""
        # Resolve user mentions in content
        resolved_content = await self.replace_user_mentions(message.content)
        message.content = resolved_content
        
        title = self._build_title(message)
        body = self._build_body(message)
        labels = self._get_labels(message)
        
        # Resolve channel name
        channel_name = await self.get_channel_name(message.channel_id)
        
        logger.info(f"📝 Creating new GitHub issue for Discord message {message.id}")
        logger.debug(f"🔍 Repository: {self.repo}")
        logger.debug(f"🔍 Title: {title}")
        logger.debug(f"🔍 Labels: {labels}")
        logger.debug(f"🔍 Channel: {channel_name}")
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
                        
                        # Index parent document in OpenSearch (our source of truth)
                        try:
                            parent_doc = self._create_discord_parent_document(
                                message, issue_number, issue_url, labels, channel_name
                            )
                            self.indexer.index_parent(parent_doc)
                            logger.info(f"✅ Created GitHub issue #{issue_number} and indexed in OpenSearch")
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
    
    async def _add_thread_comment(self, message: DiscordMessage) -> Optional[dict]:
        """Add a comment to the parent issue for a thread reply"""
        # Resolve user mentions in content
        resolved_content = await self.replace_user_mentions(message.content)
        message.content = resolved_content
        
        # Find the parent document in OpenSearch using thread_id
        # First try by message_id (direct lookup)
        parent_doc_id = f"discord_{message.thread_id}"
        parent_doc = self.indexer.get_parent_document(parent_doc_id)
        
        # If not found by message_id, search by channel_id
        # (the message.channel_id when in a thread IS the thread's channel_id)
        if not parent_doc:
            logger.info(f"🔍 Parent not found by message_id, searching by channel_id: {message.channel_id}")
            parent_doc = self.indexer.search_parent_by_channel(message.channel_id)
        
        if not parent_doc:
            logger.warning(f"⚠️  No parent document found in OpenSearch for thread {message.thread_id}")
            logger.info(f"   Tried message_id: {parent_doc_id}")
            logger.info(f"   Tried channel_id: {message.channel_id}")
            return None
        
        issue_number = parent_doc.get('github_issue_number')
        issue_url = parent_doc.get('github_issue_url')
        parent_message_id = parent_doc.get('discord_message_id')
        channel_name = parent_doc.get('channel')  # Get normalized channel name from parent
        
        if not issue_number or not issue_url:
            logger.error(f"❌ Parent document found but missing GitHub info: {parent_doc}")
            return None
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
                            comment_doc = self._create_discord_comment_document(
                                message, comment_data.get('id'), issue_number, issue_url, parent_message_id, channel_name
                            )
                            # Use the actual parent message_id from the found document
                            parent_id = f"discord_{parent_message_id}"
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
    
    def _build_title(self, message: DiscordMessage) -> str:
        """Build issue title from message"""
        if not message.content or not message.content.strip():
            # Fallback title when content is empty - use channel info
            return f"Discord message in thread"
        
        # Use first 100 characters of the message content
        title = message.content.replace('\n', ' ').strip()
        text_preview = title[:100] if len(title) > 100 else title
        return text_preview
    
    def _build_body(self, message: DiscordMessage) -> str:
        """Build issue body from message"""
        user_info = f"@{message.author_username}"
        channel_info = f"#{message.channel_name}" if message.channel_name else message.channel_id
        permalink = message.get_permalink()
        
        body = f"""## Discord Message

**Channel:** {channel_info}
**User:** {user_info}
**Message ID:** {message.id}
**Permalink:** {permalink}

### Message Content:

{message.content}

"""
        return body
    
    def _build_comment_body(self, message: DiscordMessage) -> str:
        """Build comment body for thread replies"""
        user_info = f"@{message.author_username}"
        permalink = message.get_permalink()
        
        body = f"""### Thread Reply from {user_info}

**User:** {user_info}
**Message ID:** {message.id}
**Permalink:** {permalink}

{message.content}

"""
        return body
    
    def _get_labels(self, message: DiscordMessage) -> List[str]:
        """Determine labels for the issue"""
        labels = ['platform/discord']
        
        if message.channel_name:
            labels.append(f'discord/channel/{message.channel_name}')
        
        return labels
    
    def _create_discord_parent_document(self, message: DiscordMessage, 
                                       issue_number: int, issue_url: str,
                                       labels: List[str], channel_name: Optional[str] = None) -> Dict:
        """Create a parent document for OpenSearch"""
        return {
            'id': f"discord_{message.id}",
            'platform': 'discord',
            'document_type': 'parent',
            'created_at': message.timestamp,
            'discord_message_id': message.id,
            'discord_channel_id': message.channel_id,
            'discord_channel_name': message.channel_name,
            'channel': channel_name or message.channel_id,  # Normalized channel field
            'discord_guild_id': message.guild_id,
            'discord_author_id': message.author_id,
            'author': message.author_username,
            'discord_author_username': message.author_username,
            'discord_permalink': message.get_permalink(),
            'content': message.content,
            'record_type': 'parent',  # For easier filtering
            'status': 'open',  # Default status for new parent documents
            'github_issue_number': issue_number,
            'github_issue_url': issue_url,
            'labels': labels
        }
    
    def _create_discord_comment_document(self, message: DiscordMessage,
                                         github_comment_id: Optional[int],
                                         github_issue_number: int,
                                         github_issue_url: str,
                                         parent_message_id: Optional[str] = None,
                                         channel_name: Optional[str] = None) -> Dict:
        """Create a comment document for OpenSearch"""
        # Use provided parent_message_id or fall back to thread_id
        parent_id = parent_message_id if parent_message_id else message.thread_id
        
        return {
            'id': f"discord_{message.id}",
            'parent_id': f"discord_{parent_id}",
            'platform': 'discord',
            'document_type': 'comment',
            'created_at': message.timestamp,
            'discord_message_id': message.id,
            'discord_channel_id': message.channel_id,
            'channel': channel_name or message.channel_id,  # Normalized channel field
            'discord_thread_id': message.thread_id,
            'discord_author_id': message.author_id,
            'discord_author_username': message.author_username,
            'author': message.author_username,
            'discord_permalink': message.get_permalink(),
            'content': message.content,
            'record_type': 'comment',  # For easier filtering
            'github_comment_id': github_comment_id,
            'github_issue_number': github_issue_number,
            'github_issue_url': github_issue_url
        }


class DiscordGateway:
    def __init__(self):
        self.token = DISCORD_TOKEN
        self.session_id = None
        self.sequence = None
        self.heartbeat_interval = None
        self.websocket = None
        self.heartbeat_task = None
        self.gateway_url = None
        
        # Track thread to parent message mapping
        self.thread_to_parent = {}  # thread_id -> parent_message_id
        
        # Initialize GitHub ticket creator
        github_token = token_manager.get_token('github')
        self.ticket_creator = GitHubTicketCreator(github_token)
        
    async def get_gateway_url(self) -> str:
        """Get the Gateway URL from Discord API"""
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{DISCORD_API_BASE}/gateway/bot", 
                                 headers={"Authorization": f"Bot {self.token}"}) as response:
                if response.status == 200:
                    data = await response.json()
                    url = data["url"]
                    logger.info(f"✅ Got gateway URL: {url}")
                    logger.info(f"📊 Recommended shards: {data.get('shards', 1)}")
                    logger.info(f"🔄 Session start limit: {data.get('session_start_limit', {})}")
                    return url
                else:
                    raise Exception(f"Failed to get gateway URL: {response.status}")

    async def send_heartbeat(self):
        """Send heartbeat to maintain connection"""
        while True:
            if self.websocket and not self.websocket.closed:
                heartbeat_payload = {
                    "op": 1,
                    "d": self.sequence
                }
                await self.websocket.send(json.dumps(heartbeat_payload))
                logger.debug("💓 Sent heartbeat")
            
            await asyncio.sleep(self.heartbeat_interval / 1000)

    async def send_identify(self):
        """Send IDENTIFY payload to authenticate"""
        # Gateway Intents - need MESSAGE_CONTENT (1 << 15) to read message content
        # GUILDS (1 << 0) = 1
        # GUILD_MESSAGES (1 << 9) = 512
        # MESSAGE_CONTENT (1 << 15) = 32768
        # DIRECT_MESSAGES (1 << 12) = 4096
        intents = (1 << 0) | (1 << 9) | (1 << 15) | (1 << 12)  # 36865
        
        identify_payload = {
            "op": 2,
            "d": {
                "token": self.token,
                "intents": intents,
                "properties": {
                    "os": "linux",
                    "browser": "discord_gateway_client",
                    "device": "discord_gateway_client"
                }
            }
        }
        await self.websocket.send(json.dumps(identify_payload))
        logger.info(f"🔐 Sent IDENTIFY payload with intents: {intents}")

    def format_event(self, event_data: Dict) -> str:
        """Format event data for console output"""
        op = event_data.get("op", "unknown")
        op_name = GATEWAY_OPCODES.get(op, f"UNKNOWN_OP_{op}")
        
        if op == 0:  # DISPATCH
            event_type = event_data.get("t", "UNKNOWN_EVENT")
            sequence = event_data.get("s")
            data = event_data.get("d", {})
            
            # Format different event types
            if event_type == "MESSAGE_CREATE":
                author = data.get("author", {})
                channel_id = data.get("channel_id")
                content = data.get("content", "")
                
                return f"📝 MESSAGE_CREATE [#{channel_id}] {author.get('username', 'Unknown')}: {content[:100]}"
                
            elif event_type == "MESSAGE_UPDATE":
                author = data.get("author", {})
                channel_id = data.get("channel_id")
                content = data.get("content", "")
                
                return f"✏️  MESSAGE_UPDATE [#{channel_id}] {author.get('username', 'Unknown')}: {content[:100]}"
                
            elif event_type == "MESSAGE_DELETE":
                channel_id = data.get("channel_id")
                message_id = data.get("id")
                
                return f"🗑️  MESSAGE_DELETE [#{channel_id}] Message ID: {message_id}"
                
            elif event_type == "THREAD_CREATE":
                thread_name = data.get("name", "Unknown Thread")
                parent_id = data.get("parent_id")
                
                return f"🧵 THREAD_CREATE [#{parent_id}] Thread: {thread_name}"
                
            elif event_type == "THREAD_UPDATE":
                thread_name = data.get("name", "Unknown Thread")
                thread_id = data.get("id")
                
                return f"🧵 THREAD_UPDATE [#{thread_id}] Thread: {thread_name}"
                
            elif event_type == "GUILD_MEMBER_ADD":
                user = data.get("user", {})
                guild_id = data.get("guild_id")
                
                return f"👋 GUILD_MEMBER_ADD [Guild: {guild_id}] User: {user.get('username', 'Unknown')}"
                
            elif event_type == "TYPING_START":
                user_id = data.get("user_id")
                channel_id = data.get("channel_id")
                
                return f"⌨️  TYPING_START [#{channel_id}] User: {user_id}"
                
            elif event_type == "READY":
                user = data.get("user", {})
                guilds = len(data.get("guilds", []))
                
                return f"🚀 READY - Bot: {user.get('username', 'Unknown')} | Guilds: {guilds}"
            
            elif event_type == "PRESENCE_UPDATE":
                # Skip presence updates (too noisy)
                return ""
                
            else:
                #return ""
                return f"📡 {event_type} [Seq: {sequence}] - {json.dumps(data, indent=2)[:200]}..."
                
        elif op == 10:  # HELLO
            heartbeat_interval = event_data.get("d", {}).get("heartbeat_interval", 0)
            return f"👋 HELLO - Heartbeat interval: {heartbeat_interval}ms"
            
        elif op == 11:  # HEARTBEAT_ACK
            return f"💓 HEARTBEAT_ACK"
            
        elif op == 1:  # HEARTBEAT
            return f"💓 HEARTBEAT"
            
        elif op == 9:  # INVALID_SESSION
            resumable = event_data.get("d", False)
            return f"❌ INVALID_SESSION - Resumable: {resumable}"
            
        elif op == 7:  # RECONNECT
            return f"🔄 RECONNECT"
            
        else:
            return ""
            #return f"📡 {op_name} - {json.dumps(event_data, indent=2)[:200]}..."

    async def handle_message(self, message: str):
        """Handle incoming WebSocket messages"""
        try:
            data = json.loads(message)
            op = data.get("op")
            
            # Update sequence number for DISPATCH events
            if op == 0:
                self.sequence = data.get("s")
            
            # Handle different opcodes
            if op == 10:  # HELLO
                hello_data = data.get("d", {})
                self.heartbeat_interval = hello_data.get("heartbeat_interval", 41250)
                logger.info(f"🎯 Heartbeat interval set to {self.heartbeat_interval}ms")
                
                # Cancel old heartbeat task if exists
                if self.heartbeat_task and not self.heartbeat_task.done():
                    self.heartbeat_task.cancel()
                
                # Start heartbeat task
                self.heartbeat_task = asyncio.create_task(self.send_heartbeat())
                
                # Send IDENTIFY (only if we don't have a valid session)
                if not self.session_id:
                    await self.send_identify()
                else:
                    logger.debug("Skipping IDENTIFY, already have session_id")
                
            elif op == 0:  # DISPATCH
                event_type = data.get("t")
                if event_type == "READY":
                    ready_data = data.get("d", {})
                    self.session_id = ready_data.get("session_id")
                    user_info = ready_data.get("user", {})
                    logger.info(f"🎉 Bot ready: {user_info.get('username')}#{user_info.get('discriminator')}")
                elif event_type == "THREAD_CREATE":
                    thread_data = data.get("d", {})
                    thread_id = thread_data.get("id")
                    # Try to get the parent message ID (the message that started the thread)
                    # In some cases this is in owner_id or we need to track it from MESSAGE_CREATE
                    parent_id = thread_data.get("owner_id")  # This is often the starter message ID
                    if parent_id:
                        self.thread_to_parent[thread_id] = parent_id
                        logger.info(f"🧵 Tracked thread {thread_id} -> parent message {parent_id}")
                    
            elif op == 11:  # HEARTBEAT_ACK
                logger.debug("💓 Received heartbeat ACK")
                
            elif op == 9:  # INVALID_SESSION
                resumable = data.get("d", False)
                logger.error(f"❌ Invalid session, resumable: {resumable}")
                
                # Clean session state
                self.session_id = None
                self.sequence = None
                
                # If not resumable, we need to reconnect with a fresh IDENTIFY
                if not resumable:
                    logger.warning("⚠️ Session not resumable, forcing reconnection...")
                    # Wait a bit before reconnecting (Discord recommends 1-5 seconds)
                    await asyncio.sleep(3)
                    # Close the websocket to trigger reconnection
                    if self.websocket:
                        try:
                            await self.websocket.close()
                        except Exception as e:
                            logger.debug(f"Error closing websocket: {e}")
                
            elif op == 7:  # RECONNECT
                logger.warning("🔄 Discord requested reconnect")
                # Clean state and close to trigger reconnection
                self.session_id = None
                if self.websocket:
                    try:
                        await self.websocket.close()
                    except Exception as e:
                        logger.debug(f"Error closing websocket: {e}")
            
            # Print formatted event to console
            formatted_event = self.format_event(data)
            #print(f"[{asyncio.get_event_loop().time():.1f}] {formatted_event}")
            
            # Process MESSAGE_CREATE events for GitHub/OpenSearch
            if op == 0 and data.get("t") == "MESSAGE_CREATE":
                await self.handle_message_create(data.get("d", {}))
            
        except json.JSONDecodeError:
            logger.error(f"Failed to decode message: {message}")
        except Exception as e:
            logger.error(f"Error handling message: {e}")
    
    async def handle_message_create(self, event: dict):
        """Handle MESSAGE_CREATE events and create GitHub issues or comments"""
        logger.info(f"🔍 Processing MESSAGE_CREATE event")
        
        # Skip bot messages
        author = event.get("author", {})
        if author.get("bot", False):
            logger.info("  ⏭️  Skipping: Bot message")
            return
        
        # Skip certain system messages (but allow THREAD_STARTER_MESSAGE type=18 and type=19)
        msg_type = event.get("type", 0)
        if msg_type not in [0, 18, 19]:  # 0=DEFAULT, 18=THREAD_STARTER_MESSAGE, 19=REPLY
            logger.info(f"  ⏭️  Skipping: System message (type={msg_type})")
            return
        
        # Extract message data
        message_id = event.get("id")
        channel_id = event.get("channel_id")
        guild_id = event.get("guild_id")
        content = event.get("content", "")
        timestamp = event.get("timestamp", datetime.utcnow().isoformat())
        channel_type = event.get("channel_type", 0)
        position = event.get("position", 0)
        
        logger.info(f"  📋 Message ID: {message_id}")
        logger.info(f"  📋 Channel: {channel_id}")
        logger.info(f"  📋 Channel Type: {channel_type} (11=PUBLIC_THREAD, 12=PRIVATE_THREAD)")
        logger.info(f"  📋 Position: {position}")
        logger.info(f"  📋 Content length: {len(content)}")
        logger.info(f"  📋 Content preview: {content[:100] if content else '(empty)'}")
        
        # Check for referenced message (for thread starters with empty content)
        referenced_message = event.get("referenced_message")
        message_reference = event.get("message_reference")
        
        if referenced_message:
            logger.info(f"  🔗 Has referenced_message")
            ref_content = referenced_message.get("content", "")
            if ref_content:
                logger.info(f"  🔗 Using content from referenced message: {ref_content[:100]}")
                content = ref_content
            else:
                logger.info(f"  🔗 Referenced message has no content")
        
        # Skip position=1 messages in threads (they're duplicates of the thread starter)
        is_thread = channel_type in [11, 12]  # PUBLIC_THREAD or PRIVATE_THREAD
        if is_thread and position == 1 and not content.strip():
            logger.info("  ⏭️  Skipping: Thread starter duplicate (position=1, empty)")
            return
        
        # Determine if this is a thread message
        # channel_type 11 = PUBLIC_THREAD, 12 = PRIVATE_THREAD
        thread_id = None
        if is_thread:
            # This message is IN a thread
            # Look up which message created this thread
            parent_message_id = self.thread_to_parent.get(channel_id)
            if parent_message_id:
                thread_id = parent_message_id
                logger.info(f"  🧵 Message is in thread, parent message: {parent_message_id}")
            else:
                logger.info(f"  🧵 Message is in thread {channel_id} (parent unknown)")
                # Still treat it as a thread message, using channel_id as thread identifier
                thread_id = channel_id
        
        # Create DiscordMessage object
        discord_message = DiscordMessage(
            id=message_id,
            channel_id=channel_id,
            author_id=author.get("id", "Unknown"),
            author_username=author.get("username", "Unknown"),
            content=content,
            timestamp=timestamp,
            guild_id=guild_id,
            channel_name=None,  # Would need to fetch from API
            thread_id=thread_id
        )
        
        logger.info(f"  ✅ Message passed all checks, processing...")
        
        # Process message (create issue or add comment)
        try:
            await self.ticket_creator.process_message(discord_message)
        except Exception as e:
            logger.error(f"❌ Error processing Discord message: {e}")

    async def connect(self):
        """Connect to Discord Gateway"""
        try:
            # Always get a fresh gateway URL
            self.gateway_url = await self.get_gateway_url()
            
            # Reset connection state
            self.session_id = None
            self.sequence = None
            
            # Build WebSocket URL
            ws_url = f"{self.gateway_url}/?v={DISCORD_GATEWAY_VERSION}&encoding={DISCORD_ENCODING}"
            logger.info(f"🔌 Connecting to: {ws_url}")
            
            # Connect to WebSocket with ping/pong
            async with websockets.connect(
                ws_url,
                ping_interval=20,
                ping_timeout=10
            ) as websocket:
                self.websocket = websocket
                logger.info("✅ Connected to Discord Gateway")
                
                # Listen for messages
                async for message in websocket:
                    await self.handle_message(message)
                    
        except ConnectionClosed as e:
            logger.warning(f"🔌 Connection closed: {e.code} {e.reason}")
            self.gateway_url = None
        except asyncio.TimeoutError:
            logger.error("⏱️ Connection timeout - no messages received")
            self.gateway_url = None
        except Exception as e:
            logger.error(f"❌ Connection error: {type(e).__name__}: {e}")
            self.gateway_url = None
        finally:
            if self.heartbeat_task:
                self.heartbeat_task.cancel()

    async def run(self):
        """Run the gateway client with auto-reconnect"""
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

async def main():
    """Main function"""
    print("🤖 Discord Gateway Client Starting...")
    print("📋 This will show real-time Discord events")
    print("🛑 Press Ctrl+C to stop")
    print("-" * 50)
    
    gateway = DiscordGateway()
    
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
    
    # Run the gateway client
    asyncio.run(main())