#!/usr/bin/env python3
"""
Update existing parent documents in OpenSearch with assignee field
Adds a random assignee from the team list to all parent documents
"""

import logging
import os
import random
from opensearch_indexer import OpenSearchIndexer

# ======================== Configuration ========================

ASSIGNEES = [
    "sakib789",
    "joaquinsgi",
    "YisDav",
    "NahuFigueroa97",
    "vikman90",
    "bonyjohn05",
    "cborla",
    "MiguelazoDS"
]

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)


def update_parent_documents():
    """Update all parent documents with assignee field"""
    indexer = OpenSearchIndexer()
    
    if not indexer.enabled:
        logging.error("❌ OpenSearch indexer not enabled. Cannot update documents.")
        return
    
    logging.info("🔍 Fetching all parent documents...")
    
    # Query to get all parent documents
    query = {
        "query": {
            "term": {
                "record_type": "parent"
            }
        },
        "size": 1000  # Adjust if you have more documents
    }
    
    try:
        # Search for parent documents
        response = indexer.search(query)
        
        if not response:
            logging.error("❌ Failed to search documents")
            return
        
        hits = response.get('hits', {}).get('hits', [])
        total = response.get('hits', {}).get('total', {}).get('value', 0)
        
        logging.info(f"📋 Found {total} parent documents")
        
        if not hits:
            logging.warning("⚠️  No parent documents found")
            return
        
        # Update each document
        updated_count = 0
        failed_count = 0
        
        for hit in hits:
            doc_id = hit['_id']
            source = hit['_source']
            
            # Assign a random assignee
            assignee = random.choice(ASSIGNEES)
            
            # Add assignee field
            source['assignee'] = assignee
            
            # Update the document
            success = indexer.update_document(doc_id, source)
            
            if success:
                updated_count += 1
                logging.info(f"✅ Updated {doc_id} with assignee: {assignee}")
            else:
                failed_count += 1
                logging.error(f"❌ Failed to update {doc_id}")
        
        logging.info("=" * 50)
        logging.info(f"📊 Update Summary:")
        logging.info(f"   Total parent documents: {total}")
        logging.info(f"   Successfully updated: {updated_count}")
        logging.info(f"   Failed: {failed_count}")
        logging.info("=" * 50)
        
    except Exception as e:
        logging.error(f"❌ Error updating documents: {e}")


if __name__ == "__main__":
    print("🔧 OpenSearch Parent Documents Updater")
    print("📝 This script will add 'assignee' field to all parent documents")
    print(f"👥 Available assignees: {', '.join(ASSIGNEES)}")
    print("=" * 50)
    
    # Confirm before proceeding
    response = input("Do you want to proceed? (yes/no): ").strip().lower()
    
    if response in ['yes', 'y']:
        update_parent_documents()
        print("\n✅ Update completed!")
    else:
        print("\n🛑 Update cancelled")
