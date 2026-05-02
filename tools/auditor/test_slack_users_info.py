#!/usr/bin/env python3
"""
Test script to inspect Slack users_list API response
Shows all available fields including email address
"""

import os
import sys
import json

# Add parent directory to path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

from slack_sdk import WebClient
from token_manager import get_slack_user_workspace_wazuh_team

def main():
    print("=" * 80)
    print("🔍 Testing Slack users_list API Response")
    print("=" * 80)
    
    # Get Slack token
    slack_token = get_slack_user_workspace_wazuh_team()
    if not slack_token:
        print("❌ Failed to load Slack token")
        return
    
    print("✅ Slack token loaded")
    
    # Initialize Slack client
    client = WebClient(token=slack_token)
    
    # Fetch users
    print("\n📋 Fetching users from Slack API...")
    response = client.users_list(limit=1000)
    
    print(f"✅ API call successful")
    print(f"📊 Total users returned: {len(response['members'])}")
    
    # Show first few non-bot, non-deleted users
    print("\n" + "=" * 80)
    print("👥 Sample User Data (first 3 real users)")
    print("=" * 80)
    
    count = 0
    for user in response['members']:
        # Skip deleted and bot users
        if user.get('deleted') or user.get('is_bot'):
            continue
        
        count += 1
        if count > 3:
            break
        
        print(f"\n{'='*80}")
        print(f"USER #{count}: {user.get('name', 'unknown')}")
        print(f"{'='*80}")
        
        # Print entire user object
        print(json.dumps(user, indent=2))
        
        # Highlight important fields
        print(f"\n{'─'*80}")
        print(f"HIGHLIGHTED FIELDS:")
        print(f"{'─'*80}")
        print(f"  ID: {user.get('id')}")
        print(f"  Name: {user.get('name')}")
        print(f"  Real Name: {user.get('real_name')}")
        print(f"  Deleted: {user.get('deleted')}")
        print(f"  Is Bot: {user.get('is_bot')}")
        
        # Check profile for email
        profile = user.get('profile', {})
        print(f"\n  PROFILE FIELDS:")
        print(f"    Email: {profile.get('email', 'NOT FOUND')}")
        print(f"    Real Name: {profile.get('real_name')}")
        print(f"    Display Name: {profile.get('display_name')}")
        print(f"    Status Text: {profile.get('status_text')}")
        print(f"    Title: {profile.get('title', 'N/A')}")
        
        # Check if email is in custom fields
        if 'fields' in profile:
            print(f"\n  CUSTOM FIELDS:")
            for field_id, field_data in profile['fields'].items():
                print(f"    {field_id}: {field_data}")
    
    # Summary
    print("\n" + "=" * 80)
    print("📊 SUMMARY")
    print("=" * 80)
    
    users_with_email = 0
    users_without_email = 0
    
    for user in response['members']:
        if user.get('deleted') or user.get('is_bot'):
            continue
        
        profile = user.get('profile', {})
        if profile.get('email'):
            users_with_email += 1
        else:
            users_without_email += 1
    
    print(f"Total real users: {users_with_email + users_without_email}")
    print(f"  With email: {users_with_email}")
    print(f"  Without email: {users_without_email}")
    
    print("\n✅ Test completed")
    print("=" * 80)

if __name__ == "__main__":
    main()
