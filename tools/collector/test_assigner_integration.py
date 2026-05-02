#!/usr/bin/env python3
"""
Test script to verify assigner logs appear correctly
"""

import sys
import logging
import os

# Setup logging like main.py does
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] [%(levelname)s] %(message)s"
)

logger = logging.getLogger("TestAssigner")

# Add parent directory to path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

logger.info("=" * 60)
logger.info("🧪 Testing Assigner Integration")
logger.info("=" * 60)

try:
    from assigner.assigner import IssueAssigner
    
    logger.info("📦 Creating IssueAssigner instance...")
    assigner = IssueAssigner()
    
    logger.info("📊 Getting available users...")
    users = assigner.get_available_users()
    
    if users:
        logger.info(f"✅ Found {len(users)} users with available quota")
        for user in users[:5]:
            logger.info(f"   - {user['github_username']}: {user['ticket_count']} tickets")
    else:
        logger.warning("⚠️  No users with available quota")
    
    logger.info("=" * 60)
    logger.info("✅ Test completed successfully!")
    logger.info("=" * 60)
    
except Exception as e:
    logger.error(f"❌ Test failed: {e}", exc_info=True)
    sys.exit(1)
