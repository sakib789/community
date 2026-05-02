# Community Assigner

Complete Python migration of the Google Apps Script system for GitHub issue assignment and team summary generation.

## 📋 Features

- **Summary Generation**: Creates Google Sheets spreadsheets with team statistics
- **Automatic Assignment**: Assigns GitHub issues to team members based on availability
- **AI Integration**: Uses OpenAI GPT-4 to suggest appropriate teams
- **Duplicate Detection**: Identifies and closes duplicate issues automatically
- **Slack Management**: Checks member status (PTO, working hours, presence)
- **GitHub GraphQL**: Efficient access to GitHub Projects v2

## 🏗️ Architecture

The system is organized in classes following the `slack_gw_v2.py` pattern:

```
community_assigner.py
├── Data Classes
│   ├── SlackMember
│   ├── GitHubIssue
│   └── TeamMember
│
├── API Clients
│   ├── TokenManager
│   ├── GitHubAPIClient (REST API)
│   ├── GitHubGraphQLClient (GraphQL API)
│   ├── SlackAPIClient
│   ├── OpenAIClient
│   └── GoogleSheetsClient
│
├── Business Logic
│   ├── IssueAssigner
│   └── SummaryGenerator
│
└── Main Orchestrator
    └── CommunityAssigner
```

## 📦 Installation

### Option 1: Automatic Setup

```bash
cd /path/to/community/tools/assigner
chmod +x setup.sh
./setup.sh
```

This will:
- Create a Python virtual environment
- Install all dependencies
- Set up configuration file templates

### Option 2: Manual Installation

1. **Install dependencies**:
```bash
cd /path/to/community/tools
pip install -r requirements.txt
```

2. **Configure tokens** (in `tools/` folder):

### `.token_github`
```
# GitHub Personal Access Token
# Scopes needed: repo, read:org, read:project, write:discussion
ghp_your_github_token_here
```

### `.token_slack`
```
# Slack Bot Token
# Scopes needed: users:read, users:read.email, users.profile:read, dnd:read, chat:write
xoxb-your-slack-bot-token
```

### `.token_slack_user` (optional, for message search)
```
# Slack User Token
# Scopes needed: search:read
xoxp-your-slack-user-token
```

### `.token_openai` (optional, for AI suggestions)
```
# OpenAI API Key
sk-your-openai-api-key
```

### `.credentials_google.json`
JSON file with Google Service Account credentials with permissions for Google Sheets and Drive.

Example structure:
```json
{
  "type": "service_account",
  "project_id": "your-project-id",
  "private_key_id": "...",
  "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n",
  "client_email": "your-service-account@your-project.iam.gserviceaccount.com",
  "client_id": "...",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "..."
}
```

**How to create Google credentials:**
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable Google Sheets API and Google Drive API
4. Create a Service Account
5. Generate a JSON key and download it as `.credentials_google.json`
6. Share your Google Spreadsheet with the service account email

## 🚀 Usage

### Generate summary only:
```bash
python community_assigner.py summary
```

### Run assignment only:
```bash
python community_assigner.py assignment
```

### Run everything (summary + assignment):
```bash
python community_assigner.py all
```

### Run default (summary):
```bash
python community_assigner.py
```

## 📊 Configuration

Edit the constants at the beginning of `community_assigner.py`:

```python
# GitHub Configuration
GITHUB_ORG = "your-org"
GITHUB_REPO = "your-repo"
GITHUB_PROJECT_NODE_ID = "PVT_kwDOANHY9s4AKR_X"

# Slack Configuration
SLACK_COMMUNITY_CHANNEL_ID = "CHANNELID"
SLACK_COMMUNITY_CHANNEL_NAME = "channel-name"

# Google Sheets Configuration
SPREADSHEET_NAME = "Community Team Summary"
SHEET_NAME = "Summary"
```

## 🔍 Main Components

### TokenManager
Manages secure token loading from files, removing spaces and comments.

