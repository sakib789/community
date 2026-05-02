# Wazuh Community Issues to OpenSearch Sync

This script fetches GitHub issues from the [Wazuh Community repository](https://github.com/wazuh/community) and synchronizes them to an OpenSearch cluster for analytics and monitoring. It enriches the issue data with team information, extracts metadata from labels and titles, and calculates resolution times.

## Features

- **GitHub Integration**: Fetches issues using GitHub's GraphQL API with pagination support
- **Team Resolution**: Maps issue assignees to their respective teams in the Wazuh organization
- **Data Enrichment**: Extracts resolution status, source platforms, and URLs from issue metadata
- **OpenSearch Storage**: Bulk indexes enriched issue data to OpenSearch for analytics
- **Time-based Processing**: Processes issues in weekly batches to handle GitHub API limits
- **Duration Calculation**: Automatically calculates resolution time in hours for closed issues

## Requirements

- Python 3.9+
- GitHub Personal Access Token with `read:org` and `repo` permissions
- OpenSearch cluster access credentials

## Setup

### 1. Install Dependencies

```bash
pip install requests
```

### 2. Create Token Files

Create the required token files in the same directory as the script:

```bash
# GitHub token
echo 'ghp_your_github_token_here' > .token

# OpenSearch credentials  
echo 'your_opensearch_password_here' > .token_opensearch.prod
```

> **Security Note**: Never commit token files to version control. Add them to `.gitignore`.

### 3. Configure Script

Edit the configuration variables in `fetch_issues.py` if needed:

```python
ORG_NAME = 'wazuh'  # GitHub organization
OPENSEARCH_HOST = "https://your-opensearch-cluster.amazonaws.com"
INDEX_NAME = "community-tickets"
USERNAME = "community"  # OpenSearch username
```

## Usage

### Run the Script

```bash
python fetch_issues.py
```

The script will:

1. **Connect to GitHub**: Authenticate using the token from `.token`
2. **Build Team Mapping**: Fetch all teams and members from the Wazuh organization
3. **Create OpenSearch Index**: Set up the index with proper field mappings if it doesn't exist
4. **Fetch Issues**: Process issues from March 1, 2023 to present in weekly batches
5. **Enrich Data**: Add team information, extract labels, calculate durations
6. **Bulk Index**: Send processed issues to OpenSearch in batches

### Data Processing

For each GitHub issue, the script extracts and processes:

- **Basic Info**: ID, title, URL, creation/closing dates, state, author
- **Assignment**: Assignee and their team (from organization teams)
- **Labels**: Resolution status and source platform from predefined label sets
- **Metadata**: URLs extracted from issue titles
- **Metrics**: Duration in hours for closed issues

### OpenSearch Schema

Issues are indexed with the following structure:

```json
{
  "id_issue": "123",
  "title": "Issue title",
  "url": "https://github.com/wazuh/community/issues/123",
  "created_at": "2024-01-01T10:00:00Z",
  "closed_at": "2024-01-02T15:30:00Z",
  "state": "CLOSED",
  "author": "username",
  "assignee": "assignee-username",
  "team": "community",
  "labels": ["bug", "resolved"],
  "resolution": "Resolved",
  "source": "Slack",
  "source_url": "https://slack.com/...",
  "duration_hours": 29.5
}
```

## Configuration

### GitHub Teams

The script only processes members from these allowed teams:

- Development teams (devel-*)
- Operations teams (ops-*)
- Content and community teams
- CTI and cloud teams

### Label Categories

**Resolution Labels**: `Resolved`, `Resolved without feedback`, `No feedback`

**Source Labels**: `Slack`, `Discord`, `Reddit`, `Google Groups`, `Github`, `LinkedIn`, `Twitter`, `X`

### Processing Batches

Issues are processed in weekly batches working backwards from the current date to avoid GitHub API limits. Each batch processes up to 1000 issues per query.

## Monitoring

The script provides detailed logging for:

- Team fetching progress
- Issue batch processing
- OpenSearch indexing results
- Error handling and retries

## AWS Lambda Support

The script includes a Lambda handler for serverless deployment:

```python
def lambda_handler(event, context):
    return main()
```

## Troubleshooting

**Authentication Issues**: Verify token files exist and contain valid credentials

**OpenSearch Connection**: Check cluster URL, credentials, and network connectivity

**GitHub Rate Limits**: The script handles pagination automatically, but heavy usage may hit rate limits

**Index Creation**: Ensure the OpenSearch user has permissions to create indices and bulk index data

DISCLAIMER: AI has generated the above README thru reading fetch_issues.py :D