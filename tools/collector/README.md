# Community Tools - Collectors

This repository contains various collectors and tools for managing community interactions across different platforms.

## Table of Contents

- [Quick Start](#quick-start)
- [Collectors](#collectors)
  - [Slack Gateway](#slack-gateway)
  - [Discord Gateway](#discord-gateway)
  - [Main Orchestrator](#main-orchestrator)
- [Architecture](#architecture)
- [Getting Started](#getting-started)

---

## Quick Start

Run all gateways concurrently:

```bash
cd tools/collector
python main.py
```

This will start both Slack and Discord gateways simultaneously, creating GitHub issues and indexing to OpenSearch.

## Configuration

### Environment Variables

You can configure the gateways using environment variables:

```bash
# GitHub Repository (required)
export GITHUB_REPO=wazuh/community

# Logging level (optional, default: INFO)
export LOG_LEVEL=DEBUG  # Use DEBUG to see detailed API calls

# Run with configuration
python main.py
```

Or create a `.env` file in `tools/` (copy from `../.env.example`):

```bash
cd tools
cp .env.example .env
# Edit .env with your values
```

Then the configuration will be loaded automatically.

### Required Configuration

1. **GitHub Repository**: Set `GITHUB_REPO` environment variable
   - Format: `owner/repository`
   - Example: `wazuh/community` or `wazuh/community-dev`
   - Default: `wazuh/community-dev`

2. **Token Files**: Create these in `tools/collector/`
   - `.token_slack` - Slack Bot Token
   - `.token_slack_app` - Slack App Token (for Socket Mode)
   - `.token_discord` - Discord Bot Token
   - `.token_github` - GitHub Personal Access Token

3. **OpenSearch Token**: Create in `tools/indexer/`
   - `.token_opensearch` - OpenSearch password

## Debugging

### Enable Debug Logging

To see detailed information about API calls, authentication, and errors:

```bash
export LOG_LEVEL=DEBUG
python main.py
```

Debug logs will show:
- ✅ Full GitHub API URLs being called
- ✅ Token prefixes (first 10 characters)
- ✅ Request payloads
- ✅ Detailed error responses from GitHub
- ✅ Response headers

### Common Issues

#### GitHub 404 Error

If you see:
```
❌ Failed to create GitHub issue
   Status: 404
   URL: https://api.github.com/repos/owner/repo/issues
   Repository: owner/repo
```

**Solutions:**
1. Verify the repository exists and you have access
2. Check your GitHub token has correct permissions (`repo` scope)
3. Verify the `GITHUB_REPO` environment variable is correct
4. Test token manually:
   ```bash
   curl -H "Authorization: token YOUR_TOKEN" \
        https://api.github.com/repos/OWNER/REPO
   ```

#### GitHub 401/403 Error

- Check token is valid and not expired
- Verify token has `repo` scope (full repository access)
- Check if repository is private (token needs access)

### Verify GitHub Configuration

Before running the gateways, verify your GitHub configuration:

```bash
cd tools/collector
python verify_github.py
```

This will check:
- ✅ GitHub token is valid
- ✅ Token has correct permissions
- ✅ Repository exists and is accessible
- ✅ Token can create issues in the repository

Example output:
```
✅ Token is valid
   User: your-username
   Scopes: repo, admin:org

✅ Repository exists and is accessible
   Full Name: wazuh/community
   Private: False
   Permissions:
     - Pull: True
     - Push: True
```

### Test Components

Test that all components are configured correctly:

```bash
cd tools/collector
python test_components.py
```

This will verify:
- All dependencies are installed
- Token files exist and are readable
- Gateways can initialize successfully
- OpenSearch credentials are valid

---

## Collectors

### Main Orchestrator

**File:** `main.py`

The main orchestrator runs both Slack and Discord gateways concurrently with unified logging.

#### 🎯 Features

- **Concurrent execution** of multiple gateways
- **Unified logging** to console and file (`main_gateway.log`)
- **Graceful shutdown** with Ctrl+C
- **Auto-recovery** - continues running if one gateway fails
- **Smart initialization** - runs only available gateways

#### 🚀 Usage

```bash
# Run all available gateways
python main.py

# Or make it executable
chmod +x main.py
./main.py
```

The orchestrator will:
1. Initialize available gateways (Slack, Discord)
2. Start them concurrently
3. Monitor and log all activity
4. Handle reconnections automatically

---

### Slack Gateway

The Slack Gateway automatically creates GitHub issues from Slack messages, adds thread replies as comments, and indexes everything to OpenSearch.

#### 🎯 Features

1. **Parent Messages → GitHub Issues + OpenSearch**
   - Each new message (non-thread) creates a GitHub issue
   - Indexed to OpenSearch as parent document
   - Title: Message text (max 100 characters)
   - Automatic labels: `platform/slack`, `slack/channel/{channel-name}`

2. **Thread Replies → Comments + Child Documents**
   - Thread replies are added as comments to the parent issue
   - Indexed to OpenSearch as child documents
   - Maintains parent-child relationship in OpenSearch

3. **SQLite Database**
   - Stores relationship: `slack_message_ts → github_issue_number`
   - Enables finding parent issue to add comments
   - File: `slack_github_mapping.db`

4. **OpenSearch Integration**
   - Parent documents: Main messages/issues
   - Child documents: Thread replies/comments
   - Index: `tickets-raw-v1.0`
   - Full text search capabilities

---

### Discord Gateway

The Discord Gateway provides the same functionality as Slack for Discord messages.

#### 🎯 Features

1. **Messages → GitHub Issues + OpenSearch**
   - Creates GitHub issues from Discord messages
   - Indexed to OpenSearch as parent document
   - Automatic labels: `platform/discord`, `discord/channel/{channel-name}`

2. **Thread Replies → Comments + Child Documents**
   - Thread messages added as comments
   - Indexed to OpenSearch as child documents

3. **SQLite Database**
   - Stores relationship: `discord_message_id → github_issue_number`
   - File: `discord_github_mapping.db`

4. **OpenSearch Integration**
   - Same parent-child structure as Slack
   - Index: `tickets-raw-v1.0`

#### 📋 Requirements

```bash
pip install websockets aiohttp
```

#### 🔧 Configuration

##### 1. Required Tokens

Create these files in `tools/collector/`:

**`.token_slack` (Bot Token)**
```
xoxb-your-bot-token
```

**`.token_slack_app` (App Token)**
```
xapp-your-app-token
```

**`.token_github` (GitHub Personal Access Token)**
```
# Comments are allowed
github_pat_your_token_here
```

**Required GitHub Token Scopes:**
- `repo` - Full control of private repositories

##### 2. Slack App Configuration

At https://api.slack.com/apps:

**OAuth & Permissions → Bot Token Scopes:**
- `channels:read`
- `channels:history`
- `users:read`

**Socket Mode:**
- ✅ Enabled
- App-Level Token with scope: `connections:write`

**Event Subscriptions → Subscribe to bot events:**
- `message.channels` - Messages in channels

##### 3. GitHub Repository Configuration

Edit in code (line 27):
```python
GITHUB_REPO = "wazuh/wazuh-community-dev"  # Change to your repo
```

#### 🚀 Usage

```bash
cd tools/collector
python3 slack_gw_v2.py
```

#### 📊 Workflow

##### Parent Message (New)
```
User in Slack: "How do I configure Wazuh indexer?"
    ↓
GitHub Issue created:
    Title: "How do I configure Wazuh indexer?"
    Labels: ["platform/slack", "slack/channel/wazuh-indexer"]
    Body: Channel info, user, timestamp, message
    ↓
DB: slack_ts → github_issue_#123
```

##### Thread Reply
```
Another user replies in thread
    ↓
Search DB: What's the parent issue?
    ↓
GitHub Comment added to issue #123:
    Body: User, timestamp, reply text
```

#### 🗄️ Database Structure

##### Table: `message_mapping`

| Field | Type | Description |
|-------|------|-------------|
| `slack_message_ts` | TEXT (PK) | Slack message timestamp |
| `slack_channel_id` | TEXT | Slack channel ID |
| `slack_channel_name` | TEXT | Channel name |
| `github_issue_number` | INTEGER | GitHub issue number |
| `github_issue_url` | TEXT | Issue URL |
| `created_at` | TIMESTAMP | Creation date |

#### 📝 Example Created Issue

**Title:**
```
How do I configure Wazuh indexer?
```

**Labels:**
- `platform/slack`
- `slack/channel/wazuh-indexer`

**Body:**
```markdown
## Slack Message

**Channel:** #wazuh-indexer
**User:** @john.doe
**Timestamp:** 1234567890.123456

### Message Content:

How do I configure Wazuh indexer?

---
*This issue was automatically created from a Slack message*
```

#### 📝 Example Thread Comment

```markdown
### Thread Reply from @jane.smith

**Timestamp:** 1234567890.234567

Here's the documentation: https://docs.wazuh.com/indexer

---
*This comment was automatically added from a Slack thread reply*
```

#### 🏗️ Class Architecture

##### `MessageDatabase`
- Manages SQLite
- Operations: `save_mapping()`, `get_parent_issue()`

##### `TokenManager`
- Loads and validates tokens
- Cleans whitespace/newlines

##### `SlackAPIClient`
- Slack REST client
- Methods: `get_user_info()`, `get_channel_info()`, etc.

##### `GitHubTicketCreator`
- Creates issues and comments
- Methods: `process_message()`, `_create_parent_issue()`, `_add_thread_comment()`

##### `SlackEventFormatter`
- Formats events for console
- Distinguishes parent messages vs. threads

##### `SlackGateway`
- Orchestrates entire flow
- WebSocket connection with Slack
- Auto-reconnection

#### 🐛 Troubleshooting

##### "GitHub integration disabled"
- Verify `.token_github` exists with a valid token
- Ensure token has `repo` scope

##### "No parent issue found for thread"
- Parent message didn't create an issue (possibly was a bot or edited message)
- Database doesn't have the record (may have been deleted)

##### "Failed to create GitHub issue: 401"
- Invalid or expired GitHub token
- Generate a new token at https://github.com/settings/tokens

##### "Bot is not a member of any channels"
- Invite bot to channels: `/invite @your_bot_name`
- Verify bot has `channels:read` and `channels:history` permissions

#### 📊 Logging

Logs are saved to:
- **Console**: Real-time events
- **File**: `slack_gateway.log` (complete log)

**Log Levels:**
- `INFO`: Important events (issues created, comments added)
- `WARNING`: Non-critical issues
- `ERROR`: Errors requiring attention

#### 🔒 Security

- ✅ Tokens stored in local files (not in code)
- ✅ `.token_*` files must be in `.gitignore`
- ✅ SQLite database is local (not shared)
- ✅ Token validation (whitespace/newline cleanup)

#### 📈 Future Improvements

- [ ] Add Slack reactions as GitHub labels
- [ ] Sync issue closure when thread is resolved
- [ ] Support for Slack file attachments
- [ ] Web dashboard for statistics
- [ ] Discord integration

---

### Discord Gateway

**Coming soon...**

---

## Architecture

The collector tools are built with a modular, class-based architecture:

```
┌─────────────────────────────────────────────┐
│          Collector Gateway                  │
│  (Slack, Discord, etc.)                     │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│          Message Processing                 │
│  • Event parsing                            │
│  • Thread detection                         │
│  • User enrichment                          │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│          Database Layer                     │
│  • Message-Issue mapping                    │
│  • Thread tracking                          │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│          GitHub Integration                 │
│  • Issue creation                           │
│  • Comment addition                         │
│  • Label management                         │
└─────────────────────────────────────────────┘
```

## Getting Started

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd community/tools/collector
   ```

2. **Install dependencies**
   ```bash
   pip install websockets aiohttp
   ```

3. **Configure tokens**
   - Create token files as described in each collector section
   - Never commit tokens to the repository

4. **Run a collector**
   ```bash
   python3 slack_gw_v2.py  # For Slack
   # python3 discord_gw.py  # For Discord (coming soon)
   ```

5. **Monitor logs**
   - Check console for real-time events
   - Review `*_gateway.log` files for detailed logs

---

## Contributing

When adding new collectors:

1. Follow the established class architecture
2. Implement proper error handling
3. Add comprehensive logging
4. Update this README with configuration details
5. Include example workflows

## License

[Add your license information here]


# Slack Gateway v2 - Installation and Execution Guide

## 📋 Description

Slack Gateway v2 is a tool that automatically creates GitHub issues from Slack messages, and adds comments to those issues when users reply in Slack threads.

### Main Features:
- ✅ Converts parent Slack messages into GitHub issues
- ✅ Converts thread replies into issue comments
- ✅ Maps Slack format (mrkdwn) to GitHub Markdown
- ✅ SQLite database to map messages to issues
- ✅ Automatic labels: `platform/slack`, `slack/channel/{name}`

---

## 🚀 Installation on Amazon Linux

### Step 1: Prepare the environment

```bash
# Update the system (optional but recommended)
sudo yum update -y

# Verify Python 3 is installed
python3 --version

# If Python 3.9+ is not installed:
# sudo yum install python3.9 -y
```

### Step 2: Create virtual environment

```bash
# Navigate to the collector directory
cd /home/ec2-user/community/tools/collector

# Create virtual environment
python3 -m venv venv

# Activate the virtual environment
source venv/bin/activate

# Your prompt should now show (venv) at the beginning
```

### Step 3: Install dependencies

```bash
# Ensure pip is up to date
pip install --upgrade pip

# Install dependencies from requirements.txt
pip install -r requirements.txt
```

---

## ⚙️ Configuration

### Create token files

You need three tokens for the application to work. Create the following files in `/home/ec2-user/community/tools/collector/`:

#### 1. `.token_slack` (Bot Token)

```bash
# Create file for Slack bot token
nano .token_slack
```

Content:
```
xoxb-your-bot-token-here
```

**How to get the Bot Token:**
1. Go to https://api.slack.com/apps
2. Select your app
3. Go to "OAuth & Permissions"
4. Copy the "Bot User OAuth Token" (starts with `xoxb-`)

#### 2. `.token_slack_app` (App-Level Token)

```bash
# Create file for app-level token
nano .token_slack_app
```

Content:
```
xapp-your-app-token-here
```

**How to get the App-Level Token:**
1. Go to https://api.slack.com/apps
2. Select your app
3. Go to "Basic Information" → "App-Level Tokens"
4. Generate a token with scope `connections:write`
5. Copy the token (starts with `xapp-`)

#### 3. `.token_github` (GitHub Personal Access Token)

```bash
# Create file for GitHub token
nano .token_github
```

Content:
```
ghp-your-github-token-here
```

**How to get the GitHub Token:**
1. Go to https://github.com/settings/tokens
2. Click "Generate new token" → "Generate new token (classic)"
3. Select scopes: `repo` (full repository access)
4. Generate and copy the token (starts with `ghp_` or `github_pat_`)

### Configure GitHub repository

Edit the `slack_gw_v2.py` file and modify line 23:

```python
GITHUB_REPO = "your-username/your-repository"  # Example: "wazuh/community"
```

### File permissions

```bash
# Ensure token files have correct permissions
chmod 600 .token_slack .token_slack_app .token_github
```

---

## 🏃 Execution

### Activate virtual environment (if not active)

```bash
cd /home/ec2-user/community/tools/collector
source venv/bin/activate
```

### Run the application

```bash
python3 slack_gw_v2.py
```

### Expected output

```
💬 Slack Gateway with GitHub Integration v2
📋 Features:
  • Creates GitHub issues from parent Slack messages
  • Adds comments to issues from thread replies
  • Uses labels: platform/slack, slack/channel/{name}
  • SQLite DB for message-issue mapping
🛑 Press Ctrl+C to stop
--------------------------------------------------
✅ Loaded Slack bot token
✅ Loaded Slack app token
✅ Loaded GitHub token
✅ Database initialized
✅ GitHub integration enabled for repo: your-username/your-repository
🔌 Connecting to Slack Socket Mode...
✅ Connected to Slack Socket Mode
[HH:MM:SS] 👋 HELLO - Socket Mode connection established
🤖 Bot authenticated as: your_bot
📍 Team: Your Team | URL: https://your-team.slack.com/
🏢 Team domain: your-team
📋 Bot is member of X channels:
  #channel-1 (ID: C123...)
  #channel-2 (ID: C456...)
```

### Stop the application

Press `Ctrl+C` to stop the service.

---

## 🔧 Slack App Configuration

For the application to work, your Slack App must have:

### Event Subscriptions (Socket Mode)
1. Enable Socket Mode in "Socket Mode"
2. Subscribe to events in "Event Subscriptions":
   - `message.channels` - Messages in public channels
   - `app_mention` - App mentions (optional)

### OAuth & Permissions - Bot Token Scopes
- `channels:read` - View public channels
- `channels:history` - Read channel messages
- `users:read` - Read user information
- `chat:write` - Send messages (optional)

### Install the app in workspace
1. In "Install App", install the app in your workspace
2. Invite the bot to channels: `/invite @your_bot`

---

## 📊 Database

The application automatically creates a SQLite database:

**File:** `slack_github_mapping.db`

**Table:** `message_mapping`
- `slack_message_ts` - Slack message timestamp
- `slack_channel_id` - Channel ID
- `slack_channel_name` - Channel name
- `github_issue_number` - Created issue number
- `github_issue_url` - Issue URL
- `created_at` - Creation date

---

## 📝 Logs

Logs are saved in:

**File:** `slack_gateway.log`

To view logs in real-time:

```bash
tail -f slack_gateway.log
```

---

## 🔄 Run as Service (Optional)

To keep the application running permanently, you can use systemd:

### Create systemd service

```bash
sudo nano /etc/systemd/system/slack-gateway.service
```

Content:

```ini
[Unit]
Description=Slack Gateway v2 - GitHub Integration
After=network.target

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/home/ec2-user/community/tools/collector
ExecStart=/home/ec2-user/community/tools/collector/venv/bin/python3 /home/ec2-user/community/tools/collector/slack_gw_v2.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Enable and run the service

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable slack-gateway

# Start the service
sudo systemctl start slack-gateway

# Check status
sudo systemctl status slack-gateway

# View service logs
sudo journalctl -u slack-gateway -f
```

### Useful service commands

```bash
# Stop the service
sudo systemctl stop slack-gateway

# Restart the service
sudo systemctl restart slack-gateway

# Disable the service
sudo systemctl disable slack-gateway
```

---

## 🐛 Troubleshooting

### Error: "No module named 'websockets'"

```bash
# Make sure the virtual environment is activated
source venv/bin/activate
pip install -r requirements.txt
```

### Error: "Slack API error: invalid_auth"

- Verify that tokens in `.token_slack` and `.token_slack_app` are correct
- Ensure there are no extra spaces or line breaks

### Error: "Bot is not a member of any channels"

```bash
# In Slack, invite the bot to channels:
/invite @your_bot_name
```

### Error creating GitHub issues

- Verify that the GitHub token has `repo` permissions
- Verify that the repository in `GITHUB_REPO` is correct
- Verify that the token has access to the repository

### App doesn't receive messages

1. Verify that Socket Mode is enabled
2. Verify Event Subscriptions
3. Verify that the bot has necessary scopes
4. Reinstall the app in the workspace

---

## 📚 File Structure

```
/home/ec2-user/community/tools/collector/
├── slack_gw_v2.py              # Main script
├── requirements.txt             # Python dependencies
├── README_slack_gw_v2.md       # This guide
├── .token_slack                 # Bot token (do not share)
├── .token_slack_app            # App-level token (do not share)
├── .token_github               # GitHub token (do not share)
├── slack_gateway.log           # Application logs
├── slack_github_mapping.db     # SQLite database
└── venv/                       # Virtual environment (generated)
```

---

## 🔒 Security

- **NEVER** share `.token_*` files
- **NEVER** commit them to Git (they are in .gitignore)
- Use restrictive permissions: `chmod 600 .token_*`
- Rotate tokens periodically
- Use tokens with minimum necessary permissions

---

## 📖 Usage

1. The bot listens to messages in channels where it's invited
2. When it detects a new message (not from a bot):
   - Creates a GitHub issue with the content
   - Saves the message-issue relationship in the DB
3. When it detects a thread reply:
   - Finds the parent issue in the DB
   - Adds a comment to the issue

**Example:**

```
Slack:
  #general: User1: "There's a problem with the installation"
    └─ User2: "I think it's due to the Python version"

GitHub:
  Issue #123: "There's a problem with the installation"
    Comment: "I think it's due to the Python version"
```

# Navigate to the directory
cd /home/ec2-user/community/tools/collector

# Activate virtual environment and run with nohup
source venv/bin/activate
nohup python3 slack_gw_v2.py > slack_gw_v2.out 2>&1 &

# To check if it's running
ps aux | grep slack_gw_v2.py

# To view logs
tail -f slack_gw_v2.out

# To stop the process
pkill -f slack_gw_v2.py

---

## 📞 Support

For issues or questions:
1. Check the logs: `tail -f slack_gateway.log`
2. Verify token configuration
3. Verify Slack App permissions
4. Consult Slack API documentation: https://api.slack.com/

---

## 📄 License

This project is part of Wazuh Community Tools.
