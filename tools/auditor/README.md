# Community Auditor

Python tool for generating weekly team summaries from GitHub Issues and Slack team availability data, updating Google Sheets with color-coded status information.

## Overview

The Community Auditor extracts data from:
- **GitHub Projects v2**: Open issues assigned to team members
- **Slack API**: User presence and Do Not Disturb status
- **Working hours calculation**: Availability based on current week progress

And generates a Google Sheets summary with:
- Color-coded availability (green: available, yellow: limited, red: unavailable)
- Issue count per member
- Priority sorting (a/b/c based on availability and workload)
- Automatic formatting with borders and highlighting

## Features

- **SQLite Cache System**: 10-20x faster with intelligent caching (see [CACHE.md](CACHE.md))
- **GraphQL Pagination**: Efficiently fetches large project datasets
- **Slack Status Checking**: Combines presence + DND to determine actual availability
- **Working Days Calculation**: Excludes weekends from current week progress
- **Smart Priority Assignment**: 
  - Priority A: Available members with fewer issues
  - Priority B: Moderate availability or moderate workload
  - Priority C: Limited availability or high workload
- **Google Sheets Formatting**: Professional appearance with color coding and borders
- **Comprehensive Logging**: Detailed logs of all operations

## Prerequisites

1. **Python 3.7+** with pip
2. **GitHub Personal Access Token** with:
   - `repo` scope (read repository data)
   - `read:org` scope (read organization data)
   - `read:project` scope (read project data)
3. **Slack User Token** with scopes:
   - `users:read` (user information)
   - `users:read.email` (email addresses)
   - `users.profile:read` (user profiles)
4. **Google Service Account** with:
   - Google Sheets API enabled
   - Service account JSON credentials
   - Sheet shared with service account email

## Installation

### 1. Run Setup Script

```bash
cd /path/to/community/tools/auditor
chmod +x setup.sh
./setup.sh
```

This will:
- Create a Python virtual environment
- Install all dependencies
- Set up configuration file templates

### 2. Configure Tokens

Copy and configure token files:

```bash
# GitHub token
cp .token_github.example .token_github
# Edit and add your token (remove comments)

# Slack token
cp .token_slack.example .token_slack
# Edit and add your token (remove comments)

# Slack user token (for presence checking)
cp .token_slack_user.example .token_slack_user
# Edit and add your token (remove comments)
```

**Token File Format:**
```
# Comments are allowed (lines starting with #)
your-actual-token-here
# Whitespace is automatically trimmed
```

### 3. Configure Google Credentials

```bash
cp .credentials_google.json.example .credentials_google.json
# Replace with your actual service account JSON
```

## Configuration

Edit `auditor.py` to set your configuration:

```python
# GitHub Configuration
GITHUB_ORG = "your-org"
GITHUB_REPO = "your-repo"
PROJECT_NUMBER = 123  # Your GitHub Project number

# Google Sheets Configuration
SPREADSHEET_NAME = "Your Spreadsheet Name"
WORKSHEET_NAME = "Sheet1"

# Slack Configuration
SLACK_TEAM_DOMAIN = "yourteam"  # For user profile links

# Cache Configuration (optional)
CACHE_ENABLED = True               # Enable/disable caching globally
CACHE_GITHUB_TEAMS = True          # Cache GitHub teams
CACHE_SLACK_MEMBERS = True         # Cache Slack members
CACHE_PROJECT_ISSUES = True        # Cache project issues
```

See [CACHE.md](CACHE.md) for detailed cache documentation.

## Usage

### Basic Usage

```bash
# Activate virtual environment
source venv/bin/activate

# Run the auditor
python auditor.py
```

### Cache Management

```bash
# View cache status
python auditor.py --clear-cache

# Clear specific cache
python auditor.py --clear-cache github_teams
python auditor.py --clear-cache slack_members
python auditor.py --clear-cache project_issues

# Clear all cache
python auditor.py --clear-cache all
```

### First Run vs Cached Run

**First run** (building cache):
```bash
python auditor.py
# Takes ~2-3 minutes (fetching all data from APIs)
```

**Subsequent runs** (using cache):
```bash
python auditor.py  
# Takes ~15-20 seconds (cached data) ⚡
```

### Regular Usage
python auditor.py
```

### What It Does

1. Fetches all open issues from the specified GitHub Project
2. Checks Slack status for all assigned team members
3. Calculates availability based on:
   - Current week progress (working days only)
   - Slack presence (active/away)
   - Do Not Disturb status
4. Updates Google Sheets with:
   - Member name (linked to Slack profile)
   - Team identifier
   - Issue count
   - Availability percentage
   - Priority level (A/B/C)
5. Applies color coding:
   - 🟢 Green: >60% available
   - 🟡 Yellow: 30-60% available
   - 🔴 Red: <30% available

### Example Output

The Google Sheet will look like:

| Member Name | Team | Issues | Availability | Priority |
|-------------|------|--------|--------------|----------|
| John Doe    | API  | 3      | 75%          | A        |
| Jane Smith  | UI   | 5      | 45%          | B        |
| Bob Jones   | DB   | 7      | 20%          | C        |

## Architecture

### Class Structure

```
CommunityAuditor (main orchestrator)
├── TokenManager (loads tokens from files)
├── DateUtils (working days calculation)
├── GitHubAPIClient (PyGithub wrapper)
├── GitHubGraphQLClient (Projects v2 access)
├── SlackAPIClient (Slack SDK wrapper)
├── GoogleSheetsClient (gspread wrapper)
└── SummaryGenerator (core summary logic)
```

### Data Flow

```
GitHub Projects v2 → GitHubGraphQLClient → GitHubIssue objects
                                              ↓
Slack API → SlackAPIClient → SlackMember objects
                                              ↓
                                    SummaryGenerator
                                              ↓
                                    TeamMember objects (sorted by priority)
                                              ↓
                                    GoogleSheetsClient
                                              ↓
                                    Google Sheets (formatted)
```

## Dependencies

- **PyGithub**: GitHub REST API client
- **slack-sdk**: Official Slack SDK
- **gspread**: Google Sheets API client
- **google-auth**: Google authentication
- **requests**: HTTP library for GraphQL queries

See `../requirements.txt` for specific versions.

## Error Handling

The tool includes comprehensive error handling:
- Token loading failures
- API rate limiting
- Network errors
- Missing data gracefully handled

Check console output for detailed error messages and logging.

## Comparison with Apps Script Version

This Python implementation replaces the original `summary.js` Google Apps Script with:
- ✅ Better error handling and logging
- ✅ Type hints for code safety
- ✅ Modular class-based architecture
- ✅ GraphQL for efficient data fetching
- ✅ Proper token management
- ✅ Local execution (no Apps Script limits)

See `MIGRATION.md` in the assigner folder for detailed comparison.

## Troubleshooting

### "Invalid token" errors
- Verify token file contains only the token (no comments on the same line)
- Check token has required scopes
- Ensure no extra whitespace

### Google Sheets permission errors
- Share the spreadsheet with the service account email (found in credentials JSON)
- Verify Google Sheets API is enabled in Google Cloud Console

### Slack API errors
- Ensure both slack tokens are configured (app token + user token)
- User token needed for presence checking
- App token needed for user profile data

### GraphQL pagination issues
- Check GitHub token has `read:project` scope
- Verify project number is correct
- Ensure organization name is correct

## License

Part of the community tools repository.
