import requests
import sqlite3
import os
import re
from typing import List, Optional, Dict
from datetime import datetime, timedelta

ORG_NAME = 'wazuh'

TOKEN_FILE = '.token'
if not os.path.exists(TOKEN_FILE):
    raise FileNotFoundError("GitHub token file not found. Please create a file named '.token' with your GitHub token inside.")

with open(TOKEN_FILE, 'r') as token_file:
    GITHUB_TOKEN = token_file.read().strip()

GRAPHQL_URL = 'https://api.github.com/graphql'
DB_NAME = 'issues.db'
QUERY_FILE = 'query.graphql'

RESOLUTION_LABELS = ['Resolved', 'Resolved without feedback', 'No feedback']
SOURCE_LABELS = ['Slack', 'Discord', 'Reddit', 'Google Groups', 'Github']
GITHUB_ALLOWED_TEAMS = [
    "devel-xdrsiem-agent", "devel-xdrsiem-server", "devel-xdrsiem-indexer",
    "devel-xdrsiem-dashboard", "devel-xdrsiem-qa", "devel-xdrsiem-devops",
    "devel-cti-threatintel", "devel-cti-development-div2", "devel-cloud",
    "content", "ops-support", "ops-presales", "ops-community",
    "ops-tam", "ops-trainings"
]

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

    for team in teams:
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

def initialize_database():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS issues (
                id_issue INTEGER PRIMARY KEY,
                id TEXT,
                title TEXT,
                url TEXT,
                created_at TEXT,
                closed_at TEXT,
                state TEXT,
                state_reason TEXT,
                author TEXT,
                assignee TEXT,
                labels TEXT,
                repository TEXT,
                resolution TEXT,
                source TEXT,
                source_url TEXT,
                team TEXT,
                duration_hours TEXT
            )
        """)
        conn.commit()

def initialize_team_database():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS team_members (
                username TEXT PRIMARY KEY,
                team TEXT
            )
        """)
        conn.commit()

def is_team_data_cached() -> bool:
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM team_members")
        count = cursor.fetchone()[0]
        return count > 0

def store_team_members(user_team_map: Dict[str, str]):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        for username, team in user_team_map.items():
            cursor.execute("""
                INSERT OR REPLACE INTO team_members (username, team) VALUES (?, ?)
            """, (username, team))
        conn.commit()

def load_user_team_mapping() -> Dict[str, str]:
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT username, team FROM team_members")
        rows = cursor.fetchall()
        return {username: team for username, team in rows}

def get_or_build_user_team_mapping() -> Dict[str, str]:
    initialize_team_database()
    if is_team_data_cached():
        return load_user_team_mapping()
    else:
        print("Fetching team members from GitHub...")
        user_team_map = build_user_team_mapping()
        store_team_members(user_team_map)
        return user_team_map

def insert_issue(issue: Dict, user_team_map: Dict[str, str]):
    assignees = issue.get('assignees', {}).get('nodes', [])
    assignee = extract_assignee(assignees)

    labels = [label['name'] for label in issue.get('labels', {}).get('nodes', [])]
    label_str = ', '.join(labels)

    resolution = extract_label(labels, RESOLUTION_LABELS)
    source = extract_label(labels, SOURCE_LABELS)
    source_url = extract_url_from_title(issue['title'])

    createdAt = int(datetime.strptime(issue['createdAt'], '%Y-%m-%dT%H:%M:%SZ').timestamp())
    closedAt_str = issue.get('closedAt')
    if closedAt_str:
        closedAt = int(datetime.strptime(closedAt_str, '%Y-%m-%dT%H:%M:%SZ').timestamp())
    else:
        closedAt = None

    if closedAt is not None:
        duration_hours = (closedAt - createdAt) / 3600.0
    else:
        duration_hours = None

    team = user_team_map.get(assignee, 'No Team') if assignee else 'No Team'

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO issues (
                id_issue, id, title, url, created_at, closed_at,
                state, state_reason, author, assignee, labels, repository,
                resolution, source, source_url, team, duration_hours
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            issue['number'],
            issue['id'],
            issue['title'],
            issue['url'],
            createdAt,
            closedAt,
            issue['state'],
            issue.get('stateReason'),
            issue.get('author', {}).get('login'),
            assignee,
            label_str,
            issue['repository']['nameWithOwner'],
            resolution,
            source,
            source_url,
            team, 
            duration_hours
        ))
        conn.commit()

def main():
    initialize_database()
    user_team_map = get_or_build_user_team_mapping()
    
    start_date = datetime.strptime("2023-03-01", "%Y-%m-%d")
    #start_date = datetime.strptime("2025-05-13", "%Y-%m-%d")
    #end_date = datetime.strptime("2024-12-31", "%Y-%m-%d")
    end_date = datetime.today()

    current = start_date
    while current <= end_date:
        week_end = current + timedelta(days=6)
        range_start = current.strftime("%Y-%m-%d")
        range_end = min(week_end, end_date).strftime("%Y-%m-%d")

        issues = fetch_issues_for_range(range_start, range_end)
        print(f"Fetched {len(issues)} issues for {range_start} to {range_end}")

        for issue in issues:
            insert_issue(issue, user_team_map)

        current = week_end + timedelta(days=1)

    print(f"Issues stored in {DB_NAME} database.")

if __name__ == '__main__':
    main()
