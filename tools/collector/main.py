#!/usr/bin/env python3
"""
Main Gateway Orchestrator
Runs Slack, Discord, and Reddit gateways concurrently when available
"""

import asyncio
import logging
import os
import sys
from datetime import datetime

# Add parent directory to path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# Import gateways
from slack_gw_v2 import SlackGateway, TokenManager as SlackTokenManager
from discord_gw import DiscordGateway
from reddit_gw import RedditGateway
from google_group_gw import GoogleGroupGateway

# Configuration
LOG_FILE = os.path.join(SCRIPT_DIR, 'main_gateway.log')

# Setup logging with both file and console handlers
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="a"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("MainGateway")


class GatewayOrchestrator:
    """Orchestrates multiple gateway connections"""
    
    def __init__(self):
        self.slack_gateway = None
        self.discord_gateway = None
        self.reddit_gateway = None
        self.google_group_gateway = None
        self.tasks = []
    
    async def initialize_slack(self):
        """Initialize Slack gateway"""
        try:
            token_manager = SlackTokenManager()
            self.slack_gateway = SlackGateway(token_manager)
            logger.info("✅ Slack gateway initialized")
            return True
        except FileNotFoundError as e:
            logger.warning(f"⚠️  Slack gateway not available: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Failed to initialize Slack gateway: {e}")
            return False
    
    async def initialize_discord(self):
        """Initialize Discord gateway"""
        try:
            self.discord_gateway = DiscordGateway()
            logger.info("✅ Discord gateway initialized")
            return True
        except FileNotFoundError as e:
            logger.warning(f"⚠️  Discord gateway not available: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Failed to initialize Discord gateway: {e}")
            return False

    async def initialize_reddit(self):
        """Initialize Reddit gateway"""
        try:
            self.reddit_gateway = RedditGateway()
            logger.info("✅ Reddit gateway initialized")
            return True
        except FileNotFoundError as e:
            logger.warning(f"⚠️  Reddit gateway not available: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Failed to initialize Reddit gateway: {e}")
            return False

    async def initialize_google_group(self):
        """Initialize Google Groups gateway"""
        try:
            self.google_group_gateway = GoogleGroupGateway()
            logger.info("✅ Google Groups gateway initialized")
            return True
        except FileNotFoundError as e:
            logger.warning(f"⚠️  Google Groups gateway not available: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Failed to initialize Google Groups gateway: {e}")
            return False
    
    async def run_slack(self):
        """Run Slack gateway with error handling"""
        if not self.slack_gateway:
            return
        
        logger.info("🚀 Starting Slack gateway...")
        try:
            await self.slack_gateway.run()
        except Exception as e:
            logger.error(f"❌ Slack gateway error: {e}")
            raise
    
    async def run_discord(self):
        """Run Discord gateway with error handling"""
        if not self.discord_gateway:
            return
        
        logger.info("🚀 Starting Discord gateway...")
        try:
            await self.discord_gateway.run()
        except Exception as e:
            logger.error(f"❌ Discord gateway error: {e}")
            raise

    async def run_reddit(self):
        """Run Reddit gateway with error handling"""
        if not self.reddit_gateway:
            return

        logger.info("🚀 Starting Reddit gateway...")
        try:
            await self.reddit_gateway.run()
        except Exception as e:
            logger.error(f"❌ Reddit gateway error: {e}")
            raise

    async def run_google_group(self):
        """Run Google Groups gateway with error handling"""
        if not self.google_group_gateway:
            return

        logger.info("🚀 Starting Google Groups gateway...")
        try:
            await self.google_group_gateway.run()
        except Exception as e:
            logger.error(f"❌ Google Groups gateway error: {e}")
            raise
    
    async def run(self):
        """Run all available gateways concurrently"""
        logger.info("=" * 60)
        logger.info("🌐 Gateway Orchestrator Starting")
        logger.info("=" * 60)
        
        # Initialize gateways
        slack_available = await self.initialize_slack()
        discord_available = await self.initialize_discord()
        reddit_available = await self.initialize_reddit()
        google_group_available = await self.initialize_google_group()
        
        if not slack_available and not discord_available and not reddit_available and not google_group_available:
            logger.error("❌ No gateways available. Exiting.")
            return
        
        # Create tasks for available gateways
        tasks = []
        
        if slack_available:
            logger.info("📱 Slack gateway will be started")
            tasks.append(asyncio.create_task(self.run_slack(), name="Slack"))
        
        if discord_available:
            logger.info("🎮 Discord gateway will be started")
            tasks.append(asyncio.create_task(self.run_discord(), name="Discord"))

        if reddit_available:
            logger.info("🟥 Reddit gateway will be started")
            tasks.append(asyncio.create_task(self.run_reddit(), name="Reddit"))

        if google_group_available:
            logger.info("📧 Google Groups gateway will be started")
            tasks.append(asyncio.create_task(self.run_google_group(), name="GoogleGroups"))
        
        logger.info("-" * 60)
        logger.info(f"🎯 Running {len(tasks)} gateway(s)")
        logger.info("🛑 Press Ctrl+C to stop all gateways")
        logger.info("-" * 60)
        
        # Wait for all tasks
        try:
            await asyncio.gather(*tasks)
        except KeyboardInterrupt:
            logger.info("🛑 Received shutdown signal")
            # Cancel all tasks
            for task in tasks:
                if not task.done():
                    task.cancel()
            # Wait for cancellation
            await asyncio.gather(*tasks, return_exceptions=True)
            logger.info("✅ All gateways stopped")
        except Exception as e:
            logger.error(f"❌ Unexpected error: {e}")
            # Cancel remaining tasks
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


async def main():
    """Main entry point"""
    print("╔" + "═" * 58 + "╗")
    print("║" + " " * 10 + "🌐 Community Gateway Orchestrator" + " " * 14 + "║")
    print("╚" + "═" * 58 + "╝")
    print()
    print("Features:")
    print("  • Slack → GitHub + OpenSearch integration")
    print("  • Discord → GitHub + OpenSearch integration")
    print("  • Reddit → GitHub issue/comment integration")
    print("  • Google Groups (Pub/Sub) → GitHub + OpenSearch integration")
    print("  • Concurrent multi-platform monitoring")
    print("  • Parent/child document relationships")
    print()
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    orchestrator = GatewayOrchestrator()
    
    try:
        await orchestrator.run()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down gracefully...")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        print(f"\n❌ Fatal error: {e}")
    finally:
        print("\n✅ Goodbye!")


if __name__ == "__main__":
    # Check dependencies
    missing_deps = []
    
    try:
        import websockets
    except ImportError:
        missing_deps.append("websockets")
    
    try:
        import aiohttp
    except ImportError:
        missing_deps.append("aiohttp")
    
    if missing_deps:
        print("❌ Missing dependencies. Install with:")
        print(f"pip install {' '.join(missing_deps)}")
        sys.exit(1)
    
    # Run the orchestrator
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass



