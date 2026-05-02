#!/usr/bin/env python3
"""
Clear all cache indices to force recreation with new mappings
Run this after updating index mappings
"""

import os
import sys
import logging

# Setup basic logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# Add parent directory to path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

from indexer.opensearch_indexer import OpenSearchIndexer
import requests

# Index names
CACHE_INDICES = [
    "github-teams-cache",
    "slack-members-cache", 
    "project-issues-cache"
]

def delete_index(indexer, index_name):
    """Delete an index"""
    url = f"{indexer.host}/{index_name}"
    
    try:
        response = requests.delete(
            url,
            auth=indexer.auth,
            verify=False,
            timeout=10
        )
        
        if response.status_code == 200:
            logging.info(f"✅ Deleted index: {index_name}")
            return True
        elif response.status_code == 404:
            logging.info(f"ℹ️  Index not found (already deleted): {index_name}")
            return True
        else:
            logging.error(f"❌ Failed to delete {index_name}: {response.status_code}")
            return False
    except Exception as e:
        logging.error(f"❌ Error deleting {index_name}: {e}")
        return False

def main():
    print("🗑️  Cache Indices Cleanup")
    print("=" * 60)
    print("This will delete all cache indices to force recreation")
    print("with updated mappings.")
    print("=" * 60)
    
    # Initialize OpenSearch indexer
    indexer = OpenSearchIndexer()
    
    if not indexer.enabled:
        logging.error("❌ OpenSearch not available")
        return 1
    
    logging.info("🔧 Connected to OpenSearch")
    
    # Delete each cache index
    success_count = 0
    for index_name in CACHE_INDICES:
        if delete_index(indexer, index_name):
            success_count += 1
    
    print("=" * 60)
    if success_count == len(CACHE_INDICES):
        logging.info(f"✅ Successfully deleted {success_count}/{len(CACHE_INDICES)} indices")
        logging.info("📋 Indices will be recreated with new mappings on next run")
    else:
        logging.warning(f"⚠️  Deleted {success_count}/{len(CACHE_INDICES)} indices")
    print("=" * 60)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
