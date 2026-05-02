#!/usr/bin/env python3
"""
Community Auditor - Team Summary Generator
Generates weekly team summaries for Google Sheets and OpenSearch
Migrated from Google Apps Script summary.js
Now uses OpenSearch instead of SQLite for caching and quota tracking
"""

import os
import json
import logging
import sys
import warnings
import time
from dotenv import load_dotenv

from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from dataclasses import dataclass, asdict

# Suppress InsecureRequestWarning
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Get script directory first
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)

# Add parent directory (tools/) to Python path for absolute imports
sys.path.insert(0, PARENT_DIR)

# Third-party libraries
try:
    from github import Github, Auth
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError as e:
    print(f"❌ Missing dependencies: {e}")
    print("Install with: cd ../.. && pip install -r tools/requirements.txt")
    exit(1)

# Import OpenSearch modules from indexer/
try:
    from indexer.opensearch_cache import OpenSearchCacheManager
    from indexer.opensearch_quota import OpenSearchQuotaManager
except ImportError as e:
    print(f"❌ Missing OpenSearch modules: {e}")
    print(f"Expected in: {PARENT_DIR}/indexer/")
    exit(1)

# Import centralized token manager
try:
    from token_manager import get_github_token, get_slack_user_workspace_wazuh_team
except ImportError as e:
    print(f"❌ Missing token_manager: {e}")
    print("Make sure token_manager.py exists in tools/ directory")
    exit(1)

# ======================== Cache Configuration ========================

# Global cache toggle - Set to True to use cache, False to always fetch fresh data
CACHE_ENABLED = True

# Individual cache toggles for each data type
CACHE_GITHUB_TEAMS = True      # Cache GitHub teams data
CACHE_SLACK_MEMBERS = True     # Cache Slack members data  
CACHE_PROJECT_ISSUES = True    # Cache GitHub project issues

# ======================== Configuration ========================

# SCRIPT_DIR already defined above for .env loading
GITHUB_TOKEN_FILE = os.path.join(SCRIPT_DIR, '.token_github')
SLACK_BOT_TOKEN_FILE = os.path.join(SCRIPT_DIR, '.token_slack')
GOOGLE_CREDENTIALS_FILE = os.path.join(SCRIPT_DIR, '.credentials_google.json')
LOG_FILE = os.path.join(SCRIPT_DIR, 'community_auditor.log')

# GitHub Configuration
GITHUB_ORG = "wazuh"
GITHUB_REPO = "community"
GITHUB_PROJECT_NODE_ID = "PVT_kwDOANHY9s4AKR_X"
GITHUB_ALLOWED_TEAMS = [
    "devel-xdrsiem-agent", "devel-xdrsiem-server", "devel-xdrsiem-indexer",
    "devel-xdrsiem-dashboard", "devel-xdrsiem-qa", "devel-xdrsiem-devops",
    "devel-cti-threatintel", "devel-cti-development-div2", "devel-cloud-platform",
    "devel-cloud-cicd", "devel-cloud-ops", "devel-cloud-threatintel",
    "content", "ops-support", "ops-presales", "community", "ops-tam", "ops-trainings"
]
GITHUB_EXCLUSION_LIST = ["wazuhci", "wazuh-cloud-cicd", "havidarou", "wazuh-community"]

# Google Sheets Configuration
SPREADSHEET_NAME = "Community summary - Dev"
SHEET_NAME = "Summary"

# Slack Configuration (for testing)
MAX_SLACK_MEMBERS_FOR_TESTING = 1000  # Limit members for testing purposes

# Setup logging with environment variable support
# Load .env file FIRST, before reading environment variables
env_path = os.path.join(SCRIPT_DIR, '.env')
print(env_path)
print(f"🔧 Loading .env from: {env_path}")
print(f"🔧 .env exists: {os.path.exists(env_path)}")
load_dotenv(dotenv_path=env_path)
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()
print(f"🔧 LOG_LEVEL from env: {os.environ.get('LOG_LEVEL', 'NOT SET')}")
print(f"🔧 Final LOG_LEVEL: {LOG_LEVEL}")

# Force reconfigure logging (basicConfig only works once, need to force it)
root_logger = logging.getLogger()
root_logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

# Clear existing handlers and add new ones
for handler in root_logger.handlers[:]:
    root_logger.removeHandler(handler)

# Add new handlers with correct level
file_handler = logging.FileHandler(LOG_FILE, mode="a")
file_handler.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

stream_handler = logging.StreamHandler()
stream_handler.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
stream_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

root_logger.addHandler(file_handler)
root_logger.addHandler(stream_handler)

print(f"🔧 Logger configured with level: {root_logger.level} ({logging.getLevelName(root_logger.level)})")




# ======================== Data Classes ========================

@dataclass
class SlackMember:
    """Represents a Slack member"""
    full_name: str
    user_id: str
    github_username: str
    country: str
    pto: bool
    email: str = ""  # Email address from profile
    status: str = "away"  # Presence from Slack API: active, away
    available: str = "no"  # yes/no - active AND not in DND period
    dnd_enabled: bool = False  # Whether user has DND scheduled
    next_dnd_start_ts: Optional[int] = None  # Unix timestamp
    next_dnd_end_ts: Optional[int] = None  # Unix timestamp
    status_text: str = ""  # Slack status text
    status_emoji: str = ""  # Slack status emoji
    utc_working_hours: str = ""  # UTC working hours from profile
    city: str = ""  # City from profile
    title: str = ""  # Title from profile

    def to_dict(self) -> dict:
        return {
            'full_name': self.full_name,
            'title': self.title,
            'user_id': self.user_id,
            'github_username': self.github_username,
            'country': self.country,
            'city': self.city,
            'email': self.email,
            'pto': self.pto,
            'status': self.status,
            'available': self.available,
            'dnd_enabled': self.dnd_enabled,
            'next_dnd_start_ts': self.next_dnd_start_ts,
            'next_dnd_end_ts': self.next_dnd_end_ts,
            'status_text': self.status_text,
            'status_emoji': self.status_emoji,
            'utc_working_hours': self.utc_working_hours
        }


