import requests
import json
from datetime import datetime, timedelta, timezone
import logging

# --- Configuration ---
ACCESS_TOKEN = "xx"
OWNER = "wazuh"
REPO = "community"
ACTOR_FILTER = "vikman90"
HOURS_BACK = 60
GRAPHQL_URL = "https://api.github.com/graphql"
HEADERS = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

# Configure logging to file and console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("unassigned.log", mode="a"),
        logging.StreamHandler()
    ]
)


def fetch_issues(repo_owner, repo_name, start_date, end_date):
    """
    Returns a list of issue numbers from the repository created between start_date and end_date (both datetime, UTC).
    Uses GitHub's search API with a query string for time filtering.
    Sorted by createdAt ASC.
    """
    all_issues = []
    cursor = None
    has_next_page = True
    # Format dates as YYYY-MM-DD
    start = start_date.strftime('%Y-%m-%d') if start_date else '1970-01-01'
    end = end_date.strftime('%Y-%m-%d') if end_date else datetime.now(timezone.utc).strftime('%Y-%m-%d')
    query_string = f"repo:{repo_owner}/{repo_name} created:{start}..{end} sort:created-asc"
    print(f"Fetching issues for range {start} to {end}...")
    logging.info(f"Fetching issues for range {start} to {end}...")
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
              createdAt
            }
          }
        }
      }
    }
    """
    headers = {
        'Authorization': f'Bearer {ACCESS_TOKEN}',
        'Content-Type': 'application/json'
    }
    page = 1
    while has_next_page:
        print(f"[fetch_issues] Requesting page {page} (cursor={cursor})...")
        logging.info(f"Requesting page {page} (cursor={cursor})...")
        variables = {'queryString': query_string, 'after': cursor}
        response = requests.post(GRAPHQL_URL, headers=headers, json={'query': query, 'variables': variables})
        data = response.json()
        if "errors" in data:
            print(f"[fetch_issues] Error: {json.dumps(data['errors'], indent=2)}")
            logging.error(f"Error: {json.dumps(data['errors'], indent=2)}")
            raise Exception(json.dumps(data["errors"], indent=2))
        search = data['data']['search']
        page_info = search['pageInfo']
        edges = search['edges']
        print(f"[fetch_issues] Fetched {len(edges)} issues on page {page}.")
        logging.info(f"Fetched {len(edges)} issues on page {page}.")
        for edge in edges:
            node = edge['node']
            all_issues.append(node['number'])
        has_next_page = page_info['hasNextPage']
        cursor = page_info['endCursor']
        page += 1
    return all_issues


def get_recent_unassigned_events_and_reassign(repo_owner, repo_name, issue_number, cutoff, actor_filter):
    """
    Detects UnassignedEvent events performed by actor_filter in a specific issue and immediately reassigns the user(s).
    Handles multiple assignees per event.
    """
    query = """
    query($owner: String!, $name: String!, $number: Int!, $cursor: String) {
      repository(owner: $owner, name: $name) {
        issue(number: $number) {
          timelineItems(first: 100, itemTypes: [UNASSIGNED_EVENT], after: $cursor) {
            pageInfo {
              hasNextPage
              endCursor
            }
            nodes {
              __typename
              ... on UnassignedEvent {
                createdAt
                actor {
                  login
                }
                assignee {
                  ... on User {
                    login
                  }
                  ... on Bot {
                    login
                  }
                  ... on Organization {
                    login
                  }
                }
              }
            }
          }
        }
      }
    }
    """

    variables = {
        "owner": repo_owner,
        "name": repo_name,
        "number": issue_number,
        "cursor": None
    }

    url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/issues/{issue_number}/assignees"
    headers = HEADERS.copy()
    headers["Accept"] = "application/vnd.github.v3+json"

    while True:
        response = requests.post(GRAPHQL_URL, headers=HEADERS, json={"query": query, "variables": variables})
        data = response.json()

        if "errors" in data:
            logging.error(json.dumps(data["errors"], indent=2))
            raise Exception(json.dumps(data["errors"], indent=2))

        items = data["data"]["repository"]["issue"]["timelineItems"]
        assignees_to_reassign = set()
        event_time = None
        for event in items["nodes"]:
            created_at = datetime.fromisoformat(event["createdAt"].replace("Z", "+00:00"))
            actor = event["actor"]["login"] if event["actor"] else None
            assignee = event["assignee"]["login"] if event["assignee"] else None
            if created_at >= cutoff and actor == actor_filter and assignee:
                logging.info(f"Unassigned event found: issue #{issue_number}, actor={actor}, assignee={assignee}, created_at={created_at}")
                assignees_to_reassign.add(assignee)
                event_time = created_at
        if assignees_to_reassign:
            payload = {"assignees": list(assignees_to_reassign)}
            resp = requests.post(url, headers=headers, json=payload)
            if resp.status_code == 201:
                print(f"[reassign] Assignees {list(assignees_to_reassign)} reassigned to issue #{issue_number}.")
                logging.info(f"Assignees {list(assignees_to_reassign)} reassigned to issue #{issue_number}.")
            elif resp.status_code == 422 and 'already assigned' in resp.text:
                print(f"[reassign] Some assignees already assigned to issue #{issue_number}.")
                logging.info(f"Some assignees already assigned to issue #{issue_number}.")
            else:
                print(f"[reassign] Failed to assign {list(assignees_to_reassign)} to issue #{issue_number}: {resp.status_code} - {resp.text}")
                logging.error(f"Failed to assign {list(assignees_to_reassign)} to issue #{issue_number}: {resp.status_code} - {resp.text}")
        if not items["pageInfo"]["hasNextPage"]:
            break
        variables["cursor"] = items["pageInfo"]["endCursor"]


if __name__ == "__main__":
    print("🔍 Getting list of issues day by day...")
    logging.info("Getting list of issues day by day...")
    end_date = datetime.now(timezone.utc)
    start_date = datetime(2023, 3, 1, tzinfo=timezone.utc)
    current = start_date + timedelta(days=1)
    while current <= end_date:
        print(f"\n=== Processing day {current}: {current.date()} ===")
        logging.info(f"Processing day {current}: {current.date()}")
        issues = fetch_issues(OWNER, REPO, start_date, current)
        print(f"📦 Scanning {len(issues)} issues for Unassigned events by {ACTOR_FILTER} on {current.date()}...")
        logging.info(f"Scanning {len(issues)} issues for Unassigned events by {ACTOR_FILTER} on {current.date()}...")
        for i, issue_number in enumerate(issues):
            print(f"  ⏳ [{i+1}/{len(issues)}] Issue #{issue_number}")
            logging.info(f"Scanning issue [{i+1}/{len(issues)}] #{issue_number}")
            get_recent_unassigned_events_and_reassign(OWNER, REPO, issue_number, datetime.now(timezone.utc) - timedelta(hours=HOURS_BACK), ACTOR_FILTER)
        current = current + timedelta(days=1)
    print("\n✅ All days processed.")
    logging.info("All days processed.")
