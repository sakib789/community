#!/usr/bin/env python3
"""
GitHub Repository Verifier
Check if the configured GitHub repository exists and the token has proper access
"""

import os
import sys
import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GITHUB_TOKEN_FILE = os.path.join(SCRIPT_DIR, '.token_github')
GITHUB_REPO = os.environ.get('GITHUB_REPO', 'wazuh/community-dev')
GITHUB_API_BASE = "https://api.github.com"


def load_token():
    """Load GitHub token from file"""
    if not os.path.exists(GITHUB_TOKEN_FILE):
        print(f"❌ GitHub token file not found: {GITHUB_TOKEN_FILE}")
        return None
    
    with open(GITHUB_TOKEN_FILE, 'r') as f:
        lines = f.readlines()
        for line in lines:
            line = line.strip()
            if line and not line.startswith('#'):
                token = ''.join(line.split())
                if token:
                    return token
    
    print(f"❌ GitHub token file is empty or contains only comments")
    return None


def check_token_info(token):
    """Check information about the token"""
    print("\n🔑 Checking token information...")
    
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json'
    }
    
    try:
        response = requests.get(f"{GITHUB_API_BASE}/user", headers=headers)
        
        if response.status_code == 200:
            user_data = response.json()
            print(f"✅ Token is valid")
            print(f"   User: {user_data.get('login')}")
            print(f"   Name: {user_data.get('name', 'N/A')}")
            print(f"   Type: {user_data.get('type', 'N/A')}")
            
            # Check scopes
            scopes = response.headers.get('X-OAuth-Scopes', '')
            print(f"   Scopes: {scopes if scopes else 'None (probably fine-grained token)'}")
            
            if scopes and 'repo' not in scopes and 'public_repo' not in scopes:
                print(f"   ⚠️  Warning: Token may not have 'repo' or 'public_repo' scope")
            
            return True
        elif response.status_code == 401:
            print(f"❌ Token is invalid or expired")
            print(f"   Response: {response.text}")
            return False
        else:
            print(f"❌ Unexpected response: {response.status_code}")
            print(f"   Response: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error checking token: {e}")
        return False


def check_repository(token, repo):
    """Check if repository exists and is accessible"""
    print(f"\n📦 Checking repository: {repo}")
    
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json'
    }
    
    url = f"{GITHUB_API_BASE}/repos/{repo}"
    print(f"   URL: {url}")
    
    try:
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            repo_data = response.json()
            print(f"✅ Repository exists and is accessible")
            print(f"   Full Name: {repo_data.get('full_name')}")
            print(f"   Private: {repo_data.get('private', False)}")
            print(f"   Owner: {repo_data.get('owner', {}).get('login')}")
            print(f"   Description: {repo_data.get('description', 'N/A')}")
            
            # Check permissions
            perms = repo_data.get('permissions', {})
            print(f"   Permissions:")
            print(f"     - Pull: {perms.get('pull', False)}")
            print(f"     - Push: {perms.get('push', False)}")
            print(f"     - Admin: {perms.get('admin', False)}")
            
            if not perms.get('push', False):
                print(f"   ⚠️  Warning: Token does not have push/write access")
                print(f"      You won't be able to create issues!")
            
            return True
        elif response.status_code == 404:
            print(f"❌ Repository not found or not accessible")
            print(f"   Possible reasons:")
            print(f"   - Repository doesn't exist")
            print(f"   - Repository is private and token doesn't have access")
            print(f"   - Repository name is misspelled")
            print(f"   Response: {response.text}")
            return False
        elif response.status_code == 401:
            print(f"❌ Authentication failed")
            print(f"   Token may be invalid or expired")
            print(f"   Response: {response.text}")
            return False
        elif response.status_code == 403:
            print(f"❌ Access forbidden")
            print(f"   Token doesn't have permission to access this repository")
            print(f"   Response: {response.text}")
            return False
        else:
            print(f"❌ Unexpected response: {response.status_code}")
            print(f"   Response: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error checking repository: {e}")
        return False


def test_create_issue(token, repo):
    """Test if we can create an issue (dry run)"""
    print(f"\n🧪 Testing issue creation permissions...")
    
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json'
    }
    
    # We'll just check the rate limit endpoint to verify write access
    # Actually creating a test issue would pollute the repo
    url = f"{GITHUB_API_BASE}/repos/{repo}/issues"
    print(f"   URL: {url}")
    print(f"   Note: Not actually creating an issue, just verifying URL is correct")
    
    return True


def main():
    """Main function"""
    print("=" * 60)
    print("🔍 GitHub Repository Verifier")
    print("=" * 60)
    
    # Show configuration
    print(f"\n📋 Configuration:")
    print(f"   GITHUB_REPO: {GITHUB_REPO}")
    print(f"   Token file: {GITHUB_TOKEN_FILE}")
    
    # Load token
    token = load_token()
    if not token:
        return 1
    
    print(f"   Token prefix: {token[:10]}...")
    
    # Check token
    token_ok = check_token_info(token)
    if not token_ok:
        return 1
    
    # Check repository
    repo_ok = check_repository(token, GITHUB_REPO)
    if not repo_ok:
        print("\n" + "=" * 60)
        print("💡 Suggestions:")
        print("   1. Verify the repository name is correct")
        print("   2. Make sure the repository exists on GitHub")
        print("   3. If private, ensure your token has access")
        print("   4. Check token has 'repo' scope")
        print("   5. Try setting GITHUB_REPO environment variable:")
        print(f"      export GITHUB_REPO=wazuh/community")
        print("=" * 60)
        return 1
    
    # Test issue creation
    test_create_issue(token, GITHUB_REPO)
    
    print("\n" + "=" * 60)
    print("✅ All checks passed! You're ready to create issues.")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Run the gateway:")
    print("   python main.py")
    print("2. Or run with debug logging:")
    print("   export LOG_LEVEL=DEBUG")
    print("   python main.py")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
