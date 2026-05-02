#!/usr/bin/env python3
"""
Community Assigner Library
Assigns GitHub issues to team members based on available quota
"""

import os
import sys
import logging
from typing import Optional, List, Dict
from datetime import datetime

# Add parent directory to path to import modules
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

# Import dependencies
try:
    from github import Github, Auth
    from indexer.opensearch_quota import OpenSearchQuotaManager
    from indexer.opensearch_indexer import OpenSearchIndexer
except ImportError as e:
    print(f"❌ Missing dependencies: {e}")
    print("Install with: pip install PyGithub")
    sys.exit(1)

# Import centralized logging and token manager
try:
    from logging_config import setup_logger
    from token_manager import get_github_token
    logger = setup_logger("Assigner")
except ImportError:
    # Fallback if logging_config not available
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] [%(levelname)s] %(message)s")
    logger = logging.getLogger("Assigner")
    def get_github_token():
        return None

# ======================== Configuration ========================

GITHUB_ORG = "wazuh"
GITHUB_REPO = "community-dev"
TICKETS_INDEX = "tickets-raw-v1.0"
MAX_TICKETS_PER_USER = 2


# ======================== Assigner Library ========================

class IssueAssigner:
    """
    Library for assigning GitHub issues based on quota availability
    """
    
    def __init__(self):
        """
        Initialize the Issue Assigner
        
        Args:
            github_token: GitHub token (if None, reads from centralized token manager)
        """
        logger.info("🔧 Initializing Issue Assigner...")
        
        # Initialize GitHub client
        github_token = get_github_token()
        
        if github_token is None:
            raise ValueError("GitHub token not found in centralized token manager")
        
        auth = Auth.Token(github_token)
        self.github = Github(auth=auth)
        self.repo = self.github.get_repo(f"{GITHUB_ORG}/{GITHUB_REPO}")
        
        # Initialize OpenSearch clients
        self.quota_manager = OpenSearchQuotaManager()
        self.indexer = OpenSearchIndexer(index_name=TICKETS_INDEX)
        
        logger.info("✅ Issue Assigner initialized")
    
    def get_available_users(self, max_tickets: int = MAX_TICKETS_PER_USER) -> List[Dict[str, any]]:
        """
        Get list of users with available quota (ticket_count < max_tickets)
        
        Args:
            max_tickets: Maximum tickets per user (default: 2)
        
        Returns:
            List of users with available quota, sorted by ticket count (ascending)
            Each user dict contains: github_username, ticket_count, full_name, etc.
        """
        if not self.quota_manager.enabled:
            logger.error("❌ Quota manager not enabled")
            return []
        
        try:
            # Get current year and week
            now = datetime.now()
            year = str(now.year)
            week = now.strftime("%Y-%U")  # Format: YYYY-WW
            
            # Get all ticket counts in bulk
            logger.info("📊 Fetching ticket counts for all users...")
            ticket_counts = self.quota_manager.get_all_ticket_counts_bulk(year, week)
            
            if not ticket_counts:
                logger.warning("⚠️  No ticket counts found")
                return []
            
            # Filter users with available quota
            available_users = []
            for username, count in ticket_counts.items():
                if count < max_tickets:
                    available_users.append({
                        'github_username': username,
                        'ticket_count': count,
                        'available_slots': max_tickets - count
                    })
            
            # Sort by ticket count (ascending) - prioritize users with fewer tickets
            available_users.sort(key=lambda x: x['ticket_count'])
            
            logger.info(f"✅ Found {len(available_users)} users with available quota")
            return available_users
        
        except Exception as e:
            logger.error(f"❌ Error getting available users: {e}")
            return []
    
    def assign_issue(self, issue_number: int, github_username: Optional[str] = None) -> bool:
        """
        Assign a GitHub issue to a user and update quota
        
        Args:
            issue_number: GitHub issue number to assign
            github_username: GitHub username to assign to (if None, auto-assigns to user with lowest quota)
        
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"🎯 Assigning issue #{issue_number}...")
            
            # Get the issue
            issue = self.repo.get_issue(issue_number)
            
            # If no username specified, auto-assign to user with lowest quota
            if github_username is None:
                available_users = self.get_available_users()
                
                if not available_users:
                    logger.error("❌ No users with available quota found")
                    return False
                
                # Pick user with lowest ticket count
                github_username = available_users[0]['github_username']
                logger.info(f"   Auto-assigned to: {github_username} (current tickets: {available_users[0]['ticket_count']})")
            
            # Assign in GitHub
            logger.info(f"   Assigning issue #{issue_number} to {github_username} in GitHub...")
            issue.add_to_assignees(github_username)
            
            # Update quota in OpenSearch (increment ticket_count)
            logger.info(f"   Updating quota for {github_username}...")
            success = self._update_user_quota(github_username, increment=1)
            
            if success:
                logger.info(f"✅ Successfully assigned issue #{issue_number} to {github_username}")
                
                # Also update the document in tickets-raw-v1.0
                self._update_issue_assignee_in_opensearch(issue_number, github_username)
                
                return True
            else:
                logger.error(f"❌ Failed to update quota for {github_username}")
                # Note: Issue is already assigned in GitHub, but quota update failed
                return False
        
        except Exception as e:
            logger.error(f"❌ Error assigning issue #{issue_number}: {e}")
            return False
    
    def _update_user_quota(self, github_username: str, increment: int = 1) -> bool:
        """
        Update user's ticket count in OpenSearch
        
        Args:
            github_username: GitHub username
            increment: Amount to increment ticket_count by (default: 1)
        
        Returns:
            True if successful, False otherwise
        """
        if not self.quota_manager.enabled:
            logger.error("❌ Quota manager not enabled")
            return False
        
        try:
            import requests
            
            # Get current year and week
            now = datetime.now()
            year = str(now.year)
            week = now.strftime("%Y-%U")
            
            # Deterministic document ID
            doc_id = f"{github_username}_{year}_week_{week}"
            
            # Use OpenSearch update API with script to increment ticket_count
            url = f"{self.quota_manager.indexer.host}/community-quota-v1/_update/{doc_id}"
            
            update_body = {
                "script": {
                    "source": "ctx._source.ticket_count += params.increment",
                    "params": {
                        "increment": increment
                    }
                },
                "upsert": {
                    "github_username": github_username,
                    "ticket_count": increment,
                    "year": year,
                    "week": week,
                    "created_at": datetime.utcnow().isoformat() + 'Z'
                }
            }
            
            response = requests.post(
                url,
                auth=self.quota_manager.indexer.auth,
                verify=False,
                json=update_body,
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info(f"   ✅ Updated quota for {github_username} (+{increment})")
                return True
            else:
                logger.error(f"   ❌ Failed to update quota: {response.status_code} - {response.text}")
                return False
        
        except Exception as e:
            logger.error(f"   ❌ Error updating quota: {e}")
            return False
    
    def _update_issue_assignee_in_opensearch(self, issue_number: int, github_username: str) -> bool:
        """
        Update the assignee field in tickets-raw-v1.0 for the issue
        
        Args:
            issue_number: GitHub issue number
            github_username: GitHub username to set as assignee
        
        Returns:
            True if successful, False otherwise
        """
        if not self.indexer.enabled:
            logger.debug("   OpenSearch indexer disabled, skipping document update")
            return False
        
        try:
            import requests
            
            # Search for the document by issue number
            url = f"{self.indexer.host}/{TICKETS_INDEX}/_search"
            
            query = {
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"github_issue_number": issue_number}},
                            {"term": {"document_type": "parent"}}
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
                    doc_id = hits[0]['_id']
                    
                    # Update the assignee field
                    update_url = f"{self.indexer.host}/{TICKETS_INDEX}/_update/{doc_id}"
                    update_body = {
                        "doc": {
                            "assignee": github_username
                        }
                    }
                    
                    update_response = requests.post(
                        update_url,
                        auth=self.indexer.auth,
                        verify=False,
                        json=update_body,
                        timeout=10
                    )
                    
                    if update_response.status_code == 200:
                        logger.info(f"   ✅ Updated assignee in OpenSearch for issue #{issue_number}")
                        return True
                    else:
                        logger.warning(f"   ⚠️  Failed to update assignee in OpenSearch: {update_response.status_code}")
                        return False
                else:
                    logger.warning(f"   ⚠️  Issue #{issue_number} not found in OpenSearch")
                    return False
            else:
                logger.warning(f"   ⚠️  Failed to search for issue in OpenSearch: {response.status_code}")
                return False
        
        except Exception as e:
            logger.warning(f"   ⚠️  Error updating assignee in OpenSearch: {e}")
            return False
    
    def unassign_issue(self, issue_number: int, github_username: str) -> bool:
        """
        Unassign a GitHub issue from a user and decrement quota
        
        Args:
            issue_number: GitHub issue number to unassign
            github_username: GitHub username to unassign from
        
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"🔄 Unassigning issue #{issue_number} from {github_username}...")
            
            # Get the issue
            issue = self.repo.get_issue(issue_number)
            
            # Unassign in GitHub
            issue.remove_from_assignees(github_username)
            
            # Decrement quota
            success = self._update_user_quota(github_username, increment=-1)
            
            if success:
                logger.info(f"✅ Successfully unassigned issue #{issue_number} from {github_username}")
                return True
            else:
                logger.error(f"❌ Failed to update quota for {github_username}")
                return False
        
        except Exception as e:
            logger.error(f"❌ Error unassigning issue #{issue_number}: {e}")
            return False
    
    def get_user_quota(self, github_username: str) -> Optional[Dict]:
        """
        Get current quota information for a user
        
        Args:
            github_username: GitHub username
        
        Returns:
            Dictionary with quota info or None if not found
        """
        if not self.quota_manager.enabled:
            return None
        
        try:
            now = datetime.now()
            year = str(now.year)
            week = now.strftime("%Y-%U")
            
            # Get ticket count
            ticket_counts = self.quota_manager.get_all_ticket_counts_bulk(year, week)
            count = ticket_counts.get(github_username, 0)
            
            return {
                'github_username': github_username,
                'ticket_count': count,
                'available_slots': MAX_TICKETS_PER_USER - count,
                'max_tickets': MAX_TICKETS_PER_USER
            }
        
        except Exception as e:
            logger.error(f"❌ Error getting quota for {github_username}: {e}")
            return None


# ======================== Example Usage ========================

if __name__ == "__main__":
    """Example usage of the Issue Assigner library"""
    
    # Initialize assigner
    assigner = IssueAssigner()
    
    # Get available users
    print("\n📊 Available users with quota:")
    available = assigner.get_available_users()
    for user in available[:10]:  # Show first 10
        print(f"   - {user['github_username']}: {user['ticket_count']}/{MAX_TICKETS_PER_USER} tickets")
    
    # Example: Assign an issue (uncomment to test)
    # assigner.assign_issue(12345)  # Auto-assigns to user with lowest quota
    # assigner.assign_issue(12345, "username")  # Assigns to specific user
    
    # Example: Get user quota
    # quota = assigner.get_user_quota("username")
    # if quota:
    #     print(f"\nQuota for {quota['github_username']}: {quota['ticket_count']}/{quota['max_tickets']}")