@dataclass
class GitHubIssue:
    """Represents a GitHub issue from project"""
    number: int
    title: str
    assignees: List[str]
    created_at: datetime
    status: Optional[str] = None
    team: Optional[str] = None
    time: Optional[float] = None
    year: Optional[str] = None
    week: Optional[str] = None
    node_id: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            'number': self.number,
            'title': self.title,
            'assignees': self.assignees,
            'created_at': self.created_at.isoformat(),
            'status': self.status,
            'team': self.team,
            'time': self.time,
            'year': self.year,
            'week': self.week
        }


@dataclass
class TeamMember:
    """Represents a team member for summary"""
    team: str
    full_name: str
    github_username: str
    ticket_count: int
    country: str
    status: str
    pto: str
    slack_user_id: str
    email: str = ""
    priority: str = "c"
    
    def to_list(self) -> List[Any]:
        """Convert to list for Google Sheets (without priority)"""
        return [
            self.team,
            self.full_name,
            self.github_username,
            self.ticket_count,
            self.country,
            self.status,
            self.pto,
            self.slack_user_id,
            self.email
        ]


# ======================== Cache Manager ========================

class CacheManager:
    """Wrapper for OpenSearch Cache Manager"""
    
    def __init__(self):
        self.enabled = CACHE_ENABLED
        
        if self.enabled:
            self.opensearch_cache = OpenSearchCacheManager(enabled=True)
            self.enabled = self.opensearch_cache.enabled
            logging.info(f"💾 Cache system initialized (OpenSearch-based)")
        else:
            self.opensearch_cache = None
            logging.info("💾 Cache system disabled")
    
    def get_github_teams(self) -> Optional[List[Dict]]:
        if not self.enabled or not CACHE_GITHUB_TEAMS:
            return None
        return self.opensearch_cache.get_github_teams()
    
    def save_github_teams(self, teams: List[Any]):
        if not self.enabled or not CACHE_GITHUB_TEAMS:
            return
        self.opensearch_cache.save_github_teams(teams)
    
    def get_team_members(self, team_slug: str) -> Optional[List[Dict]]:
        if not self.enabled or not CACHE_GITHUB_TEAMS:
            return None
        return self.opensearch_cache.get_team_members(team_slug)
    
    def save_team_members(self, team_slug: str, members: List[Any]):
        if not self.enabled or not CACHE_GITHUB_TEAMS:
            return
        self.opensearch_cache.save_team_members(team_slug, members)
    
    def get_slack_members(self) -> Optional[List]:
        if not self.enabled or not CACHE_SLACK_MEMBERS:
            return None
        return self.opensearch_cache.get_slack_members()
    
    def save_slack_members(self, members: List):
        if not self.enabled or not CACHE_SLACK_MEMBERS:
            return
        self.opensearch_cache.save_slack_members(members)
    
    def get_project_issues(self) -> Optional[List]:
        if not self.enabled or not CACHE_PROJECT_ISSUES:
            return None
        return self.opensearch_cache.get_project_issues()
    
    def save_project_issues(self, issues: List):
        if not self.enabled or not CACHE_PROJECT_ISSUES:
            return
        self.opensearch_cache.save_project_issues(issues)
    
    def clear_cache(self, cache_type: Optional[str] = None):
        if not self.enabled:
            return
        self.opensearch_cache.clear_cache(cache_type)


# ======================== Token Manager ========================
# Now using centralized token_manager.py from tools/ directory


# ======================== Date Utilities ========================

