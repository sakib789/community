import requests
import os
import logging
from requests.auth import HTTPBasicAuth

OPENSEARCH_HOST = "https://search-community-metrics-oevnczvd7jexwstzykmjwj7ak4.aos.us-east-1.on.aws"
INDEX_NAME = "community-tickets"
USERNAME = "community"
TOKEN_FILE = ".token_opensearch.prod"
VERIFY_CERTS = False
LOG_FILE = "update_team.log"
BATCH_SIZE = 500

# Read password/token
if not os.path.exists(TOKEN_FILE):
    raise FileNotFoundError(f"Opensearch token file not found: {TOKEN_FILE}")
with open(TOKEN_FILE, 'r') as token_file:
    PASSWORD = token_file.read().strip()

auth = HTTPBasicAuth(USERNAME, PASSWORD)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="a"),
        logging.StreamHandler()
    ]
)

def scan_documents_with_team_ops_community():
    """Scan all documents with team == 'ops-community'."""
    url = f"{OPENSEARCH_HOST}/{INDEX_NAME}/_search?scroll=2m"
    query = {
        "size": BATCH_SIZE,
        "query": {
            "term": {
                "team": "ops-community"
            }
        }
    }
    response = requests.post(url, auth=auth, verify=VERIFY_CERTS, headers={"Content-Type": "application/json"}, json=query)
    response.raise_for_status()
    data = response.json()
    scroll_id = data.get('_scroll_id')
    hits = data['hits']['hits']
    while hits:
        yield hits
        # Scroll for next batch
        scroll_url = f"{OPENSEARCH_HOST}/_search/scroll"
        scroll_payload = {
            "scroll": "2m",
            "scroll_id": scroll_id
        }
        scroll_resp = requests.post(scroll_url, auth=auth, verify=VERIFY_CERTS, headers={"Content-Type": "application/json"}, json=scroll_payload)
        scroll_resp.raise_for_status()
        scroll_data = scroll_resp.json()
        scroll_id = scroll_data.get('_scroll_id')
        hits = scroll_data['hits']['hits']

def bulk_update_team_field(batch):
    """Bulk update 'team' field to 'community' for a batch of documents."""
    bulk_lines = []
    for doc in batch:
        doc_id = doc['_id']
        action = {"update": {"_index": INDEX_NAME, "_id": doc_id}}
        doc_update = {"doc": {"team": "community"}}
        bulk_lines.append(f'{json.dumps(action)}\n{json.dumps(doc_update)}')
    bulk_body = '\n'.join(bulk_lines) + '\n'
    url = f"{OPENSEARCH_HOST}/_bulk"
    resp = requests.post(url, auth=auth, verify=VERIFY_CERTS, headers={"Content-Type": "application/x-ndjson"}, data=bulk_body)
    if resp.status_code in (200, 201):
        logging.info(f"Bulk updated {len(batch)} documents.")
    else:
        logging.error(f"Bulk update failed: {resp.status_code} - {resp.text}")

def main():
    logging.info("Starting bulk update of 'team' field from 'ops-community' to 'community'...")
    total = 0
    for batch in scan_documents_with_team_ops_community():
        bulk_update_team_field(batch)
        total += len(batch)
    logging.info(f"Finished. Updated {total} documents.")

if __name__ == "__main__":
    import json
    main()