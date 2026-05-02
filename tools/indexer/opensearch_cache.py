#!/usr/bin/env python3
"""
OpenSearch Cache Manager - Replacement for SQLite cache
Uses OpenSearch indices for caching GitHub teams, Slack members, and project issues
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

# Add parent directory to path for imports
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)
from indexer.opensearch_indexer import OpenSearchIndexer

# Import centralized logging
try:
    from logging_config import setup_logger
    logger = setup_logger("Auditor.Cache")
except ImportError:
    # Fallback if logging_config not available
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] [%(levelname)s] %(message)s")
    logger = logging.getLogger("Auditor.Cache")

# ======================== Configuration ========================

# Index names for caching
GITHUB_TEAMS_INDEX = "github-teams-cache"
SLACK_MEMBERS_INDEX = "slack-members-cache"
SLACK_MEMBERS_HISTORY_INDEX = "slack-members-history-v2.0"  # Historical data (no overwrites)
PROJECT_ISSUES_INDEX = "project-issues-cache"

# Cache expiry hours
CACHE_EXPIRY_HOURS = {
    'github_teams': 24,           # Teams don't change often
    'slack_members': 5 / 60,      # 60 minutes - presence/DND change frequently
    'project_issues': 15 / 60     # 15 minutes - Issues change frequently
}


# ======================== OpenSearch Cache Manager ========================

class OpenSearchCacheManager:
    """Manages OpenSearch-based cache for API data"""
    
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        
        if self.enabled:
            # Initialize OpenSearch indexer
            self.indexer = OpenSearchIndexer()
            
            if not self.indexer.enabled:
                logger.warning("⚠️  OpenSearch not available, cache disabled")
                self.enabled = False
            else:
                # Create indices if they don't exist
                self._ensure_indices_exist()
                logger.info("💾 OpenSearch cache system initialized")
        else:
            logger.info("💾 Cache system disabled")
    
    def _ensure_indices_exist(self):
        """Ensure all cache indices exist"""
        indices = [
            GITHUB_TEAMS_INDEX, 
            SLACK_MEMBERS_INDEX, 
            SLACK_MEMBERS_HISTORY_INDEX,  # Historical data
            PROJECT_ISSUES_INDEX
        ]
        
        for index_name in indices:
            self._ensure_index_exists(index_name)
    
    def _ensure_index_exists(self, index_name: str):
        """Create an index if it doesn't exist"""
        import requests
        from requests.auth import HTTPBasicAuth
        
        url = f"{self.indexer.host}/{index_name}"
        
        try:
            response = requests.head(url, auth=self.indexer.auth, verify=False, timeout=10)
            
            if response.status_code == 404:
                logger.debug(f"   Creating cache index: {index_name}")
                
                # Mapping specific to each index
                if index_name == SLACK_MEMBERS_INDEX:
                    # Slack members cache with specific fields including DND timestamps
                    mapping = {
                        "mappings": {
                            "properties": {
                                "cached_at": {"type": "date"},
                                "full_name": {"type": "text"},
                                "user_id": {"type": "keyword"},
                                "github_username": {"type": "keyword"},
                                "country": {"type": "keyword"},
                                "email": {"type": "keyword"},
                                "pto": {"type": "boolean"},
                                "status": {"type": "keyword"},
                                "available": {"type": "keyword"},
                                "dnd_enabled": {"type": "boolean"},
                                "next_dnd_start_ts": {"type": "date", "format": "epoch_second"},
                                "next_dnd_end_ts": {"type": "date", "format": "epoch_second"}
                            }
                        }
                    }
                elif index_name == SLACK_MEMBERS_HISTORY_INDEX:
                    # Historical Slack members data (same schema but with inserted_at)
                    mapping = {
                        "mappings": {
                            "properties": {
                                "inserted_at": {"type": "date"},
                                "full_name": {"type": "text"},
                                "user_id": {"type": "keyword"},
                                "github_username": {"type": "keyword"},
                                "country": {"type": "keyword"},
                                "email": {"type": "keyword"},
                                "pto": {"type": "boolean"},
                                "status": {"type": "keyword"},
                                "available": {"type": "keyword"},
                                "dnd_enabled": {"type": "boolean"},
                                "next_dnd_start_ts": {"type": "date", "format": "epoch_second"},
                                "next_dnd_end_ts": {"type": "date", "format": "epoch_second"}
                            }
                        }
                    }
                else:
                    # Generic mapping for other cache indices
                    mapping = {
                        "mappings": {
                            "properties": {
                                "cached_at": {"type": "date"},
                                "data": {"type": "object", "enabled": True}
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
                    logger.debug(f"   ✅ Created cache index: {index_name}")
                else:
                    logger.warning(f"   ⚠️  Failed to create cache index: {index_name}")
            
            elif response.status_code == 200:
                logger.debug(f"   Cache index exists: {index_name}")
        
        except Exception as e:
            logger.warning(f"   ⚠️  Error checking cache index {index_name}: {e}")
    
    def _is_cache_valid(self, index_name: str, cache_type: str) -> bool:
        """Check if cached data is still valid based on expiry time"""
        if not self.enabled:
            return False
        
        try:
            import requests
            
            # Query the specific cache index (not the default tickets index)
            url = f"{self.indexer.host}/{index_name}/_search"
            
            query = {
                "size": 1,
                "sort": [{"cached_at": {"order": "desc"}}],
                "_source": ["cached_at"]
            }
            
            response = requests.post(
                url,
                auth=self.indexer.auth,
                verify=False,
                json=query,
                timeout=10
            )
            
            if response.status_code != 200:
                logger.debug(f"   Cache index {index_name} query failed or empty")
                return False
            
            result = response.json()
            hits = result.get('hits', {}).get('hits', [])
            
            if not hits:
                return False
            
            hit = hits[0]
            cached_at_str = hit['_source'].get('cached_at')
            
            if not cached_at_str:
                return False
            
            cached_time = datetime.fromisoformat(cached_at_str.replace('Z', '+00:00'))
            current_time = datetime.now(timezone.utc)
            hours_elapsed = (current_time - cached_time).total_seconds() / 3600
            
            expiry_hours = CACHE_EXPIRY_HOURS.get(cache_type, 24)
            is_valid = hours_elapsed < expiry_hours
            
            if is_valid:
                logger.debug(f"   Cache valid for {cache_type} ({hours_elapsed:.1f}h < {expiry_hours}h)")
            else:
                logger.debug(f"   Cache expired for {cache_type} ({hours_elapsed:.1f}h >= {expiry_hours}h)")
            
            return is_valid
        
        except Exception as e:
            logger.warning(f"   ⚠️  Error checking cache validity: {e}")
            return False
    
    def _save_to_cache(self, index_name: str, doc_id: str, data: Any):
        """Save data to cache index"""
        if not self.enabled:
            return
        
        try:
            import requests
            
            # Change index temporarily for cache operations
            original_index = self.indexer.index_name
            self.indexer.index_name = index_name
            
            document = {
                "cached_at": datetime.utcnow().isoformat() + 'Z',
                "data": data
            }
            
            url = f"{self.indexer.host}/{index_name}/_doc/{doc_id}"
            response = requests.put(
                url,
                auth=self.indexer.auth,
                verify=False,
                json=document,
                timeout=10
            )
            
            # Restore original index
            self.indexer.index_name = original_index
            
            if response.status_code in (200, 201):
                logger.debug(f"   Saved to cache: {index_name}/{doc_id}")
            else:
                logger.warning(f"   Failed to save to cache: {response.status_code}")
        
        except Exception as e:
            logger.warning(f"   ⚠️  Error saving to cache: {e}")
            # Restore original index on error
            self.indexer.index_name = original_index
    
    def _get_from_cache(self, index_name: str, doc_id: str) -> Optional[Any]:
        """Get data from cache index"""
        if not self.enabled:
            return None
        
        try:
            import requests
            
            url = f"{self.indexer.host}/{index_name}/_doc/{doc_id}"
            response = requests.get(
                url,
                auth=self.indexer.auth,
                verify=False,
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get('found'):
                    return result['_source'].get('data')
            
            return None
        
        except Exception as e:
            logger.warning(f"   ⚠️  Error getting from cache: {e}")
            return None
    
    def _clear_cache_index(self, index_name: str):
        """Clear all documents in a cache index"""
        if not self.enabled:
            return
        
        try:
            import requests
            
            # Delete by query - delete all documents
            url = f"{self.indexer.host}/{index_name}/_delete_by_query"
            query = {"query": {"match_all": {}}}
            
            response = requests.post(
                url,
                auth=self.indexer.auth,
                verify=False,
                json=query,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                deleted = result.get('deleted', 0)
                logger.info(f"   Deleted {deleted} documents from {index_name}")
        
        except Exception as e:
            logger.warning(f"   ⚠️  Error clearing cache: {e}")
    
    # ======================== GitHub Teams Cache ========================
    
    def get_github_teams(self) -> Optional[List[Dict]]:
        """Retrieve GitHub teams from cache"""
        if not self.enabled:
            return None
        
        if not self._is_cache_valid(GITHUB_TEAMS_INDEX, 'github_teams'):
            return None
        
        data = self._get_from_cache(GITHUB_TEAMS_INDEX, 'teams_data')
        
        if data:
            teams = data.get('teams', [])
            logger.info(f"💾 Loaded {len(teams)} GitHub teams from OpenSearch cache")
            return teams
        
        return None
    
    def save_github_teams(self, teams: List[Any]):
        """Save GitHub teams to cache"""
        if not self.enabled:
            return
        
        teams_data = {
            'teams': [{'name': team.name, 'slug': team.slug, 'id': team.id} for team in teams]
        }
        
        # IMPORTANT: When updating teams, clear old member documents
        # This forces a refresh of team members on next access
        logger.debug(f"   Clearing old team member documents...")
        self._clear_team_members_cache()
        
        self._save_to_cache(GITHUB_TEAMS_INDEX, 'teams_data', teams_data)
        logger.info(f"💾 Saved {len(teams)} GitHub teams to OpenSearch cache")
    
    def get_team_members(self, team_slug: str) -> Optional[List[Dict]]:
        """Retrieve team members from cache"""
        if not self.enabled:
            return None
        
        # IMPORTANT: Check if cache is valid before returning data
        # This ensures members are refreshed when teams cache expires
        if not self._is_cache_valid(GITHUB_TEAMS_INDEX, 'github_teams'):
            logger.debug(f"      Team members cache expired for '{team_slug}'")
            return None
        
        data = self._get_from_cache(GITHUB_TEAMS_INDEX, f'team_members_{team_slug}')
        
        if data:
            members = data.get('members', [])
            logger.debug(f"      Loaded {len(members)} members for team '{team_slug}' from cache")
            return members
        
        return None
    
    def save_team_members(self, team_slug: str, members: List[Any]):
        """Save team members to cache"""
        if not self.enabled:
            return
        
        members_data = {
            'members': [{'login': member.login, 'id': member.id} for member in members]
        }
        
        self._save_to_cache(GITHUB_TEAMS_INDEX, f'team_members_{team_slug}', members_data)
        logger.debug(f"      Saved {len(members)} members for team '{team_slug}' to cache")
    
    def _clear_team_members_cache(self):
        """Clear only team_members_* documents from GitHub teams cache"""
        if not self.enabled:
            return
        
        try:
            import requests
            
            # Delete by query - delete all documents with ID starting with 'team_members_'
            url = f"{self.indexer.host}/{GITHUB_TEAMS_INDEX}/_delete_by_query"
            query = {
                "query": {
                    "prefix": {
                        "_id": "team_members_"
                    }
                }
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
                deleted = result.get('deleted', 0)
                logger.debug(f"   Deleted {deleted} team member documents from cache")
        
        except Exception as e:
            logger.warning(f"   ⚠️  Error clearing team members cache: {e}")
    
    # ======================== Slack Members Cache ========================
    
    def get_slack_members(self) -> Optional[List]:
        """Retrieve Slack members from cache - one document per user"""
        if not self.enabled:
            return None
        
        if not self._is_cache_valid(SLACK_MEMBERS_INDEX, 'slack_members'):
            return None
        
        try:
            import requests
            
            # Query all documents in the slack members cache
            url = f"{self.indexer.host}/{SLACK_MEMBERS_INDEX}/_search"
            query = {
                "query": {"match_all": {}},
                "size": 1000  # Adjust if you have more members
            }
            
            response = requests.post(
                url,
                auth=self.indexer.auth,
                verify=False,
                json=query,
                timeout=10
            )
            
            if response.status_code != 200:
                return None
            
            result = response.json()
            hits = result.get('hits', {}).get('hits', [])
            
            if not hits:
                return None
            
            # Import SlackMember from auditor module
            import sys
            import os
            auditor_path = os.path.join(PARENT_DIR, 'auditor', 'auditor.py')
            import importlib.util
            spec = importlib.util.spec_from_file_location("auditor_module", auditor_path)
            auditor_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(auditor_module)
            SlackMember = auditor_module.SlackMember
            
            members = []
            for hit in hits:
                data = hit['_source']
                members.append(SlackMember(
                    full_name=data.get('full_name', ''),
                    user_id=data.get('user_id', ''),
                    github_username=data.get('github_username', ''),
                    country=data.get('country', ''),
                    pto=data.get('pto', False),
                    email=data.get('email', ''),
                    status=data.get('status', 'away'),
                    available=data.get('available', 'no'),
                    dnd_enabled=data.get('dnd_enabled', False),
                    next_dnd_start_ts=data.get('next_dnd_start_ts'),
                    next_dnd_end_ts=data.get('next_dnd_end_ts'),
                    status_text=data.get('status_text', ''),
                    status_emoji=data.get('status_emoji', ''),
                    utc_working_hours=data.get('utc_working_hours', '')
                ))
            
            logger.info(f"💾 Loaded {len(members)} Slack members from OpenSearch cache")
            return members
        
        except Exception as e:
            logger.warning(f"   ⚠️  Error loading Slack members from cache: {e}")
            return None
    
    def save_slack_members(self, members: List):
        """Save Slack members to cache using Bulk API - one document per user
        
        Saves to TWO indices:
        1. slack-members-cache: Current snapshot (replaces old data)
        2. slack-members-history-v2.0: Historical log (appends new data)
        """
        if not self.enabled:
            return
        
        try:
            import requests
            import json
            
            # Clear old cache data first (only for cache, not history)
            self._clear_cache_index(SLACK_MEMBERS_INDEX)
            
            current_time = datetime.utcnow().isoformat() + 'Z'
            
            # ========== 1. Save to CACHE index (replaces data) ==========
            bulk_body_cache = []
            
            for member in members:
                # Action line with _id (will replace if exists)
                action = {"index": {"_id": member.user_id}}
                
                # Document with cached_at
                document = {
                    "cached_at": current_time,
                    "full_name": member.full_name,
                    "user_id": member.user_id,
                    "github_username": member.github_username,
                    "country": member.country,
                    "email": member.email,
                    "pto": member.pto,
                    "status": member.status,
                    "available": member.available,
                    "dnd_enabled": member.dnd_enabled,
                    "next_dnd_start_ts": member.next_dnd_start_ts,
                    "next_dnd_end_ts": member.next_dnd_end_ts,
                    "status_text": member.status_text,
                    "status_emoji": member.status_emoji,
                    "utc_working_hours": member.utc_working_hours,
                    "city": member.city,
                    "title": member.title
                }
                
                bulk_body_cache.append(action)
                bulk_body_cache.append(document)
            
            # Send bulk request to cache index
            ndjson_cache = '\n'.join(json.dumps(item) for item in bulk_body_cache) + '\n'
            url_cache = f"{self.indexer.host}/{SLACK_MEMBERS_INDEX}/_bulk"
            
            response_cache = requests.post(
                url_cache,
                auth=self.indexer.auth,
                verify=False,
                data=ndjson_cache,
                headers={'Content-Type': 'application/x-ndjson'},
                timeout=30
            )
            
            # ========== 2. Save to HISTORY index (appends data) ==========
            bulk_body_history = []
            
            for member in members:
                # Action line WITHOUT _id (OpenSearch auto-generates unique ID)
                action = {"index": {}}
                
                # Document with inserted_at instead of cached_at
                document = {
                    "inserted_at": current_time,
                    "full_name": member.full_name,
                    "user_id": member.user_id,
                    "github_username": member.github_username,
                    "country": member.country,
                    "email": member.email,
                    "pto": member.pto,
                    "status": member.status,
                    "available": member.available,
                    "dnd_enabled": member.dnd_enabled,
                    "next_dnd_start_ts": member.next_dnd_start_ts,
                    "next_dnd_end_ts": member.next_dnd_end_ts,
                    "status_text": member.status_text,
                    "status_emoji": member.status_emoji,
                    "utc_working_hours": member.utc_working_hours,
                    "city": member.city,
                    "title": member.title
                }
                
                bulk_body_history.append(action)
                bulk_body_history.append(document)
            
            # Send bulk request to history index
            ndjson_history = '\n'.join(json.dumps(item) for item in bulk_body_history) + '\n'
            url_history = f"{self.indexer.host}/{SLACK_MEMBERS_HISTORY_INDEX}/_bulk"
            
            response_history = requests.post(
                url_history,
                auth=self.indexer.auth,
                verify=False,
                data=ndjson_history,
                headers={'Content-Type': 'application/x-ndjson'},
                timeout=30
            )
            
            # ========== Process results ==========
            cache_success = False
            history_success = False
            
            if response_cache.status_code == 200:
                result = response_cache.json()
                errors = result.get('errors', False)
                items = result.get('items', [])
                
                if errors:
                    failed = sum(1 for item in items if 'index' in item and item['index'].get('status') not in (200, 201))
                    logger.warning(f"   ⚠️  Cache bulk save had {failed} errors out of {len(members)} members")
                else:
                    logger.info(f"💾 Saved {len(members)} Slack members to cache")
                    cache_success = True
            else:
                logger.warning(f"   ⚠️  Cache bulk save failed with status {response_cache.status_code}")
            
            if response_history.status_code == 200:
                result = response_history.json()
                errors = result.get('errors', False)
                items = result.get('items', [])
                
                if errors:
                    failed = sum(1 for item in items if 'index' in item and item['index'].get('status') not in (200, 201))
                    logger.warning(f"   ⚠️  History bulk save had {failed} errors out of {len(members)} members")
                else:
                    logger.info(f"📚 Saved {len(members)} Slack members to history")
                    history_success = True
            else:
                logger.warning(f"   ⚠️  History bulk save failed with status {response_history.status_code}")
            
            if cache_success and history_success:
                logger.info(f"✅ Successfully saved to both cache and history indices")
        
        except Exception as e:
            logger.warning(f"   ⚠️  Error saving Slack members: {e}")
    
    # ======================== Project Issues Cache ========================
    
    def get_project_issues(self) -> Optional[List]:
        """Retrieve project issues from cache"""
        if not self.enabled:
            return None
        
        if not self._is_cache_valid(PROJECT_ISSUES_INDEX, 'project_issues'):
            return None
        
        data = self._get_from_cache(PROJECT_ISSUES_INDEX, 'issues_data')
        
        if data:
            # Import GitHubIssue from auditor module
            import sys
            import os
            auditor_path = os.path.join(PARENT_DIR, 'auditor', 'auditor.py')
            import importlib.util
            spec = importlib.util.spec_from_file_location("auditor_module", auditor_path)
            auditor_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(auditor_module)
            GitHubIssue = auditor_module.GitHubIssue
            
            issues_dict = data.get('issues', [])
            issues = []
            
            for i in issues_dict:
                created_at_str = i.get('created_at')
                created_at = datetime.fromisoformat(created_at_str) if created_at_str else datetime.now(timezone.utc)
                
                issues.append(GitHubIssue(
                    number=i.get('number', 0),
                    title=i.get('title', ''),
                    assignees=i.get('assignees', []),
                    created_at=created_at,
                    status=i.get('status'),
                    team=i.get('team'),
                    time=i.get('time'),
                    year=i.get('year'),
                    week=i.get('week'),
                    node_id=i.get('node_id')
                ))
            
            logger.info(f"💾 Loaded {len(issues)} project issues from OpenSearch cache")
            return issues
        
        return None
    
    def save_project_issues(self, issues: List):
        """Save project issues to cache"""
        if not self.enabled:
            return
        
        issues_data = {
            'issues': [
                {
                    'number': i.number,
                    'title': i.title,
                    'assignees': i.assignees,
                    'created_at': i.created_at.isoformat() if i.created_at else None,
                    'status': i.status,
                    'team': i.team,
                    'time': i.time,
                    'year': i.year,
                    'week': i.week,
                    'node_id': i.node_id
                }
                for i in issues
            ]
        }
        
        self._save_to_cache(PROJECT_ISSUES_INDEX, 'issues_data', issues_data)
        logger.info(f"💾 Saved {len(issues)} project issues to OpenSearch cache")
    
    # ======================== Cache Management ========================
    
    def clear_cache(self, cache_type: Optional[str] = None):
        """Clear cache data"""
        if not self.enabled:
            return
        
        if cache_type == 'github_teams':
            self._clear_cache_index(GITHUB_TEAMS_INDEX)
            logger.info("💾 Cleared GitHub teams cache")
        elif cache_type == 'slack_members':
            self._clear_cache_index(SLACK_MEMBERS_INDEX)
            logger.info("💾 Cleared Slack members cache")
        elif cache_type == 'project_issues':
            self._clear_cache_index(PROJECT_ISSUES_INDEX)
            logger.info("💾 Cleared project issues cache")
        else:
            # Clear all
            self._clear_cache_index(GITHUB_TEAMS_INDEX)
            self._clear_cache_index(SLACK_MEMBERS_INDEX)
            self._clear_cache_index(PROJECT_ISSUES_INDEX)
            logger.info("💾 Cleared all OpenSearch cache data")