class DateUtils:
    """Utility functions for date/time operations"""
    
    @staticmethod
    def get_current_year() -> str:
        """Get current year as string"""
        year = str(datetime.now().year)
        logging.debug(f"📅 Current year: {year}")
        return year
    
    @staticmethod
    def get_current_week() -> str:
        """Get current week in YYYY-WW format (counting only working days)"""
        logging.debug("📅 Calculating current week number (working days only)...")
        date = datetime.now()
        year = date.year
        
        first_day = datetime(year, 1, 1)
        current_date = first_day
        week_counter = 1
        first_week_found = False
        
        while current_date <= date:
            if current_date.weekday() < 5:  # Monday-Friday
                if current_date.weekday() == 0 and first_week_found:
                    week_counter += 1
                first_week_found = True
            
            # Move to next day
            next_day = current_date.day + 1
            if next_day > 28:
                try:
                    current_date = current_date.replace(day=next_day)
                except ValueError:
                    # End of month, move to next month
                    if current_date.month == 12:
                        current_date = datetime(current_date.year + 1, 1, 1)
                    else:
                        current_date = datetime(current_date.year, current_date.month + 1, 1)
            else:
                current_date = current_date.replace(day=next_day)
        
        week_str = f"{year}-{week_counter:02d}"
        logging.debug(f"   Current week: {week_str}")
        return week_str
    
    @staticmethod
    def get_week_from_date(date: datetime) -> str:
        """Get week number from specific date"""
        # Remove timezone info if present for comparison
        if date.tzinfo is not None:
            date = date.replace(tzinfo=None)
        
        start_date = datetime(date.year, 1, 1)
        days = (date - start_date).days
        week_number = (days // 7) + 1
        return str(week_number)


# ======================== GitHub API Client ========================

class GitHubAPIClient:
    """Handles GitHub API interactions"""
    
    def __init__(self, token: str, cache_manager: Optional['CacheManager'] = None):
        logging.debug(f"🔧 Initializing GitHub client for org '{GITHUB_ORG}'...")
        self.auth = Auth.Token(token)
        self.client = Github(auth=self.auth)
        self.cache = cache_manager
        logging.debug(f"   Connecting to organization '{GITHUB_ORG}'...")
        self.org = self.client.get_organization(GITHUB_ORG)
        logging.debug(f"   Accessing repository '{GITHUB_REPO}'...")
        self.repo = self.org.get_repo(GITHUB_REPO)
        logging.info(f"✅ GitHub client initialized (org: {GITHUB_ORG}, repo: {GITHUB_REPO})")
    
    def get_teams(self) -> List[Any]:
        """Get filtered GitHub teams"""
        # Try cache first
        if self.cache:
            cached_teams = self.cache.get_github_teams()
            if cached_teams:
                # Convert cached dict back to team-like objects
                class CachedTeam:
                    def __init__(self, data):
                        self.name = data['name']
                        self.slug = data['slug']
                        self.id = data['id']
                
                return [CachedTeam(t) for t in cached_teams]
        
        # Fetch from API
        logging.info("📋 Fetching GitHub teams from API...")
        logging.info(f"   Allowed teams: {len(GITHUB_ALLOWED_TEAMS)}")
        all_teams = list(self.org.get_teams())
        logging.info(f"   Total teams in org: {len(all_teams)}")
        filtered_teams = [team for team in all_teams if team.name in GITHUB_ALLOWED_TEAMS]
        logging.info(f"✅ Found {len(filtered_teams)} allowed teams (out of {len(all_teams)} total)")
        for team in filtered_teams:
            logging.debug(f"      - {team.name}")
        
        # Save to cache
        if self.cache:
            # First, save the teams list (this clears old team_members_* documents)
            self.cache.save_github_teams(filtered_teams)
            
            # Then, fetch and save members for each team immediately
            logging.info(f"📋 Fetching and caching members for all {len(filtered_teams)} teams...")
            for team in filtered_teams:
                logging.debug(f"   Fetching members for team '{team.slug}'...")
                members = list(team.get_members())
                logging.debug(f"      Team '{team.slug}': {len(members)} members")
                self.cache.save_team_members(team.slug, members)
            logging.info(f"✅ Cached members for all {len(filtered_teams)} teams")
        
        return filtered_teams
    
    def get_team_members(self, team_slug: str) -> List[Any]:
        """Get members of a specific team"""
        # Try cache first
        if self.cache:
            cached_members = self.cache.get_team_members(team_slug)
            if cached_members:
                # Convert cached dict back to member-like objects
                class CachedMember:
                    def __init__(self, data):
                        self.login = data['login']
                        self.id = data['id']
                
                return [CachedMember(m) for m in cached_members]
        
        # Fetch from API
        logging.info(f"   Fetching members for team '{team_slug}' from API...")
        team = self.org.get_team_by_slug(team_slug)
        members = list(team.get_members())
        logging.info(f"      Team '{team_slug}': {len(members)} members")
        for member in members:
            logging.debug(f"         - {member.login}")
        
        # Save to cache
        if self.cache:
            self.cache.save_team_members(team_slug, members)
        
        return members


# ======================== Slack API Client ========================

class SlackAPIClient:
    """Handles Slack API interactions"""
    
    def __init__(self, bot_token: str, cache_manager: Optional['CacheManager'] = None):
        logging.debug("🔧 Initializing Slack client...")
        self.bot_client = WebClient(token=bot_token)
        self.cache = cache_manager
        logging.info("✅ Slack client initialized")
    
    def get_members(self) -> List[SlackMember]:
        """Get all Slack members with their profiles, presence, and DND status"""
        # Try cache first
        if self.cache:
            cached_members = self.cache.get_slack_members()
            if cached_members:
                return cached_members
        
        # Fetch from API
        logging.info("📋 Fetching Slack members from API...")
        
        try:
            logging.debug("   Calling Slack users.list API...")
            response = self.bot_client.users_list(limit=1000)
            members = []
            total_users = len(response['members'])
            logging.debug(f"   Retrieved {total_users} total users from Slack")
            
            processed = 0
            skipped_deleted = 0
            skipped_bots = 0
            
            for user in response['members']:
                if user.get('deleted'):
                    skipped_deleted += 1
                    continue
                if user.get('is_bot'):
                    skipped_bots += 1
                    continue
                
                # Limit members for testing
                if len(members) >= MAX_SLACK_MEMBERS_FOR_TESTING:
                    logging.info(f"⚠️  Reached testing limit of {MAX_SLACK_MEMBERS_FOR_TESTING} members, stopping")
                    break
                
                user_name = user.get('name', 'unknown')
                user_id = user['id']
                
                # Log ALL user data
                logging.debug(f"   ========== Processing user: {user_name} (ID: {user_id}) ==========")
                logging.debug(f"   Full user object: {json.dumps(user, indent=2)}")
                
                # Get user profile
                logging.debug(f"   Fetching profile for user: {user_name}")
                profile_response = self.bot_client.users_profile_get(user=user_id)
                profile = profile_response['profile']
                logging.debug(f"   Profile data: {json.dumps(profile, indent=2)}")
                
                # Check PTO status
                status_text = profile.get('status_text', '')
                status_emoji = profile.get('status_emoji', '')
                pto = "vacation" in status_text.lower()
                logging.debug(f"   Status text: '{status_text}'")
                logging.debug(f"   Status emoji: '{status_emoji}'")
                logging.debug(f"   PTO detected: {pto}")
                
                # Get GitHub username from custom field
                github_username = ""
                if 'fields' in profile and 'Xf01KX0SRLF3' in profile['fields']:
                    github_username = profile['fields']['Xf01KX0SRLF3'].get('alt', '').replace(' ', '')
                    logging.debug(f"   GitHub username: {github_username}")
                
                # Get country from custom field
                country = ""
                if 'fields' in profile and 'Xf04Q9EE6NA3' in profile['fields']:
                    country = profile['fields']['Xf04Q9EE6NA3'].get('value', '')
                    logging.debug(f"   Country: {country}")
                
                # Get UTC working hours from custom field
                utc_working_hours = ""
                if 'fields' in profile and 'Xf0ABU8PDTCG' in profile['fields']:
                    utc_working_hours = profile['fields']['Xf0ABU8PDTCG'].get('value', '')
                    logging.debug(f"   UTC working hours: {utc_working_hours}")

                # Get City working hours from custom field
                city = ""
                if 'fields' in profile and 'Xf0AAJFW6PM5' in profile['fields']:
                    city = profile['fields']['Xf0AAJFW6PM5'].get('value', '')
                    logging.debug(f"   City: {city}")

                # Get Title from custom field
                title = ""
                if 'fields' in profile and 'Xf03UK34U0R3' in profile['fields']:
                    title = profile['fields']['Xf03UK34U0R3'].get('value', '')
                    logging.debug(f"   Title: {title}")
                
                # Get email from profile
                email = profile.get('email', '')
                logging.debug(f"   Email: {email}")
                
                # Get presence and DND info from API
                presence_data = self.get_presence_and_dnd(user_id)
                status = presence_data['status']
                available = presence_data['available']
                dnd_enabled = presence_data['dnd_enabled']
                next_dnd_start_ts = presence_data['next_dnd_start_ts']
                next_dnd_end_ts = presence_data['next_dnd_end_ts']
                
                logging.debug(f"   Final status: {status}, available: {available}, dnd_enabled: {dnd_enabled}")
                logging.debug(f"   ========== End user: {user_name} ==========")
                
                members.append(SlackMember(
                    full_name=profile.get('real_name', ''),
                    user_id=user_id,
                    github_username=github_username,
                    country=country,
                    pto=pto,
                    email=email,
                    status=status,
                    available=available,
                    dnd_enabled=dnd_enabled,
                    next_dnd_start_ts=next_dnd_start_ts,
                    next_dnd_end_ts=next_dnd_end_ts,
                    status_text=status_text,
                    status_emoji=status_emoji,
                    utc_working_hours=utc_working_hours,
                    city=city,
                    title=title
                ))
                processed += 1
            
            logging.info(f"✅ Found {len(members)} Slack members (with status)")
            logging.debug(f"   Processed: {processed}, Skipped (deleted): {skipped_deleted}, Skipped (bots): {skipped_bots}")
            
            # Save to cache
            if self.cache:
                self.cache.save_slack_members(members)
            
            return members
            
        except SlackApiError as e:
            logging.error(f"❌ Slack API error: {e}")
            return []
    
    def get_presence_and_dnd(self, user_id: str) -> Dict[str, Any]:
        """Get user presence and DND info from Slack (simplified like slack_presence.py)"""
        result = {
            'status': 'away',
            'available': 'no',
            'dnd_enabled': False,
            'next_dnd_start_ts': None,
            'next_dnd_end_ts': None
        }
        
        try:
            # Get presence (active/away)
            presence_response = self.bot_client.users_getPresence(user=user_id)
            logging.debug(f"      users_getPresence response: {json.dumps(presence_response.data, indent=2)}")
            status = presence_response.get('presence', 'away')
            result['status'] = status
            
            # Get DND info
            dnd_response = self.bot_client.dnd_info(user=user_id)
            dnd_data = dnd_response.data if hasattr(dnd_response, 'data') else dnd_response
            logging.debug(f"      dnd_info response: {json.dumps(dnd_data, indent=2)}")
            
            # Check if user is in DND period
            dnd_enabled = dnd_data.get('dnd_enabled', False)
            next_dnd_start_ts = dnd_data.get('next_dnd_start_ts')
            next_dnd_end_ts = dnd_data.get('next_dnd_end_ts')
            
            result['dnd_enabled'] = dnd_enabled
            result['next_dnd_start_ts'] = next_dnd_start_ts
            result['next_dnd_end_ts'] = next_dnd_end_ts
            
            # Calculate if user is available
            # Available = active AND not currently in DND period
            is_active = (status == 'active')
            in_dnd_period = False
            
            if next_dnd_start_ts and next_dnd_end_ts:
                current_ts = int(datetime.now().timestamp())
                # Check if current time is within DND period
                in_dnd_period = (next_dnd_start_ts <= current_ts <= next_dnd_end_ts)
                logging.debug(f"      DND check: current_ts={current_ts}, start={next_dnd_start_ts}, end={next_dnd_end_ts}, in_period={in_dnd_period}")
            
            result['available'] = 'yes' if (is_active and not in_dnd_period) else 'no'
            logging.debug(f"      Final: status={status}, available={result['available']}, dnd_enabled={dnd_enabled}, in_dnd_period={in_dnd_period}")
            
            return result
            
        except SlackApiError as e:
            logging.debug(f"      Failed to get presence/DND for {user_id}: {e}")
            return result
    



# ======================== GraphQL GitHub Client ========================

class GitHubGraphQLClient:
    """Handles GitHub GraphQL API for project management"""
    
    def __init__(self, token: str, cache_manager: Optional['CacheManager'] = None):
        logging.debug("🔧 Initializing GitHub GraphQL client...")
        self.token = token
        self.cache = cache_manager
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        self.endpoint = "https://api.github.com/graphql"
        logging.debug(f"   GraphQL endpoint: {self.endpoint}")
    
    def execute_query(self, query: str) -> Dict:
        """Execute a GraphQL query"""
        import requests
        
        logging.debug("   Executing GraphQL query...")
        response = requests.post(
            self.endpoint,
            headers=self.headers,
            json={'query': query}
        )
        
        if response.status_code == 200:
            logging.debug(f"      GraphQL query successful (status: {response.status_code})")
            return response.json()
        else:
            logging.error(f"❌ GraphQL query failed: {response.status_code}")
            logging.error(f"   Response: {response.text}")
            return {}
    
    def get_project_issues(self, project_id: str) -> List[GitHubIssue]:
        """Get all issues from a GitHub project using GraphQL"""
        # Try cache first
        if self.cache:
            cached_issues = self.cache.get_project_issues()
            if cached_issues:
                return cached_issues
        
        # Fetch from API
        logging.info("📋 Fetching project issues via GraphQL from API...")
        
        # Base query template
        query_template = """
        query {
            node(id: "PROJECT_ID") {
                ... on ProjectV2 {
                    items(first: 100AFTER_CURSOR) {
                        pageInfo {
                            hasNextPage
                            endCursor
                        }
                        nodes {
                            id
                            content {
                                ... on Issue {
                                    id
                                    createdAt
                                    number
                                    assignees(first: 20) { 
                                        nodes { login } 
                                    }
                                }
                            }
                            fieldValues(first: 20) {
                                nodes {
                                    ... on ProjectV2ItemFieldTextValue {
                                        field { ... on ProjectV2Field { name } }
                                        text
                                    }
                                    ... on ProjectV2ItemFieldNumberValue {
                                        field { ... on ProjectV2Field { name } }
                                        number
                                    }
                                    ... on ProjectV2ItemFieldSingleSelectValue {
                                        field { ... on ProjectV2SingleSelectField { name } }
                                        name
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        """
        
        all_issues = []
        cursor = None
        has_next_page = True
        page_count = 0
        
        logging.debug(f"   Fetching issues for project ID: {project_id}")
        
        while has_next_page:
            # Build query with cursor
            after_clause = f', after: "{cursor}"' if cursor else ''
            current_query = query_template.replace("PROJECT_ID", project_id).replace("AFTER_CURSOR", after_clause)
            
            logging.debug(f"   Fetching page {page_count + 1}..." + (f" (cursor: {cursor[:20]}...)" if cursor else ""))
            result = self.execute_query(current_query)
            page_count += 1
            
            if 'data' in result and 'node' in result['data']:
                items = result['data']['node']['items']
                items_in_page = len(items['nodes'])
                logging.debug(f"      Page {page_count}: retrieved {items_in_page} items")
                
                # Process nodes
                issues_parsed = 0
                for node in items['nodes']:
                    if node.get('content'):
                        issue = self._parse_issue_node(node)
                        if issue:
                            all_issues.append(issue)
                            issues_parsed += 1
                
                logging.debug(f"      Parsed {issues_parsed} issues from this page")
                
                # Check pagination
                has_next_page = items['pageInfo']['hasNextPage']
                cursor = items['pageInfo']['endCursor']
                
                if has_next_page:
                    logging.debug(f"      More pages available, continuing...")
                else:
                    logging.debug(f"      Last page reached")
            else:
                logging.warning(f"⚠️  No data in GraphQL response for page {page_count}")
                break
        
        logging.info(f"✅ Found {len(all_issues)} project issues across {page_count} pages")
        
        # Save to cache
        if self.cache:
            self.cache.save_project_issues(all_issues)
        
        return all_issues
    
    def _parse_issue_node(self, node: Dict) -> Optional[GitHubIssue]:
        """Parse a project issue node into GitHubIssue object"""
        content = node.get('content', {})
        if not content:
            logging.debug("         Skipping node with no content")
            return None
        
        # Extract basic info
        number = content.get('number')
        created_at = datetime.fromisoformat(content.get('createdAt').replace('Z', '+00:00'))
        assignees = [a['login'] for a in content.get('assignees', {}).get('nodes', [])]
        logging.debug(f"         Issue #{number}: {len(assignees)} assignee(s)")
        
        # Extract field values
        title = None
        status = None
        team = None
        time = None
        year = None
        week = None
        
        for field in node.get('fieldValues', {}).get('nodes', []):
            if 'field' not in field:
                continue
            
            field_name = field['field'].get('name', '')
            
            if field_name == "Title" and 'text' in field:
                title = field['text']
            elif field_name == "Status" and 'name' in field:
                status = field['name']
            elif field_name == "Team" and 'name' in field:
                team = field['name']
            elif "Time" in field_name and 'number' in field:
                time = field['number']
            elif field_name == "Year" and 'name' in field:
                year = field['name']
            elif "Week" in field_name and 'text' in field:
                week = field['text']
        
        return GitHubIssue(
            number=number,
            title=title or "",
            assignees=assignees,
            created_at=created_at,
            status=status,
            team=team,
            time=time,
            year=year,
            week=week,
            node_id=content.get('id')
        )


# ======================== Google Sheets Client ========================

class GoogleSheetsClient:
    """Handles Google Sheets operations"""
    
    def __init__(self, credentials_file: str):
        logging.debug(f"🔧 Initializing Google Sheets client...")
        logging.debug(f"   Credentials file: {credentials_file}")
        
        if not os.path.exists(credentials_file):
            logging.warning(f"⚠️  Google credentials file not found: {credentials_file}")
            self.enabled = False
            return
        
        try:
            logging.debug("   Authorizing gspread client...")
            gc = gspread.oauth(
                credentials_filename=GOOGLE_CREDENTIALS_FILE,
                authorized_user_filename='authorized_user.json'  # gspread will create this
            )
            self.client = gc
            self.enabled = True
            logging.info("✅ Google Sheets client initialized")
        except Exception as e:
            logging.error(f"❌ Failed to initialize Google Sheets client: {e}")
            self.enabled = False
    
    def get_or_create_spreadsheet(self, name: str) -> Optional[Any]:
        """Get or create a spreadsheet"""
        if not self.enabled:
            logging.warning("⚠️  Google Sheets not enabled, cannot get/create spreadsheet")
            return None
        
        logging.debug(f"📊 Looking for spreadsheet: '{name}'")
        try:
            spreadsheet = self.client.open(name)
            logging.info(f"✅ Opened existing spreadsheet: {name}")
            return spreadsheet
        except gspread.SpreadsheetNotFound:
            logging.info(f"📝 Spreadsheet not found, creating new one: {name}")
            spreadsheet = self.client.create(name)
            logging.info(f"✅ Created new spreadsheet: {name}")
            return spreadsheet
    
    def update_summary_sheet(self, community_data: List[TeamMember], total_assigned: int, 
                            from_previous_weeks: int, current_week: str):
        """Update the summary sheet with community data"""
        if not self.enabled:
            logging.warning("⚠️  Google Sheets not enabled, skipping update")
            return
        
        logging.info(f"📊 Updating Google Sheet with summary data...")
        logging.debug(f"   Spreadsheet: '{SPREADSHEET_NAME}'")
        logging.debug(f"   Worksheet: '{SHEET_NAME}'")
        
        spreadsheet = self.get_or_create_spreadsheet(SPREADSHEET_NAME)
        if not spreadsheet:
            logging.error("❌ Failed to get/create spreadsheet")
            return
        
        # Get or create the Summary sheet
        try:
            logging.debug(f"   Looking for worksheet '{SHEET_NAME}'...")
            sheet = spreadsheet.worksheet(SHEET_NAME)
            logging.debug(f"   Clearing existing content...")
            sheet.clear()
        except gspread.WorksheetNotFound:
            logging.info(f"📝 Worksheet '{SHEET_NAME}' not found, creating new one...")
            sheet = spreadsheet.add_worksheet(title=SHEET_NAME, rows=1000, cols=10)
        
        # Prepare data
        week_header = [f"Week {current_week}", "", "Total assigned", total_assigned, "", "From previous weeks", from_previous_weeks]
        column_headers = ["Team", "Full name", "GitHub username", "Ticket count", "Country", "Status", "PTO", "Slack user ID", "Email"]
        
        logging.debug(f"   Writing headers to sheet...")
        logging.debug(f"      Week {current_week}, Total: {total_assigned}, Previous weeks: {from_previous_weeks}")
        
        # Prepare all data at once (headers + community data)
        all_rows = [week_header, column_headers]
        
        logging.debug(f"   Preparing {len(community_data)} team member rows for bulk insert...")
        for i, member in enumerate(community_data, 1):
            logging.debug(f"      Row {i}: {member.full_name} ({member.github_username}) - {member.ticket_count} tickets")
            all_rows.append(member.to_list())
        
        # Write all data in ONE API call
        logging.debug(f"   Writing {len(all_rows)} rows to sheet in bulk...")
        sheet.update(f'A1:I{len(all_rows)}', all_rows)
        logging.info(f"✅ Wrote {len(all_rows)} rows in single API call")
        
        # Prepare batch formatting requests
        logging.debug(f"   Preparing batch format requests...")
        format_requests = []
        
        # Format header row 1
        format_requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet.id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": 7
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {"bold": True, "fontSize": 16},
                        "borders": {
                            "top": {"style": "SOLID"},
                            "bottom": {"style": "SOLID"},
                            "left": {"style": "SOLID"},
                            "right": {"style": "SOLID"}
                        }
                    }
                },
                "fields": "userEnteredFormat(textFormat,borders)"
            }
        })
        
        # Format header row 2
        format_requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet.id,
                    "startRowIndex": 1,
                    "endRowIndex": 2,
                    "startColumnIndex": 0,
                    "endColumnIndex": 9
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {"bold": True, "fontSize": 12},
                        "borders": {
                            "top": {"style": "SOLID"},
                            "bottom": {"style": "SOLID"},
                            "left": {"style": "SOLID"},
                            "right": {"style": "SOLID"}
                        }
                    }
                },
                "fields": "userEnteredFormat(textFormat,borders)"
            }
        })
        
        # Apply color coding to data rows
        logging.debug(f"   Preparing color coding for {len(community_data)} rows...")
        for i, member in enumerate(community_data, start=2):  # Start at row 2 (0-indexed, after 2 header rows)
            # Determine color based on criteria (active means available)
            if member.pto == "No" and member.status == "active":
                if member.ticket_count < 2:
                    color = {"red": 0, "green": 0.824, "blue": 0}  # Green
                    color_name = "green"
                elif member.ticket_count >= 2:
                    color = {"red": 0.824, "green": 0.824, "blue": 0}  # Yellow
                    color_name = "yellow"
                else:
                    color = {"red": 0.824, "green": 0, "blue": 0}  # Red
                    color_name = "red"
            else:
                color = {"red": 0.824, "green": 0, "blue": 0}  # Red
                color_name = "red"
            
            logging.debug(f"      Row {i+1}: {member.github_username} → {color_name}")
            
            format_requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet.id,
                        "startRowIndex": i,
                        "endRowIndex": i + 1,
                        "startColumnIndex": 0,
                        "endColumnIndex": 9
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": color,
                            "borders": {
                                "top": {"style": "SOLID"},
                                "bottom": {"style": "SOLID"},
                                "left": {"style": "SOLID"},
                                "right": {"style": "SOLID"}
                            }
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,borders)"
                }
            })
        
        # Execute all formatting in ONE batch API call
        logging.debug(f"   Executing batch format with {len(format_requests)} requests...")
        spreadsheet.batch_update({"requests": format_requests})
        logging.info(f"✅ Applied formatting in single batch API call")
        
        logging.info(f"✅ Updated Google Sheet with {len(community_data)} team members")


