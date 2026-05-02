#!/usr/bin/env python3
"""
Test script to verify all components are working
"""

import sys
import os

# Add parent directory to path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

def test_imports():
    """Test that all imports work"""
    print("Testing imports...")
    
    try:
        import websockets
        print("✅ websockets")
    except ImportError as e:
        print(f"❌ websockets: {e}")
        return False
    
    try:
        import aiohttp
        print("✅ aiohttp")
    except ImportError as e:
        print(f"❌ aiohttp: {e}")
        return False
    
    try:
        import sqlite3
        print("✅ sqlite3")
    except ImportError as e:
        print(f"❌ sqlite3: {e}")
        return False
    
    try:
        from indexer.opensearch_indexer import OpenSearchIndexer
        print("✅ OpenSearchIndexer")
    except ImportError as e:
        print(f"❌ OpenSearchIndexer: {e}")
        print(f"   Make sure indexer module exists in: {PARENT_DIR}/indexer/")
        return False
    
    print()
    return True

def test_slack_gateway():
    """Test Slack gateway initialization"""
    print("Testing Slack gateway...")
    
    try:
        from slack_gw_v2 import SlackGateway, TokenManager
        print("✅ Slack imports successful")
        
        # Try to initialize (will fail without tokens, but should not crash)
        try:
            token_manager = TokenManager()
            gateway = SlackGateway(token_manager)
            print("✅ Slack gateway initialized (tokens found)")
        except FileNotFoundError as e:
            print(f"⚠️  Slack gateway init failed (tokens missing): {e}")
            print("   This is expected if you haven't set up .token_slack files")
        
        print()
        return True
    except Exception as e:
        print(f"❌ Slack gateway error: {e}")
        import traceback
        traceback.print_exc()
        print()
        return False

def test_discord_gateway():
    """Test Discord gateway initialization"""
    print("Testing Discord gateway...")
    
    try:
        from discord_gw import DiscordGateway
        print("✅ Discord imports successful")
        
        # Try to initialize (will fail without tokens, but should not crash)
        try:
            gateway = DiscordGateway()
            print("✅ Discord gateway initialized (token found)")
        except FileNotFoundError as e:
            print(f"⚠️  Discord gateway init failed (token missing): {e}")
            print("   This is expected if you haven't set up .token_discord file")
        
        print()
        return True
    except Exception as e:
        print(f"❌ Discord gateway error: {e}")
        import traceback
        traceback.print_exc()
        print()
        return False

def test_main():
    """Test main orchestrator"""
    print("Testing main orchestrator...")
    
    try:
        from main import GatewayOrchestrator
        print("✅ Main orchestrator imports successful")
        
        orchestrator = GatewayOrchestrator()
        print("✅ Orchestrator initialized")
        
        print()
        return True
    except Exception as e:
        print(f"❌ Main orchestrator error: {e}")
        import traceback
        traceback.print_exc()
        print()
        return False

def main():
    """Run all tests"""
    print("=" * 60)
    print("🧪 Component Test Suite")
    print("=" * 60)
    print()
    
    results = []
    
    results.append(("Imports", test_imports()))
    results.append(("Slack Gateway", test_slack_gateway()))
    results.append(("Discord Gateway", test_discord_gateway()))
    results.append(("Main Orchestrator", test_main()))
    
    print("=" * 60)
    print("📊 Test Results")
    print("=" * 60)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {name}")
    
    print()
    
    all_passed = all(result for _, result in results)
    
    if all_passed:
        print("✅ All tests passed!")
        print()
        print("Next steps:")
        print("1. Set up token files (.token_slack, .token_discord, .token_github)")
        print("2. Set up OpenSearch token (.token_opensearch in indexer/)")
        print("3. Run: python main.py")
        return 0
    else:
        print("❌ Some tests failed. Check errors above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
