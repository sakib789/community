import requests
import os
import re
from typing import List, Optional, Dict
from datetime import datetime, timedelta
import logging
import json
from requests.auth import HTTPBasicAuth
import sys 


ORG_NAME = 'wazuh'
# Extract tokens/passwords from files
TOKEN_FILE = '.token'
if not os.path.exists(TOKEN_FILE):
    raise FileNotFoundError("GitHub token file not found. Please create a file named '.token' with your GitHub token inside.")
with open(TOKEN_FILE, 'r') as token_file:
    GITHUB_TOKEN = token_file.read().strip()

TOKEN_FILE = '.token_opensearch.prod'
if not os.path.exists(TOKEN_FILE):
    raise FileNotFoundError("Opensearch token file not found. Please create a file named '.token_opensearch' with your Opensearch master password inside.")
with open(TOKEN_FILE, 'r') as token_file:
    PASSWORD = token_file.read().strip()


OPENSEARCH_HOST = "https://search-community-metrics-oevnczvd7jexwstzykmjwj7ak4.aos.us-east-1.on.aws"
#OPENSEARCH_HOST = "https://localhost:9200" 
INDEX_NAME = "community-tickets"
BULK_SIZE = 500
SQLITE_DB = "complete_issues.db"
LOG_FILE = "sync.log"
REGION = "us-east-1"  # ← Set your AWS region if different
USERNAME = "community"
#USERNAME = "admin"
VERIFY_CERTS = False
GRAPHQL_URL = 'https://api.github.com/graphql'
DB_NAME = 'issues.db'
QUERY_FILE = 'query.graphql'
RESOLUTION_LABELS = ['Resolved', 'Resolved without feedback', 'No feedback']
SOURCE_LABELS = ['Slack', 'Discord', 'Reddit', 'Google Groups', 'Github', 'LinkedIn', 'Twitter', 'X']
GITHUB_ALLOWED_TEAMS = [
    "devel-xdrsiem-agent", "devel-xdrsiem-server", "devel-xdrsiem-indexer",
    "devel-xdrsiem-dashboard", "devel-xdrsiem-qa", "devel-xdrsiem-devops",
    "devel-cti-threatintel", "devel-cti-development-div2", "devel-cloud-platform",
    "devel-cloud-cicd", "devel-cloud-ops", "devel-cloud-threatintel",
    "content", "ops-support", "ops-presales", "community",
    "ops-tam", "ops-trainings"
]

# === LOGGING ===
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=[logging.StreamHandler()])
auth = HTTPBasicAuth(USERNAME, PASSWORD)