# ======================== Summary Generator ========================

class SummaryGenerator:
    """Generates team summary for Google Sheets and OpenSearch"""
    
    def __init__(self, github_client: GitHubAPIClient, slack_client: SlackAPIClient,
                 graphql_client: GitHubGraphQLClient, sheets_client: GoogleSheetsClient,
                 quota_manager: OpenSearchQuotaManager):
        logging.debug("🔧 Initializing SummaryGenerator...")
        self.github = github_client
        self.slack = slack_client
        self.graphql = graphql_client
        self.sheets = sheets_client
        self.quota = quota_manager
        self.current_week = DateUtils.get_current_week()
        self.current_year = DateUtils.get_current_year()
        logging.debug(f"   Target week: {self.current_week}, Year: {self.current_year}")
    
    def generate(self):
        """Generate and update summary"""
        logging.info("=" * 60)
        logging.info("🚀 Starting summary generation...")
        logging.info("=" * 60)
        
        # Get data
        github_teams = self.github.get_teams()
        slack_members = self.slack.get_members()
        
        # Note: We no longer use project_issues from GraphQL
        # Instead, we query tickets-raw-v1.0 directly for each user
        
        # Count status distribution from cached data
        logging.info(f"📊 Status distribution for {len(slack_members)} Slack members:")
        status_counts = {}
        for member in slack_members:
            status_counts[member.status] = status_counts.get(member.status, 0) + 1
        for status, count in status_counts.items():
            logging.info(f"   {status}: {count} members")
        
        # Generate community data
        community_data = []
        total_assigned = 0
        
        logging.info(f"📊 Calculating ticket counts for {len(github_teams)} teams...")
        
        # OPTIMIZATION: Fetch ALL ticket counts in ONE bulk query instead of one per user
        logging.info("🚀 Fetching ticket counts for all users in bulk...")
        all_ticket_counts = self.quota.get_all_ticket_counts_bulk(
            self.current_year,
            self.current_week
        )
        logging.info(f"✅ Retrieved ticket counts for {len(all_ticket_counts)} users")
        
        for team_idx, team in enumerate(github_teams, 1):
            logging.info(f"   Processing team {team_idx}/{len(github_teams)}: {team.name}")
            team_members = self.github.get_team_members(team.slug)
            
            for github_member in team_members:
                if github_member.login in GITHUB_EXCLUSION_LIST:
                    logging.debug(f"      Skipping excluded member: {github_member.login}")
                    continue
                
                # Get ticket count from bulk results (default to 0 if user not found)
                ticket_count = all_ticket_counts.get(github_member.login, 0)
                
                total_assigned += ticket_count
                logging.debug(f"      {github_member.login}: {ticket_count} tickets assigned")
                
                # Find corresponding Slack member
                slack_member = next((m for m in slack_members if m.github_username == github_member.login), None)
                
                if slack_member:
                    # Determine priority (active status means available)
                    priority = "c"
                    if not slack_member.pto and slack_member.status == "active":
                        priority = "a" if ticket_count < 2 else "b"
                    
                    logging.debug(f"      {github_member.login}: {ticket_count} tickets, priority={priority}")
                    
                    community_data.append(TeamMember(
                        team=team.name,
                        full_name=slack_member.full_name,
                        github_username=github_member.login,
                        ticket_count=ticket_count,
                        country=slack_member.country,
                        status=slack_member.status,
                        pto="Yes" if slack_member.pto else "No",
                        slack_user_id=slack_member.user_id,
                        email=slack_member.email,
                        priority=priority
                    ))
                else:
                    logging.debug(f"      {github_member.login}: No matching Slack member found")
        
        # Sort by priority
        logging.debug(f"📋 Sorting {len(community_data)} team members by priority...")
        community_data.sort(key=lambda x: x.priority)
        priority_a = sum(1 for m in community_data if m.priority == "a")
        priority_b = sum(1 for m in community_data if m.priority == "b")
        priority_c = sum(1 for m in community_data if m.priority == "c")
        
        logging.info(f"📈 Summary stats:")
        logging.info(f"   Total assigned this week: {total_assigned}")
        logging.info(f"   Team members tracked: {len(community_data)}")
        logging.info(f"   Priority distribution: A={priority_a}, B={priority_b}, C={priority_c}")
        
        # Update Google Sheets
        self.sheets.update_summary_sheet(community_data, total_assigned, 0, self.current_week)
        
        # NEW: Upsert quota data to OpenSearch (community-quota-v1)
        logging.info("📊 Upserting quota data to OpenSearch...")
        quota_result = self.quota.bulk_upsert_quotas(
            community_data,
            self.current_year,
            self.current_week
        )
        logging.info(f"   OpenSearch upsert: {quota_result['success']} success, {quota_result['failed']} failed")
        
        logging.info("=" * 60)
        logging.info("✅ Summary generation completed!")
        logging.info("=" * 60)


