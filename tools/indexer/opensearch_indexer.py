#!/usr/bin/env python3
"""
OpenSearch Indexer for Slack/GitHub messages
Handles parent-child document relationships for issues and comments
"""

import logging
import os
import sys
import requests
from requests.auth import HTTPBasicAuth
from typing import Dict, Optional, List
from datetime import datetime
import json

# Add parent directory to path
PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PARENT_DIR)

# Import centralized logging and token manager
try:
    from logging_config import setup_logger
    from token_manager import get_opensearch_password
    logger = setup_logger("Indexer")
except ImportError:
    # Fallback if logging_config not available
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] [%(levelname)s] %(message)s")
    logger = logging.getLogger("Indexer")
    def get_opensearch_password():
        return None


# ======================== Configuration ========================

OPENSEARCH_HOST = "https://search-community-metrics-oevnczvd7jexwstzykmjwj7ak4.aos.us-east-1.on.aws"
INDEX_NAME = "tickets-raw-sakib-v1.0"
USERNAME = "sakib"
VERIFY_CERTS = False


# ======================== OpenSearch Indexer ========================

class OpenSearchIndexer:
    """
    Simple indexer for documents with parent-child relationships
    """
    
    def __init__(self, host: str = OPENSEARCH_HOST, index_name: str = INDEX_NAME, 
                 username: str = USERNAME, password: Optional[str] = None):
        """
        Initialize the OpenSearch indexer
        
        Args:
            host: OpenSearch host URL
            index_name: Target index name
            username: OpenSearch username
            password: OpenSearch password (if None, reads from token file)
        """
        self.host = host
        self.index_name = index_name
        self.username = username
        
        # Load password from file if not provided
        if password is None:
            password = get_opensearch_password()
        
        self.auth = HTTPBasicAuth(username, password)
        self.enabled = password is not None
        
        if not self.enabled:
            logger.warning("⚠️  OpenSearch indexer disabled (no credentials found)")
        else:
            logger.info(f"✅ OpenSearch indexer enabled for index: {index_name}")
            self._ensure_index_exists()
    
    def _ensure_index_exists(self):
        """Create index if it doesn't exist with parent-child relationship mapping"""
        url = f"{self.host}/{self.index_name}"
        
        try:
            response = requests.head(url, auth=self.auth, verify=VERIFY_CERTS, timeout=10)
            
            if response.status_code == 404:
                logger.info(f"📝 Creating index '{self.index_name}'...")
                self._create_index()
            elif response.status_code == 200:
                logger.info(f"✅ Index '{self.index_name}' already exists")
            else:
                logger.warning(f"⚠️  Unexpected response checking index: {response.status_code}")
        except Exception as e:
            logger.error(f"❌ Error checking index existence: {e}")
    
    def _create_index(self):
        """Create index with parent-child relationship mapping"""
        url = f"{self.host}/{self.index_name}"
        
        # Mapping with parent-child relationship using join field
        mapping = {
            "mappings": {
                "properties": {
                    "document_type": {"type": "keyword"},  # "parent" or "comment"
                    "relation": {
                        "type": "join",
                        "relations": {
                            "parent": "comment"  # parent can have many comments
                        }
                    },
                    # Common fields
                    "platform": {"type": "keyword"},  # "slack", "github", etc.
                    "created_at": {"type": "date"},
                    "updated_at": {"type": "date"},
                    
                    # Slack-specific fields
                    "slack_message_ts": {"type": "keyword"},
                    "slack_thread_ts": {"type": "keyword"},
                    "slack_channel_id": {"type": "keyword"},
                    "slack_channel_name": {"type": "keyword"},
                    "slack_user_id": {"type": "keyword"},
                    "slack_user_name": {"type": "keyword"},
                    "slack_permalink": {"type": "keyword"},
                    
                    # GitHub-specific fields
                    "github_issue_number": {"type": "integer"},
                    "github_issue_url": {"type": "keyword"},
                    "github_comment_id": {"type": "long"},
                    "github_repository": {"type": "keyword"},
                    "github_user": {"type": "keyword"},
                    
                    # Content fields
                    "title": {"type": "text"},
                    "content": {"type": "text"},
                    "content_raw": {"type": "keyword"},  # Original content without conversion
                    
                    # Metadata
                    "labels": {"type": "keyword"},
                    "state": {"type": "keyword"},
                    "assignee": {"type": "keyword"}
                }
            }
        }
        
        try:
            response = requests.put(
                url,
                auth=self.auth,
                verify=VERIFY_CERTS,
                headers={"Content-Type": "application/json"},
                json=mapping,
                timeout=10
            )
            
            if response.status_code in (200, 201):
                logger.info(f"✅ Index '{self.index_name}' created successfully")
            else:
                logger.error(f"❌ Error creating index: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"❌ Exception creating index: {e}")
    
    def index_parent(self, document: Dict) -> Optional[str]:
        """
        Index a parent document (main message/issue)
        
        Args:
            document: Document data with required fields:
                - id: Unique document ID
                - platform: Platform name ("slack", "github")
                - content: Document content
                - created_at: Creation timestamp
                And other platform-specific fields
        
        Returns:
            Document ID if successful, None otherwise
        """
        if not self.enabled:
            logger.debug("OpenSearch indexer disabled, skipping")
            return None
        
        doc_id = document.get('id')
        if not doc_id:
            logger.error("❌ Document must have an 'id' field")
            return None
        
        # Add document type and relation
        document['document_type'] = 'parent'
        document['relation'] = {'name': 'parent'}
        
        # Ensure created_at is present
        if 'created_at' not in document:
            document['created_at'] = datetime.utcnow().isoformat() + 'Z'
        
        return self._index_document(doc_id, document)
    
    def index_comment(self, document: Dict, parent_id: str) -> Optional[str]:
        """
        Index a comment/reply document as child of a parent
        
        Args:
            document: Document data with required fields:
                - id: Unique document ID
                - platform: Platform name ("slack", "github")
                - content: Document content
                - created_at: Creation timestamp
            parent_id: ID of the parent document
        
        Returns:
            Document ID if successful, None otherwise
        """
        if not self.enabled:
            logger.debug("OpenSearch indexer disabled, skipping")
            return None
        
        doc_id = document.get('id')
        if not doc_id:
            logger.error("❌ Document must have an 'id' field")
            return None
        
        if not parent_id:
            logger.error("❌ Parent ID is required for comments")
            return None
        
        # Add document type and parent relationship
        document['document_type'] = 'comment'
        document['relation'] = {
            'name': 'comment',
            'parent': parent_id
        }
        
        # Ensure created_at is present
        if 'created_at' not in document:
            document['created_at'] = datetime.utcnow().isoformat() + 'Z'
        
        # For child documents, we need to specify routing to ensure they're stored with parent
        return self._index_document(doc_id, document, routing=parent_id)
    
    def get_parent_document(self, doc_id: str) -> Optional[Dict]:
        """
        Retrieve a parent document from OpenSearch by ID
        
        Args:
            doc_id: Document ID to retrieve
        
        Returns:
            Document data if found, None otherwise
        """
        if not self.enabled:
            logger.debug("OpenSearch indexer disabled, skipping get_parent_document")
            return None
        
        url = f"{self.host}/{self.index_name}/_doc/{doc_id}"
        
        try:
            response = requests.get(
                url,
                auth=self.auth,
                verify=VERIFY_CERTS,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get('found'):
                    source = result.get('_source', {})
                    logger.debug(f"✅ Found document: {doc_id}")
                    return source
                else:
                    logger.debug(f"📭 Document not found: {doc_id}")
                    return None
            elif response.status_code == 404:
                logger.debug(f"📭 Document not found: {doc_id}")
                return None
            else:
                logger.error(f"❌ Error retrieving document {doc_id}: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            logger.error(f"❌ Exception retrieving document {doc_id}: {e}")
            return None
    
    def search_parent_by_channel(self, channel_id: str, platform: str = "discord") -> Optional[Dict]:
        """
        Search for a parent document by message_id (useful for finding thread parents)
        The channel_id passed is actually the thread channel ID which may match the parent message_id
        
        Args:
            channel_id: Discord/Slack channel/message ID to search
            platform: Platform name ("discord" or "slack")
        
        Returns:
            Document data if found, None otherwise
        """
        if not self.enabled:
            logger.debug("OpenSearch indexer disabled, skipping search")
            return None
        
        url = f"{self.host}/{self.index_name}/_search"
        
        # Build query to find parent document by discord_message_id (not channel_id)
        query = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"platform": platform}},
                        {"term": {"document_type": "parent"}},
                        {"term": {f"{platform}_message_id": channel_id}}
                    ]
                }
            },
            "size": 1
        }
        
        try:
            response = requests.post(
                url,
                auth=self.auth,
                verify=VERIFY_CERTS,
                headers={"Content-Type": "application/json"},
                json=query,
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                hits = result.get('hits', {}).get('hits', [])
                if hits:
                    source = hits[0].get('_source', {})
                    logger.debug(f"✅ Found parent by channel_id {channel_id}")
                    return source
                else:
                    logger.debug(f"📭 No parent found for channel_id: {channel_id}")
                    return None
            else:
                logger.error(f"❌ Error searching: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            logger.error(f"❌ Exception searching: {e}")
            return None
    
    def _index_document(self, doc_id: str, document: Dict, routing: Optional[str] = None) -> Optional[str]:
        """
        Index a document to OpenSearch
        
        Args:
            doc_id: Document ID
            document: Document data
            routing: Routing value (for child documents)
        
        Returns:
            Document ID if successful, None otherwise
        """
        url = f"{self.host}/{self.index_name}/_doc/{doc_id}"
        
        # Add routing parameter for child documents
        if routing:
            url += f"?routing={routing}"
        
        try:
            response = requests.put(
                url,
                auth=self.auth,
                verify=VERIFY_CERTS,
                headers={"Content-Type": "application/json"},
                json=document,
                timeout=10
            )
            
            if response.status_code in (200, 201):
                result = response.json()
                logger.info(f"✅ Indexed document: {doc_id} (result: {result.get('result', 'unknown')})")
                return doc_id
            else:
                logger.error(f"❌ Error indexing document {doc_id}: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            logger.error(f"❌ Exception indexing document {doc_id}: {e}")
            return None
    
    def bulk_index(self, documents: List[Dict]) -> Dict[str, int]:
        """
        Bulk index multiple documents
        
        Args:
            documents: List of documents, each with:
                - id: Document ID
                - document_type: "parent" or "comment"
                - parent_id: (for comments only) Parent document ID
                - ... other fields
        
        Returns:
            Dictionary with counts: {"success": int, "failed": int}
        """
        if not self.enabled:
            logger.debug("OpenSearch indexer disabled, skipping bulk index")
            return {"success": 0, "failed": 0}
        
        if not documents:
            return {"success": 0, "failed": 0}
        
        # Build bulk request payload
        lines = []
        for doc in documents:
            doc_id = doc.get('id')
            if not doc_id:
                logger.warning("⚠️  Skipping document without 'id'")
                continue
            
            # Build index action
            action = {"index": {"_index": self.index_name, "_id": doc_id}}
            
            # Add routing for child documents
            if doc.get('document_type') == 'comment' and doc.get('parent_id'):
                action["index"]["routing"] = doc.get('parent_id')
            
            lines.append(json.dumps(action))
            lines.append(json.dumps(doc))
        
        if not lines:
            logger.warning("⚠️  No valid documents to index")
            return {"success": 0, "failed": 0}
        
        payload = "\n".join(lines) + "\n"
        
        try:
            response = requests.post(
                f"{self.host}/_bulk",
                auth=self.auth,
                verify=VERIFY_CERTS,
                headers={"Content-Type": "application/x-ndjson"},
                data=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                errors = result.get("errors", False)
                items = result.get("items", [])
                
                success_count = 0
                failed_count = 0
                
                for item in items:
                    if "index" in item:
                        status = item["index"].get("status", 0)
                        if status in (200, 201):
                            success_count += 1
                        else:
                            failed_count += 1
                            error = item["index"].get("error", "unknown")
                            logger.error(f"❌ Failed to index document: {error}")
                
                logger.info(f"✅ Bulk index completed: {success_count} success, {failed_count} failed")
                return {"success": success_count, "failed": failed_count}
            else:
                logger.error(f"❌ Bulk index error: {response.status_code} - {response.text}")
                return {"success": 0, "failed": len(documents)}
        except Exception as e:
            logger.error(f"❌ Exception during bulk index: {e}")
            return {"success": 0, "failed": len(documents)}
    
    def search(self, query: Dict) -> Optional[Dict]:
        """
        Execute a search query against OpenSearch
        
        Args:
            query: OpenSearch query DSL
        
        Returns:
            Search response dictionary or None if error
        """
        if not self.enabled:
            logger.debug("OpenSearch indexer disabled, skipping search")
            return None
        
        url = f"{self.host}/{self.index_name}/_search"
        
        try:
            response = requests.post(
                url,
                auth=self.auth,
                verify=VERIFY_CERTS,
                headers={"Content-Type": "application/json"},
                json=query,
                timeout=30
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"❌ Search error: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            logger.error(f"❌ Exception during search: {e}")
            return None
    
    def update_document(self, doc_id: str, document: Dict) -> bool:
        """
        Update an existing document in OpenSearch
        
        Args:
            doc_id: Document ID to update
            document: Complete document data
        
        Returns:
            True if successful, False otherwise
        """
        if not self.enabled:
            logger.debug("OpenSearch indexer disabled, skipping update")
            return False
        
        url = f"{self.host}/{self.index_name}/_doc/{doc_id}"
        
        try:
            response = requests.put(
                url,
                auth=self.auth,
                verify=VERIFY_CERTS,
                headers={"Content-Type": "application/json"},
                json=document,
                timeout=10
            )
            
            if response.status_code in (200, 201):
                result = response.json()
                logger.debug(f"✅ Updated document: {doc_id} (result: {result.get('result', 'unknown')})")
                return True
            else:
                logger.error(f"❌ Error updating document {doc_id}: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            logger.error(f"❌ Exception updating document {doc_id}: {e}")
            return False


# ======================== Helper Functions ========================

def create_slack_parent_document(message_ts: str, channel_id: str, channel_name: str,
                                  user_id: str, user_name: str, content: str,
                                  permalink: Optional[str] = None,
                                  github_issue_number: Optional[int] = None,
                                  github_issue_url: Optional[str] = None,
                                  labels: Optional[List[str]] = None) -> Dict:
    """
    Create a parent document for a Slack message
    
    Args:
        message_ts: Slack message timestamp
        channel_id: Slack channel ID
        channel_name: Slack channel name
        user_id: Slack user ID
        user_name: Slack username
        content: Message content
        permalink: Slack permalink (optional)
        github_issue_number: GitHub issue number (optional)
        github_issue_url: GitHub issue URL (optional)
        labels: List of labels (optional)
    
    Returns:
        Document dictionary ready for indexing
    """
    return {
        'id': f"slack_{channel_id}_{message_ts}",
        'platform': 'slack',
        'document_type': 'parent',
        'created_at': datetime.utcnow().isoformat() + 'Z',
        'slack_message_ts': message_ts,
        'slack_channel_id': channel_id,
        'slack_channel_name': channel_name,
        'channel': channel_name,  # Normalized channel field
        'slack_user_id': user_id,
        'slack_user_name': user_name,
        'author': user_name,
        'slack_permalink': permalink,
        'content': content,
        'record_type': 'parent',  # For easier filtering
        'status': 'open',  # Default status for new parent documents
        'github_issue_number': github_issue_number,
        'github_issue_url': github_issue_url,
        'labels': labels or []
    }


def create_slack_comment_document(message_ts: str, thread_ts: str, channel_id: str,
                                   user_id: str, user_name: str, content: str,
                                   permalink: Optional[str] = None,
                                   github_comment_id: Optional[int] = None,
                                   github_issue_number: Optional[int] = None,
                                   github_issue_url: Optional[str] = None,
                                   channel_name: Optional[str] = None) -> Dict:
    """
    Create a comment document for a Slack thread reply
    
    Args:
        message_ts: Slack message timestamp
        thread_ts: Slack thread timestamp (parent)
        channel_id: Slack channel ID
        user_id: Slack user ID
        user_name: Slack username
        content: Message content
        permalink: Slack permalink (optional)
        github_comment_id: GitHub comment ID (optional)
        github_issue_number: GitHub issue number (optional)
        github_issue_url: GitHub issue URL (optional)
        channel_name: Slack channel name (optional, used for normalized channel field)
    
    Returns:
        Document dictionary ready for indexing
    """
    return {
        'id': f"slack_{channel_id}_{message_ts}",
        'parent_id': f"slack_{channel_id}_{thread_ts}",
        'platform': 'slack',
        'document_type': 'comment',
        'created_at': datetime.utcnow().isoformat() + 'Z',
        'slack_message_ts': message_ts,
        'slack_thread_ts': thread_ts,
        'slack_channel_id': channel_id,
        'channel': channel_name or channel_id,  # Normalized channel field with fallback
        'slack_user_id': user_id,
        'slack_user_name': user_name,
        'author': user_name,
        'slack_permalink': permalink,
        'content': content,
        'record_type': 'comment',  # For easier filtering
        'github_comment_id': github_comment_id,
        'github_issue_number': github_issue_number,
        'github_issue_url': github_issue_url
    }


# ======================== Test / Example Usage ========================

if __name__ == "__main__":
    # Example usage
    indexer = OpenSearchIndexer()
    
    if indexer.enabled:
        # Test parent document
        parent_doc = create_slack_parent_document(
            message_ts="1234567890.123456",
            channel_id="C1234567890",
            channel_name="test-channel",
            user_id="U1234567890",
            user_name="testuser",
            content="This is a test parent message",
            permalink="https://test.slack.com/archives/C1234567890/p1234567890123456",
            github_issue_number=123,
            github_issue_url="https://github.com/org/repo/issues/123",
            labels=["platform/slack", "test"]
        )
        
        result = indexer.index_parent(parent_doc)
        print(f"Parent indexed: {result}")
        
        # Test comment document
        comment_doc = create_slack_comment_document(
            message_ts="1234567890.123457",
            thread_ts="1234567890.123456",
            channel_id="C1234567890",
            user_id="U0987654321",
            user_name="anotheruser",
            content="This is a reply in the thread",
            permalink="https://test.slack.com/archives/C1234567890/p1234567890123457",
            github_comment_id=456
        )
        
        result = indexer.index_comment(comment_doc, parent_doc['id'])
        print(f"Comment indexed: {result}")
    else:
        print("Indexer not enabled (no credentials)")
