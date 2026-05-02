import requests
import os
import re
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, List

# --- CONFIGURATION ---
SLACK_TOKEN_FILE = '.token_slack'
GITHUB_TOKEN_FILE = '.token'

if not os.path.exists(SLACK_TOKEN_FILE):
    raise FileNotFoundError(f"Slack token file not found: {SLACK_TOKEN_FILE}")
with open(SLACK_TOKEN_FILE, 'r') as f:
    SLACK_TOKEN = f.read().strip()

if not os.path.exists(GITHUB_TOKEN_FILE):
    raise FileNotFoundError(f"GitHub token file not found: {GITHUB_TOKEN_FILE}")
with open(GITHUB_TOKEN_FILE, 'r') as f:
    GITHUB_TOKEN = f.read().strip()

SLACK_API_URL = "https://slack.com/api"
GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"
REPO_OWNER = "wazuh"
REPO_NAME = "community"
LABEL = "Slack"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

def parse_slack_url(url: str) -> Optional[Dict[str, str]]:
    """
    Parse a Slack message URL and extract channel and message_ts.
    Example: https://wazuh.slack.com/archives/C07BZJY86G3/p1751459639688079
    Returns: {'channel': 'C07BZJY86G3', 'ts': '1751459639.688079'}
    """
    m = re.match(r"https://\w+\.slack\.com/archives/([A-Z0-9]+)/p(\d{16})", url)
    if not m:
        logging.error("Invalid Slack URL format.")
        return None
    channel = m.group(1)
    ts_raw = m.group(2)
    ts = f"{ts_raw[:-6]}.{ts_raw[-6:]}"
    print(f"Parsed Slack URL: channel={channel}, ts={ts}")
    return {"channel": channel, "ts": ts}

def fetch_slack_thread(channel: str, thread_ts: str) -> List[Dict]:
    """
    Fetch all messages in a Slack thread given channel and thread_ts.
    """
    headers = {"Authorization": f"Bearer {SLACK_TOKEN}"}
    url = f"{SLACK_API_URL}/conversations.replies"
    params = {"channel": channel, "ts": thread_ts, "limit": 1000}
    resp = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise Exception(f"Slack API error: {data}")
    return data.get("messages", [])

def github_search_issue_by_slack_url(slack_url: str) -> Optional[Dict]:
    """
    Search for an open GitHub issue in wazuh/community with label 'Slack' and the Slack URL in the title.
    """
    query = """
    query($queryString: String!, $after: String) {
      search(query: $queryString, type: ISSUE, first: 10, after: $after) {
        edges {
          node {
            ... on Issue {
              number
              title
              url
              state
              labels(first: 10) { nodes { name } }
            }
          }
        }
      }
    }
    """
    query_string = f'repo:{REPO_OWNER}/{REPO_NAME} is:issue is:open label:"{LABEL}" in:title "{slack_url}"'
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Content-Type": "application/json"
    }
    variables = {"queryString": query_string, "after": None}
    resp = requests.post(GITHUB_GRAPHQL_URL, json={"query": query, "variables": variables}, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    issues = data["data"]["search"]["edges"]
    for edge in issues:
        node = edge["node"]
        if slack_url in node["title"]:
            return node
    return None

def github_list_open_slack_issues() -> List[Dict]:
    """
    List all open GitHub issues in wazuh/community with label 'Slack'.
    Returns a list of dicts with number, title, and url.
    """
    issues = []
    query = """
    query($queryString: String!, $after: String) {
      search(query: $queryString, type: ISSUE, first: 100, after: $after) {
        pageInfo {
          hasNextPage
          endCursor
        }
        edges {
          node {
            ... on Issue {
              number
              title
              url
              state
              labels(first: 10) { nodes { name } }
            }
          }
        }
      }
    }
    """
    query_string = f'repo:{REPO_OWNER}/{REPO_NAME} is:issue is:open label:"{LABEL}"'
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Content-Type": "application/json"
    }
    after = None
    while True:
        variables = {"queryString": query_string, "after": after}
        resp = requests.post(GITHUB_GRAPHQL_URL, json={"query": query, "variables": variables}, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        search = data["data"]["search"]
        for edge in search["edges"]:
            node = edge["node"]
            issues.append(node)
        if not search["pageInfo"]["hasNextPage"]:
            break
        after = search["pageInfo"]["endCursor"]
    return issues

def github_get_last_comment(issue_number: int) -> Optional[Dict]:
    """
    Get the last comment of a GitHub issue.
    """
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue_number}/comments"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    comments = resp.json()
    if comments:
        return comments[-1]
    return None

def github_post_comment(issue_number: int, text: str):
    """
    Post a comment to a GitHub issue.
    """
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue_number}/comments"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
    resp = requests.post(url, headers=headers, json={"body": text})
    resp.raise_for_status()
    logging.info(f"Posted comment to issue #{issue_number}")

def main(slack_url: str):
    # 1. Parse Slack URL
    slack_info = parse_slack_url(slack_url)
    if not slack_info:
        logging.error("Could not parse Slack URL.")
        return

    # 2. Fetch Slack thread
    thread_msgs = fetch_slack_thread(slack_info["channel"], slack_info["ts"])
    if not thread_msgs:
        logging.info("No messages found in Slack thread.")
        return

    # 3. Find GitHub issue
    issue = github_search_issue_by_slack_url(slack_url)
    if not issue:
        logging.error("No matching GitHub issue found.")
        return

    issue_number = issue["number"]
    logging.info(f"Found GitHub issue #{issue_number}: {issue['title']}")

    # 4. Get last comment in GitHub issue
    last_github_comment = github_get_last_comment(issue_number)
    last_github_text = last_github_comment["body"] if last_github_comment else ""

    # 5. Find last message from Slack not yet logged in GitHub
    # We'll log all messages after the last one found in GitHub
    last_logged_ts = None
    if last_github_comment:
        m = re.search(r"\[slack_ts:(\d+\.\d+)\]", last_github_text)
        if m:
            last_logged_ts = m.group(1)

    # Prepare new messages to log
    new_msgs = []
    for msg in thread_msgs:
        if msg["ts"] == slack_info["ts"]:
            continue  # skip the original message (assumed already logged)
        if last_logged_ts and float(msg["ts"]) <= float(last_logged_ts):
            continue
        user = msg.get("user", "unknown")
        text = msg.get("text", "")
        ts = msg["ts"]
        dt = datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        new_msgs.append(f"**Slack reply by <@{user}> at {dt}:**\n{text}\n[slack_ts:{ts}]")

    if not new_msgs:
        logging.info("No new Slack replies to log in GitHub.")
        return

    # 6. Post new messages as a single comment
    comment_body = "\n\n".join(new_msgs)
    github_post_comment(issue_number, comment_body)
    logging.info(f"Logged {len(new_msgs)} new Slack replies to GitHub issue #{issue_number}.")

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python slack_to_github_issue.py <slack_message_url>")
        exit(1)
    main(sys.argv[1])