# ======================== Main Orchestrator ========================

class CommunityAuditor:
    """Main orchestrator for the community auditor system"""
    
    def __init__(self):
        logging.info("=" * 60)
        logging.info("🔧 Initializing Community Auditor...")
        logging.info("=" * 60)
        
        # Initialize cache manager (OpenSearch-based)
        self.cache = CacheManager()
        
        # Initialize quota manager (OpenSearch-based)
        logging.info("📊 Initializing quota manager...")
        self.quota = OpenSearchQuotaManager()
        
        # Load tokens from centralized token manager
        logging.info("🔑 Loading authentication tokens...")
        github_token = get_github_token()
        slack_token = get_slack_user_workspace_wazuh_team()
        
        if not github_token:
            raise ValueError("GitHub token not found in centralized token manager")
        if not slack_token:
            raise ValueError("Slack token not found in centralized token manager")
        
        # Initialize clients with cache
        logging.info("🌐 Initializing API clients...")
        self.github = GitHubAPIClient(github_token, self.cache)
        self.slack = SlackAPIClient(slack_token, self.cache)
        self.graphql = GitHubGraphQLClient(github_token, self.cache)
        self.sheets = GoogleSheetsClient(GOOGLE_CREDENTIALS_FILE)
        
        # Initialize summary generator
        logging.info("📊 Initializing summary generator...")
        self.summary = SummaryGenerator(self.github, self.slack, self.graphql, self.sheets, self.quota)
        
        logging.info("=" * 60)
        logging.info("✅ Community Auditor initialized successfully")
        logging.info("=" * 60)
    
    def run(self):
        """Run summary generation"""
        self.summary.generate()


