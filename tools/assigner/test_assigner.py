#!/usr/bin/env python3
"""
Test script for Issue Assigner
Tests all main functions and prints results
"""

import os
import sys

# Add parent directory to path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

from assigner import IssueAssigner, MAX_TICKETS_PER_USER


def print_header(title: str):
    """Print a formatted section header"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70 + "\n")


def test_initialization():
    """Test: Initialize the Issue Assigner"""
    print_header("TEST 1: Initialization")
    
    try:
        assigner = IssueAssigner()
        print("✅ Issue Assigner initialized successfully")
        print(f"   Repository: {assigner.repo.full_name}")
        print(f"   Quota Manager enabled: {assigner.quota_manager.enabled}")
        print(f"   Indexer enabled: {assigner.indexer.enabled}")
        return assigner
    except Exception as e:
        print(f"❌ Failed to initialize: {e}")
        return None


def test_get_available_users(assigner: IssueAssigner):
    """Test: Get list of users with available quota"""
    print_header("TEST 2: Get Available Users")
    
    try:
        available_users = assigner.get_available_users()
        
        if available_users:
            print(f"✅ Found {len(available_users)} users with available quota")
            print(f"\n📊 Top 15 users sorted by ticket count:\n")
            
            for i, user in enumerate(available_users[:15], 1):
                username = user['github_username']
                count = user['ticket_count']
                slots = user['available_slots']
                
                # Add emoji based on availability
                if count == 0:
                    emoji = "🟢"
                elif count < MAX_TICKETS_PER_USER:
                    emoji = "🟡"
                else:
                    emoji = "🔴"
                
                print(f"   {i:2d}. {emoji} {username:25s} → {count}/{MAX_TICKETS_PER_USER} tickets ({slots} slots available)")
        else:
            print("⚠️  No users with available quota found")
        
        return available_users
    
    except Exception as e:
        print(f"❌ Error getting available users: {e}")
        import traceback
        traceback.print_exc()
        return []


def test_get_user_quota(assigner: IssueAssigner, username: str = None):
    """Test: Get quota for a specific user"""
    print_header("TEST 3: Get User Quota")
    
    # If no username provided, pick the first available user
    if username is None:
        available = assigner.get_available_users()
        if available:
            username = available[0]['github_username']
        else:
            print("⚠️  No users available to test")
            return
    
    try:
        quota = assigner.get_user_quota(username)
        
        if quota:
            print(f"✅ Retrieved quota for user: {username}\n")
            print(f"   GitHub Username: {quota['github_username']}")
            print(f"   Current Tickets: {quota['ticket_count']}")
            print(f"   Available Slots: {quota['available_slots']}")
            print(f"   Max Tickets:     {quota['max_tickets']}")
            
            # Visual representation
            filled = "█" * quota['ticket_count']
            empty = "░" * quota['available_slots']
            print(f"\n   Progress: [{filled}{empty}] {quota['ticket_count']}/{quota['max_tickets']}")
        else:
            print(f"⚠️  No quota information found for {username}")
    
    except Exception as e:
        print(f"❌ Error getting quota: {e}")
        import traceback
        traceback.print_exc()


def test_quota_statistics(assigner: IssueAssigner):
    """Test: Display quota statistics"""
    print_header("TEST 4: Quota Statistics")
    
    try:
        available_users = assigner.get_available_users()
        
        if not available_users:
            print("⚠️  No users to analyze")
            return
        
        # Calculate statistics
        total_users = len(available_users)
        users_with_0 = sum(1 for u in available_users if u['ticket_count'] == 0)
        users_with_1 = sum(1 for u in available_users if u['ticket_count'] == 1)
        users_with_2_or_more = sum(1 for u in available_users if u['ticket_count'] >= 2)
        
        total_tickets = sum(u['ticket_count'] for u in available_users)
        total_slots = sum(u['available_slots'] for u in available_users)
        
        avg_tickets = total_tickets / total_users if total_users > 0 else 0
        
        print(f"✅ Quota Statistics:\n")
        print(f"   Total Users:           {total_users}")
        print(f"   Users with 0 tickets:  {users_with_0} 🟢")
        print(f"   Users with 1 ticket:   {users_with_1} 🟡")
        print(f"   Users with 2+ tickets: {users_with_2_or_more} 🔴")
        print(f"\n   Total Tickets:         {total_tickets}")
        print(f"   Total Available Slots: {total_slots}")
        print(f"   Average Tickets/User:  {avg_tickets:.2f}")
        
        # Distribution chart
        print(f"\n📊 Distribution Chart:")
        if users_with_0 > 0:
            bar = "█" * int(users_with_0 / total_users * 50)
            print(f"   0 tickets: {bar} {users_with_0}")
        if users_with_1 > 0:
            bar = "█" * int(users_with_1 / total_users * 50)
            print(f"   1 ticket:  {bar} {users_with_1}")
        if users_with_2_or_more > 0:
            bar = "█" * int(users_with_2_or_more / total_users * 50)
            print(f"   2+ tickets: {bar} {users_with_2_or_more}")
    
    except Exception as e:
        print(f"❌ Error calculating statistics: {e}")
        import traceback
        traceback.print_exc()


def test_github_issues(assigner: IssueAssigner):
    """Test: List recent unassigned issues"""
    print_header("TEST 5: GitHub Issues (Read-Only)")
    
    try:
        print("🔍 Fetching recent unassigned issues...\n")
        
        # Get open issues without assignee
        issues = assigner.repo.get_issues(state='open', assignee='none')
        
        count = 0
        for issue in issues:
            if count >= 10:  # Show only first 10
                break
            
            labels = [label.name for label in issue.labels]
            label_str = ", ".join(labels[:3])  # Show first 3 labels
            if len(labels) > 3:
                label_str += f" +{len(labels)-3} more"
            
            print(f"   #{issue.number:5d} - {issue.title[:60]}")
            print(f"          Labels: {label_str}")
            print(f"          Created: {issue.created_at.strftime('%Y-%m-%d %H:%M')}")
            print()
            
            count += 1
        
        if count == 0:
            print("   ✨ No unassigned issues found (all assigned!)")
        else:
            print(f"✅ Found {count} unassigned issues")
    
    except Exception as e:
        print(f"❌ Error fetching issues: {e}")
        import traceback
        traceback.print_exc()


def test_dry_run_assignment(assigner: IssueAssigner):
    """Test: Simulate assignment without actually assigning"""
    print_header("TEST 6: Assignment Simulation (Dry Run)")
    
    try:
        # Get available users
        available_users = assigner.get_available_users()
        
        if not available_users:
            print("⚠️  No users available for assignment")
            return
        
        # Get an unassigned issue
        issues = list(assigner.repo.get_issues(state='open', assignee='none'))
        
        if not issues:
            print("⚠️  No unassigned issues found")
            return
        
        issue = issues[0]
        best_user = available_users[0]
        
        print(f"✅ Simulation Results:\n")
        print(f"   Issue to assign:")
        print(f"      #{issue.number} - {issue.title[:60]}")
        print(f"\n   Would assign to:")
        print(f"      User: {best_user['github_username']}")
        print(f"      Current tickets: {best_user['ticket_count']}/{MAX_TICKETS_PER_USER}")
        print(f"      After assignment: {best_user['ticket_count']+1}/{MAX_TICKETS_PER_USER}")
        print(f"\n   💡 To actually assign, uncomment the assignment code in the main script")
    
    except Exception as e:
        print(f"❌ Error in simulation: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Run all tests"""
    print("\n" + "🧪" * 35)
    print("  ISSUE ASSIGNER - TEST SUITE")
    print("🧪" * 35)
    
    # Test 1: Initialize
    assigner = test_initialization()
    if not assigner:
        print("\n❌ Cannot continue without successful initialization")
        return
    
    # Test 2: Get available users
    available_users = test_get_available_users(assigner)
    
    # Test 3: Get user quota (use first available user)
    if available_users:
        test_get_user_quota(assigner, available_users[0]['github_username'])
    
    # Test 4: Statistics
    #test_quota_statistics(assigner)
    
    # Test 5: List unassigned issues
    #test_github_issues(assigner)
    
    # Test 6: Dry run assignment
    #test_dry_run_assignment(assigner)
    
    # Summary
    #print_header("TEST SUMMARY")
    #print("✅ All read-only tests completed successfully!")
    #print("\n💡 To test actual assignment, modify the script to call:")
    #print("   assigner.assign_issue(issue_number)  # Auto-assign")
    #print("   assigner.assign_issue(issue_number, 'username')  # Assign to specific user")
    #print("\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    main()