# === GITHUB API FUNCTIONS ===
def get_teams():
    url = f'https://api.github.com/orgs/{ORG_NAME}/teams?per_page=100'
    headers = {
        'Authorization': f'Bearer {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github+json'
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    teams = response.json()
    return teams

def get_team_members(team_slug):
    url = f'https://api.github.com/orgs/{ORG_NAME}/teams/{team_slug}/members?per_page=100'
    headers = {
        'Authorization': f'Bearer {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github+json'
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    members = response.json()
    return members

def build_user_team_mapping() -> Dict[str, str]:
    teams = get_teams()
    user_team_map = {}
    print(f"Found {len(teams)} teams in the organization.")
    for team in teams:
        print(f"Processing team: {team['name']} (slug: {team['slug']})")
        if team['name'] not in GITHUB_ALLOWED_TEAMS:
            continue

        team_slug = team['slug']
        members = get_team_members(team_slug)
        print(f"Fetched {len(members)} members for team: {team['name']}")
        for member in members:
            username = member['login']
            user_team_map[username] = team['name']

    return user_team_map

def load_query_from_file(path: str) -> str:
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

def run_query(query: str, variables: dict) -> dict:
    headers = {
        'Authorization': f'Bearer {GITHUB_TOKEN}',
        'Content-Type': 'application/json'
    }
    response = requests.post(GRAPHQL_URL, json={'query': query, 'variables': variables}, headers=headers)
    response.raise_for_status()
    return response.json()

def fetch_issues_for_range(start: str, end: str) -> List[Dict]:
    all_issues = []
    cursor = None
    has_next_page = True
    query = load_query_from_file(QUERY_FILE)
    query_string = f"repo:wazuh/community created:{start}..{end}"
    print(f"Fetching issues for range {start} to {end}...")

    while has_next_page:
        variables = {'queryString': query_string, 'after': cursor}
        result = run_query(query, variables)

        search = result['data']['search']
        page_info = search['pageInfo']
        edges = search['edges']

        for edge in edges:
            node = edge['node']
            all_issues.append(node)

        has_next_page = page_info['hasNextPage']
        cursor = page_info['endCursor']

    return all_issues

# === DATA MODELING FUNCTIONS ===
def extract_assignee(assignees: List[Dict]) -> Optional[str]:
    for assignee in assignees:
        if assignee['login'] != 'wazuh-community':
            return assignee['login']
    return None

def extract_label(labels: List[str], options: List[str]) -> Optional[str]:
    for label in labels:
        if label in options:
            return label
    return None

def extract_url_from_title(title: str) -> Optional[str]:
    match = re.search(r'https?://\S+', title)
    return match.group(0) if match else None

# === OPENSEARCH FUNCTIONS ===
def create_index_if_not_exists():
    url = f"{OPENSEARCH_HOST}/{INDEX_NAME}"
    response = requests.head(url, auth=auth, verify=VERIFY_CERTS)
    if response.status_code == 404:
        logging.info(f"Index '{INDEX_NAME}' does not exist. Creating...")
        mapping = {
            "mappings": {
                "properties": {
                    "id": {"type": "keyword"},
                    "title": {"type": "text"},
                    "url": {"type": "keyword"},
                    "created_at": {"type": "date"},
                    "closed_at": {"type": "date"},
                    "state": {"type": "keyword"},
                    "state_reason": {"type": "keyword"},
                    "author": {"type": "keyword"},
                    "assignee": {"type": "keyword"},
                    "labels": {"type": "keyword"},
                    "repository": {"type": "keyword"},
                    "resolution": {"type": "keyword"},
                    "source": {"type": "keyword"},
                    "source_url": {"type": "keyword"},
                    "team": {"type": "keyword"},
                    "duration_hours": {"type": "float"}
                }
            }
        }
        response = requests.put(url, auth=auth, verify=VERIFY_CERTS, headers={"Content-Type": "application/json"}, json=mapping)
        if response.status_code not in (200, 201):
            logging.error(f"Error creating index: {response.status_code} - {response.text}")
        else:
            logging.info(f"Index '{INDEX_NAME}' created successfully.")
    else:
        logging.info(f"Index '{INDEX_NAME}' already exists.")

def bulk_payload(docs):
    lines = []
    for doc in docs:
        action = {"index": {"_index": INDEX_NAME, "_id": doc["id_issue"]}}
        lines.append(json.dumps(action))
        clean_doc = {k: v for k, v in doc.items() if v is not None}
        lines.append(json.dumps(clean_doc))
    return "\n".join(lines) + "\n"

# === OPENSEARCH INSERTION ===

def sent_to_opensearch(issues):
    payload = bulk_payload(issues)


    response = requests.post(
        f"{OPENSEARCH_HOST}/_bulk",
        auth=auth,
        verify=VERIFY_CERTS,
        headers={"Content-Type": "application/x-ndjson"},
        data=payload
    )

    if response.status_code != 200 or response.json().get("errors"):
        logging.error(f"Batch: Error ({len(issues)} documents) {response.status_code} - {response.text}")
        raise RuntimeError("Error indexing issues to OpenSearch. Check the logs for details.")
    else:
        logging.info(f"Batch: Successfully indexed ({len(issues)} documents).")

def insert_issues(issues: List, user_team_map: Dict[str, str]):
    issues_prepared = []
    for issue in issues:
        assignees = issue.get('assignees', {}).get('nodes', [])
        assignee = extract_assignee(assignees)

        labels = [label['name'] for label in issue.get('labels', {}).get('nodes', [])]

        resolution = extract_label(labels, RESOLUTION_LABELS)
        source = extract_label(labels, SOURCE_LABELS)
        source_url = extract_url_from_title(issue['title'])

        duration_hours = None
        closedAt = None
        createdAt = issue['createdAt']
        if issue['closedAt']:
            closedAt = issue['closedAt']
            fmt = '%Y-%m-%dT%H:%M:%SZ'
            created_dt = datetime.strptime(createdAt, fmt)
            closed_dt = datetime.strptime(closedAt, fmt)
            duration_hours = (closed_dt - created_dt).total_seconds() / 3600.0

        team = user_team_map.get(assignee, 'No Team') if assignee else 'No Team'

        issues_prepared.append({
            "id_issue": issue['number'],
            "id": issue['id'],
            "title": issue['title'],
            "url": issue['url'],
            "created_at": createdAt,
            "closed_at": closedAt,
            "state": issue['state'],
            "state_reason": issue.get('stateReason'),
            "author": issue.get('author', {}).get('login'),
            "assignee": assignee,
            "labels": labels,
            "repository": issue['repository']['nameWithOwner'],
            "resolution": resolution,
            "source": source,
            "source_url": source_url,
            "team": team,
            "duration_hours": duration_hours
        })
    sent_to_opensearch(issues_prepared)

def main():
    create_index_if_not_exists()
    user_team_map = build_user_team_mapping()
    
    #start_date = datetime.strptime("2023-03-01", "%Y-%m-%d")
    #start_date = datetime.strptime("2023-03-01", "%Y-%m-%d")
    end_date = datetime.today()
    start_date = end_date - timedelta(days=120)

    current = end_date
    while current >= start_date:
        week_start = current - timedelta(days=6)
        range_start = max(week_start, start_date).strftime("%Y-%m-%d")
        range_end = current.strftime("%Y-%m-%d")

        issues = fetch_issues_for_range(range_start, range_end)
        print(f"Fetched {len(issues)} issues for {range_start} to {range_end}")
        if len(issues) > 0:
            insert_issues(issues, user_team_map)

        current -= timedelta(days=7)

    logging.info(f"Issues sent to {OPENSEARCH_HOST}.")
    return {"status": "ok", "processed": len(issues)}

# Lambda handler
def lambda_handler(event, context):
    return main()

if __name__ == '__main__':
    main()