# ======================== Main Entry Point ========================

def clear_cache_cli():
    """CLI utility to clear cache"""
    import sys
    
    print("🗑️  Cache Management Utility")
    print("=" * 60)
    
    cache = CacheManager()
    
    if len(sys.argv) > 2 and sys.argv[1] == '--clear-cache':
        cache_type = sys.argv[2]
        if cache_type in ['github_teams', 'slack_members', 'project_issues', 'all']:
            cache.clear_cache(cache_type if cache_type != 'all' else None)
            print(f"✅ Cleared {cache_type} cache")
        else:
            print("❌ Invalid cache type. Use: github_teams, slack_members, project_issues, or all")
    else:
        print("Usage:")
        print("  python auditor.py --clear-cache [github_teams|slack_members|project_issues|all]")
        print()
        print("Cache Configuration:")
        print(f"  CACHE_ENABLED: {CACHE_ENABLED}")
        print(f"  CACHE_GITHUB_TEAMS: {CACHE_GITHUB_TEAMS}")
        print(f"  CACHE_SLACK_MEMBERS: {CACHE_SLACK_MEMBERS}")
        print(f"  CACHE_PROJECT_ISSUES: {CACHE_PROJECT_ISSUES}")
        print()
        print(f"Cache Database: {CACHE_DB_FILE}")