### GitHubAPIClient
Interacts with GitHub REST API for:
- Getting teams and members
- Managing issues (assign, close, comment)
- Listing unassigned issues

### GitHubGraphQLClient
Uses GraphQL to efficiently access GitHub Projects v2:
- Gets all project issues
- Extracts custom fields (Team, Week, Year, Status, Time)
- Handles pagination automatically

### SlackAPIClient
Manages Slack interactions:
- Lists members with complete profiles
- Checks presence status
- Verifies Do Not Disturb (DND)
- Determines if they're in working hours
- Searches messages (requires user token)
- Sends messages and notifications

### OpenAIClient
Uses GPT-4 to suggest appropriate teams:
- Analyzes issue content
- Suggests most appropriate team
- Fallback to keyword detection if API fails

### GoogleSheetsClient
Updates Google Sheets with summaries:
- Creates/updates spreadsheets
- Formats headers and data
- Applies colors based on availability:
  - 🟢 Green: Available, < 2 tickets
  - 🟡 Yellow: Available, >= 2 tickets
  - 🔴 Red: Not available (PTO or outside working hours)

### SummaryGenerator
Generates weekly team summary:
- Counts assigned tickets per member
- Calculates availability (schedule + PTO)
- Identifies tickets from previous weeks
- Sorts by priority

### IssueAssigner
Issue assignment logic:
- Identifies available members
- Selects best candidate
- Detects duplicates
- Assigns and notifies

## 📝 Logs

Logs are saved to `community_assigner.log` with format:
```
2025-10-15 10:30:45 [INFO] ✅ GitHub client initialized
2025-10-15 10:30:46 [INFO] 📋 Fetching GitHub teams...
2025-10-15 10:30:47 [INFO] ✅ Found 18 allowed teams
```

## 🔄 Migration from Google Apps Script

This Python script replaces the following Apps Script files:
- `assignment.js` → `IssueAssigner` class
- `summary.js` → `SummaryGenerator` class
- `common.js` → `TokenManager`, `DateUtils`, API clients
- `main.js` → `CommunityAssigner.run_all()`

### Key differences:

| Apps Script | Python |
|------------|--------|
| `PropertiesService` | `.token_*` files |
| `SpreadsheetApp` | `gspread` library |
| `UrlFetchApp` | `PyGithub`, `slack-sdk`, `requests` |
| Automatic callbacks | Manual or cron execution |
| Integrated in Sheets | Standalone script |

## 🔐 Security

- ✅ Tokens loaded from local files (not hardcoded)
- ✅ Token files are in `.gitignore`
- ✅ Support for comments in token files
- ✅ Automatic whitespace cleanup in tokens
- ⚠️  **Do NOT commit `.token_*` or `.credentials_google.json` files**

## 🐛 Troubleshooting

### Error: "No module named 'github'"
```bash
cd tools
pip install -r requirements.txt
```

### Error: "Slack API error: invalid_auth"
Verify that the Slack token has the necessary scopes and is active.

### Error: "Google credentials file not found"
Make sure you have `.credentials_google.json` in the tools/ folder.

### Error: "GraphQL query failed: 401"
The GitHub token expired or doesn't have sufficient permissions.

### Issues don't show in the project
Verify that `GITHUB_PROJECT_NODE_ID` is correct. You can get it from the project URL or using GraphQL.

## 📚 References

- [PyGithub Documentation](https://pygithub.readthedocs.io/)
- [Slack SDK for Python](https://slack.dev/python-slack-sdk/)
- [gspread Documentation](https://docs.gspread.org/)
- [OpenAI Python Library](https://github.com/openai/openai-python)
- [GitHub GraphQL API](https://docs.github.com/en/graphql)

## 🤝 Contributing

To add new features:

1. Create a new class following the existing pattern
2. Add appropriate logging
3. Document with docstrings
4. Update this README

## 📄 License

Same as the main repository.
