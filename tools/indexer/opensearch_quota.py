#!/usr/bin/env python3
"""
OpenSearch Quota Manager
Manages the community-quota-v1 index for storing and updating team member quotas
"""

import logging
import sys
import os
import warnings
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

# Suppress InsecureRequestWarning
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Add parent directory to path to import indexer
PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PARENT_DIR)
from indexer.opensearch_indexer import OpenSearchIndexer

# Import centralized logging
try:
    from logging_config import setup_logger
    logger = setup_logger("Auditor.Quota")
except ImportError:
    # Fallback if logging_config not available
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] [%(levelname)s] %(message)s")
    logger = logging.getLogger("Auditor.Quota")

# ======================== Configuration ========================

QUOTA_INDEX = "community-quota-v1"
TICKETS_INDEX = "tickets-raw-v1.0"


# ======================== OpenSearch Quota Manager ========================

class OpenSearchQuotaManager:
    """Manages community quota tracking in OpenSearch"""
    
    def __init__(self):
        self.indexer = OpenSearchIndexer()
        self.enabled = self.indexer.enabled
        
        if self.enabled:
            self._ensure_quota_index_exists()
            logger.info("📊 OpenSearch quota manager initialized")
        else:
            logger.warning("⚠️  OpenSearch quota manager disabled (no connection)")
    
    def _ensure_quota_index_exists(self):
        """Ensure the quota index exists with proper mapping"""
        import requests
        
        url = f"{self.indexer.host}/{QUOTA_INDEX}"
        
        try:
            response = requests.head(url, auth=self.indexer.auth, verify=False, timeout=10)
            
            if response.status_code == 404:
                logger.info(f"📝 Creating quota index: {QUOTA_INDEX}")
                
                # Mapping for quota data
                mapping = {
                    "mappings": {
                        "properties": {
                            "team": {"type": "keyword"},
                            "full_name": {"type": "text"},
                            "github_username": {"type": "keyword"},
                            "ticket_count": {"type": "integer"},
                            "country": {"type": "keyword"},
                            "status": {"type": "keyword"},
                            "pto": {"type": "keyword"},
                            "slack_user_id": {"type": "keyword"},
                            "year": {"type": "keyword"},
                            "week": {"type": "keyword"},
                            "created_at": {"type": "date"}
                        }
                    }
                }
                
                create_response = requests.put(
                    url,
                    auth=self.indexer.auth,
                    verify=False,
                    json=mapping,
                    timeout=10
                )
                
                if create_response.status_code == 200:
                    logger.info(f"✅ Created quota index: {QUOTA_INDEX}")
                else:
                    logger.error(f"❌ Failed to create quota index: {create_response.status_code}")
            
            elif response.status_code == 200:
                logger.debug(f"   Quota index exists: {QUOTA_INDEX}")
        
        except Exception as e:
            logger.error(f"❌ Error checking quota index: {e}")
    
    def get_all_ticket_counts_bulk(self, year: str, week: str) -> Dict[str, int]:
        """
        Get ticket counts for ALL users in one query from QUOTA_INDEX (BULK OPERATION)
        
        Args:
            year: Year as string (e.g., "2026") - Not used, kept for compatibility
            week: Week as string in YYYY-WW format (e.g., "2026-05")
        
        Returns:
            Dictionary mapping github_username -> ticket_count
            Example: {"user1": 5, "user2": 3, "user3": 0}
        
        Note:
            Queries the QUOTA_INDEX to get all quota documents for the specified week.
            This is MUCH faster than querying each user individually (1 query vs 200 queries).
        """
        if not self.enabled:
            return {}
        
        try:
            import requests
            
            logger.debug(f"   Fetching ALL ticket counts for week {week}...")
            
            url = f"{self.indexer.host}/{QUOTA_INDEX}/_search"
            
            # Query quota index by week and specific users
            allowed_users = ["Stuti3097", "snaow", "sakib789", "Hasitha9796", "Oajani", "bonyjohn05"]
            
            query = {
                "size": 1000,  # Get up to 1000 users (adjust if needed)
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"week": week}},
                            {"terms": {"github_username": allowed_users}}
                        ]
                    }
                },
                "_source": ["github_username", "ticket_count"]
            }
            
            response = requests.post(
                url,
                auth=self.indexer.auth,
                verify=False,
                json=query,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                hits = result.get('hits', {}).get('hits', [])
                
                # Convert documents to dictionary
                ticket_counts = {}
                for hit in hits:
                    source = hit.get('_source', {})
                    username = source.get('github_username')
                    count = source.get('ticket_count', 0)
                    if username:  # Skip documents without username
                        ticket_counts[username] = count
                
                logger.info(f"   📊 Fetched ticket counts for {len(ticket_counts)} users in single bulk query")
                return ticket_counts
            else:
                logger.warning(f"      Failed to fetch bulk ticket counts: {response.status_code}")
                return {}
        
        except Exception as e:
            logger.error(f"      Error fetching bulk ticket counts: {e}")
            return {}
    
    def get_ticket_count_for_user(self, github_username: str, year: str, week: str) -> int:
        """
        Get ticket count for a user in a specific week by querying tickets-raw-v1.0
        
        DEPRECATED: Use get_all_ticket_counts_bulk() instead for better performance.
        
        Args:
            github_username: GitHub username to count tickets for
            year: Year as string (e.g., "2026") - Currently not used in query
            week: Week as string in YYYY-WW format (e.g., "2026-04") - Currently not used in query
        
        Returns:
            Number of tickets assigned to the user (all time, not filtered by week yet)
        
        Note:
            Currently counts all tickets for the user without date filtering.
            TODO: Add week/year fields to tickets-raw-v1.0 and filter by date range.
        """
        if not self.enabled:
            return 0
        
        try:
            import requests
            
            # Query tickets index for documents where:
            # - assignee = github_username
            # - record_type = parent (only count parent documents, not comments)
            # - created_at is in the specified week/year
            
            # Calculate date range for the week
            # For simplicity, we'll query by assignee and let the caller handle week calculation
            # But ideally we'd add week/year fields to tickets-raw-v1.0
            
            url = f"{self.indexer.host}/{TICKETS_INDEX}/_count"
            
            query = {
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"record_type": "parent"}},
                            {"term": {"assignee.keyword": github_username}}
                        ]
                    }
                }
            }
            
            response = requests.post(
                url,
                auth=self.indexer.auth,
                verify=False,
                json=query,
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                count = result.get('count', 0)
                logger.debug(f"      User {github_username}: {count} tickets")
                return count
            else:
                logger.warning(f"      Failed to count tickets: {response.status_code}")
                return 0
        
        except Exception as e:
            logger.warning(f"      Error counting tickets for {github_username}: {e}")
            return 0
    
    def get_existing_quota_for_week(self, github_username: str, year: str, week: str) -> Optional[Dict]:
        """
        Check if a quota document already exists for this user in this week
        
        Args:
            github_username: GitHub username
            year: Year as string
            week: Week as string
        
        Returns:
            Existing quota document or None
        """
        if not self.enabled:
            return None
        
        try:
            import requests
            
            url = f"{self.indexer.host}/{QUOTA_INDEX}/_search"
            
            query = {
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"github_username": github_username}},
                            {"term": {"year": year}},
                            {"term": {"week": week}}
                        ]
                    }
                },
                "size": 1
            }
            
            response = requests.post(
                url,
                auth=self.indexer.auth,
                verify=False,
                json=query,
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                hits = result.get('hits', {}).get('hits', [])
                
                if hits:
                    doc = hits[0]
                    return {
                        'id': doc['_id'],
                        'data': doc['_source']
                    }
            
            return None
        
        except Exception as e:
            logger.warning(f"      Error checking existing quota: {e}")
            return None
    
    def upsert_quota(self, team_member: Any, year: str, week: str) -> bool:
        """
        Insert or update a quota document for a team member
        
        DEPRECATED: Use bulk_upsert_quotas() instead for better performance.
        This method is kept for backwards compatibility but performs individual operations.
        
        Args:
            team_member: TeamMember object with user data
            year: Year as string
            week: Week as string
        
        Returns:
            True if successful, False otherwise
        """
        if not self.enabled:
            return False
        
        try:
            import requests
            
            # No need to check if exists - OpenSearch will update if _id exists
            document = {
                "team": team_member.team,
                "full_name": team_member.full_name,
                "github_username": team_member.github_username,
                "ticket_count": team_member.ticket_count,
                "country": team_member.country,
                "status": team_member.status,
                "pto": team_member.pto,
                "slack_user_id": team_member.slack_user_id,
                "year": year,
                "week": week,
                "created_at": datetime.utcnow().isoformat() + 'Z'
            }
            
            # Deterministic ID - OpenSearch automatically upserts
            doc_id = f"{team_member.github_username}_{year}_week_{week}"
            url = f"{self.indexer.host}/{QUOTA_INDEX}/_doc/{doc_id}"
            
            response = requests.put(
                url,
                auth=self.indexer.auth,
                verify=False,
                json=document,
                timeout=10
            )
            
            if response.status_code in (200, 201):
                logger.debug(f"      ✅ Upserted quota document: {doc_id}")
                return True
            else:
                logger.warning(f"      Failed to upsert quota: {response.status_code}")
                return False
        
        except Exception as e:
            logger.warning(f"      Error upserting quota: {e}")
            return False
    
    def bulk_upsert_quotas(self, team_members: List, year: str, week: str) -> Dict[str, int]:
        """
        Bulk insert or update quota documents using OpenSearch Bulk API
        
        Args:
            team_members: List of TeamMember objects
            year: Year as string
            week: Week as string
        
        Returns:
            Dictionary with counts: {"success": int, "failed": int}
        
        Note:
            Uses Bulk API for performance (1 HTTP request instead of N).
            OpenSearch automatically upserts when using the same _id.
        """
        if not self.enabled:
            return {"success": 0, "failed": len(team_members)}
        
        if not team_members:
            logger.info("📊 No team members to upsert")
            return {"success": 0, "failed": 0}
        
        try:
            import requests
            import json
            
            logger.info(f"📊 Upserting quotas for {len(team_members)} team members using Bulk API...")
            
            # Build bulk request body (ndjson format)
            bulk_body = []
            current_time = datetime.utcnow().isoformat() + 'Z'
            
            for member in team_members:
                # Deterministic ID - same format as before
                doc_id = f"{member.github_username}_{year}_week_{week}"
                
                # Action line with index operation and _id
                action = {"index": {"_id": doc_id}}
                
                # Document with all quota fields
                document = {
                    "team": member.team,
                    "full_name": member.full_name,
                    "github_username": member.github_username,
                    "ticket_count": member.ticket_count,
                    "country": member.country,
                    "status": member.status,
                    "pto": member.pto,
                    "slack_user_id": member.slack_user_id,
                    "year": year,
                    "week": week,
                    "created_at": current_time
                }
                
                bulk_body.append(action)
                bulk_body.append(document)
            
            # Convert to ndjson format
            ndjson_data = '\n'.join(json.dumps(item) for item in bulk_body) + '\n'
            
            # Send bulk request
            url = f"{self.indexer.host}/{QUOTA_INDEX}/_bulk"
            response = requests.post(
                url,
                auth=self.indexer.auth,
                verify=False,
                data=ndjson_data,
                headers={'Content-Type': 'application/x-ndjson'},
                timeout=60
            )
            
            if response.status_code == 200:
                result = response.json()
                errors = result.get('errors', False)
                items = result.get('items', [])
                
                if errors:
                    # Count failures
                    failed = sum(1 for item in items if 'index' in item and item['index'].get('status') not in (200, 201))
                    success = len(team_members) - failed
                    logger.warning(f"   ⚠️  Bulk upsert had {failed} errors out of {len(team_members)} members")
                else:
                    success = len(team_members)
                    failed = 0
                    logger.info(f"✅ Quota upsert completed: {success} members updated")
                
                return {"success": success, "failed": failed}
            else:
                logger.error(f"❌ Bulk upsert failed with status {response.status_code}")
                return {"success": 0, "failed": len(team_members)}
        
        except Exception as e:
            logger.error(f"❌ Error in bulk upsert: {e}")
            return {"success": 0, "failed": len(team_members)}