def main():
    """Main function"""
    import sys
    
    # Check for cache management commands
    if len(sys.argv) > 1 and sys.argv[1] == '--clear-cache':
        clear_cache_cli()
        return
    
    print("📊 Community Auditor - Team Summary Generator")
    print("=" * 60)
    
    # Show cache status
    if CACHE_ENABLED:
        print(f"💾 Cache: ENABLED")
        print(f"   - GitHub Teams: {'ON' if CACHE_GITHUB_TEAMS else 'OFF'}")
        print(f"   - Slack Members: {'ON' if CACHE_SLACK_MEMBERS else 'OFF'}")
        print(f"   - Project Issues: {'ON' if CACHE_PROJECT_ISSUES else 'OFF'}")
    else:
        print(f"💾 Cache: DISABLED")
    print("=" * 60)
    
    start_time = datetime.now()
    logging.info(f"⏰ Starting at: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    try:
        auditor = CommunityAuditor()
        auditor.run()
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        logging.info("=" * 60)
        logging.info(f"✅ Completed successfully!")
        logging.info(f"⏰ Duration: {duration:.2f} seconds")
        logging.info("=" * 60)
        
        print("=" * 60)
        print(f"✅ Done! (took {duration:.2f}s)")
        print(f"📋 Check log file: {LOG_FILE}")
        
    except Exception as e:
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        logging.error("=" * 60)
        logging.error(f"❌ Failed with error: {e}")
        logging.error(f"⏰ Failed after: {duration:.2f} seconds")
        logging.error("=" * 60)
        logging.exception("Full traceback:")
        
        print("=" * 60)
        print(f"❌ Error: {e}")
        print(f"📋 Check log file for details: {LOG_FILE}")
        raise


if __name__ == "__main__":
    print("🔄 Starting Community Auditor in continuous mode")
    print("⏰ Will execute every 5 minutes (300 seconds)")
    print("🛑 Press Ctrl+C to stop")
    print("=" * 60)
    
    iteration = 0
    
    try:
        while True:
            iteration += 1
            print(f"\n{'='*60}")
            print(f"🔄 Iteration #{iteration} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'='*60}\n")
            
            try:
                main()
            except Exception as e:
                logging.error(f"❌ Error in iteration #{iteration}: {e}")
                print(f"❌ Error occurred, but continuing... Check logs for details")
            
            print(f"\n⏸️  Waiting 5 minutes before next execution...")
            print(f"⏰ Next execution at: {datetime.fromtimestamp(time.time() + 300).strftime('%Y-%m-%d %H:%M:%S')}")
            time.sleep(300)  # Sleep for 5 minutes (300 seconds)
            
    except KeyboardInterrupt:
        print("\n\n🛑 Received interrupt signal")
        print("✅ Community Auditor stopped gracefully")
        sys.exit(0)
