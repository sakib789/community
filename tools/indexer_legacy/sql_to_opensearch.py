import sqlite3
import json
import boto3
from requests_aws4auth import AWS4Auth
import requests
import logging
import os
import sys
from requests.auth import HTTPBasicAuth

TOKEN_FILE = '.token_opensearch'
if not os.path.exists(TOKEN_FILE):
    raise FileNotFoundError("Opensearch token file not found. Please create a file named '.token_opensearch' with your Opensearch master password inside.")

with open(TOKEN_FILE, 'r') as token_file:
    PASSWORD = token_file.read().strip()
# === CONFIGURATION ===

#OPENSEARCH_HOST = "https://search-community-metrics-oevnczvd7jexwstzykmjwj7ak4.aos.us-east-1.on.aws"
OPENSEARCH_HOST = "https://localhost:9200" 
INDEX_NAME = "community-tickets"
BULK_SIZE = 500
SQLITE_DB = "complete_issues.db"
LOG_FILE = "sync_to_opensearch.log"
REGION = "us-east-1"  # ← Set your AWS region if different
#USERNAME = "community"
USERNAME = "admin"
VERIFY_CERTS = False

# === LOGGING ===

logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
auth = HTTPBasicAuth(USERNAME, PASSWORD)

# === FUNCTIONS ===

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
        lines.append(json.dumps(doc))
    return "\n".join(lines) + "\n"

def sync_issues_to_opensearch():
    if not os.path.exists(SQLITE_DB):
        logging.error(f"SQLite database not found: {SQLITE_DB}")
        return

    conn = sqlite3.connect(SQLITE_DB)
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM issues")
    rows = cursor.fetchall()
    column_names = [desc[0] for desc in cursor.description]

    total = len(rows)
    logging.info(f"{total} records found in SQLite database.")

    # Convierte cada fila en dict y ajusta fechas
    dict_rows = []
    for row in rows:
        row_dict = dict(zip(column_names, row))
        row_dict["created_at"] = int(row_dict["created_at"]) * 1000
        row_dict["closed_at"] = int(row_dict["closed_at"]) * 1000 if row_dict["closed_at"] else None
        dict_rows.append(row_dict)

    for i in range(0, total, BULK_SIZE):
        batch = dict_rows[i:i + BULK_SIZE]
        payload = bulk_payload(batch)

        response = requests.post(
            f"{OPENSEARCH_HOST}/_bulk",
            auth=auth,
            verify=VERIFY_CERTS,
            headers={"Content-Type": "application/x-ndjson"},
            data=payload
        )

        if response.status_code != 200 or response.json().get("errors"):
            logging.error(f"Batch {i//BULK_SIZE + 1}: Error {response.status_code} - {response.text}")
        else:
            logging.info(f"Batch {i//BULK_SIZE + 1}: successfully indexed ({len(batch)} documents).")

    conn.close()

# === MAIN ===

if __name__ == "__main__":
    create_index_if_not_exists()
    sync_issues_to_opensearch()
    logging.info("Sync completed.")