#!/usr/bin/env python3
"""
Community Tools - Main Orchestrator
Runs all components (Collectors and Auditor) in separate async tasks
"""

import asyncio
import os
import sys
import time
from datetime import datetime

# Add current directory to path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# Import centralized logging
from logging_config import setup_logger, set_log_level

# Setup main logger
logger = setup_logger("Main", log_file=os.path.join(SCRIPT_DIR, "main.log"))


# ======================== Component Runners ========================

async def run_slack_collector():
    """Run Slack collector gateway"""
    collector_logger = setup_logger("Collector.Slack")
    
    try:
        collector_logger.info("🚀 Starting Slack collector...")
        
        # Import and initialize
        from collector.slack_gw_v2 import SlackGateway, TokenManager
        
        token_manager = TokenManager()
        gateway = SlackGateway(token_manager)
        
        # Run gateway with auto-reconnect
        await gateway.run()
        
    except FileNotFoundError as e:
        collector_logger.warning(f"⚠️  Slack collector not available: {e}")
    except Exception as e:
        collector_logger.error(f"❌ Slack collector error: {e}", exc_info=True)
        # Wait before restarting
        await asyncio.sleep(30)
        collector_logger.info("🔄 Restarting Slack collector...")
        await run_slack_collector()


async def run_discord_collector():
    """Run Discord collector gateway"""
    collector_logger = setup_logger("Collector.Discord")
    
    try:
        collector_logger.info("🚀 Starting Discord collector...")
        
        # Import and initialize
        from collector.discord_gw import DiscordGateway
        
        gateway = DiscordGateway()
        
        # Run gateway
        await gateway.run()
        
    except FileNotFoundError as e:
        collector_logger.warning(f"⚠️  Discord collector not available: {e}")
    except Exception as e:
        collector_logger.error(f"❌ Discord collector error: {e}", exc_info=True)
        # Wait before restarting
        await asyncio.sleep(30)
        collector_logger.info("🔄 Restarting Discord collector...")
        await run_discord_collector()


async def run_auditor():
    """Run auditor in continuous mode"""
    auditor_logger = setup_logger("Auditor")
    
    iteration = 0
    
    while True:
        try:
            iteration += 1
            auditor_logger.info(f"🔄 Starting auditor iteration #{iteration}")
            
            # Import and run auditor
            from auditor.auditor import main as auditor_main
            
            # Run auditor synchronously
            auditor_main()
            
            auditor_logger.info(f"✅ Auditor iteration #{iteration} completed")
            
            # Wait 5 minutes before next iteration
            next_run = datetime.fromtimestamp(time.time() + 300)
            auditor_logger.info(f"⏸️  Next auditor run at: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
            await asyncio.sleep(300)
            
        except Exception as e:
            auditor_logger.error(f"❌ Auditor error: {e}", exc_info=True)
            # Wait before retrying
            auditor_logger.info("⏳ Waiting 60 seconds before retry...")
            await asyncio.sleep(60)


# ======================== Main Orchestrator ========================

async def main():
    """Main orchestrator - runs all components concurrently"""
    logger.info("=" * 60)
    logger.info("🚀 Community Tools - Main Orchestrator")
    logger.info("=" * 60)
    logger.info("")
    logger.info("Components:")
    logger.info("  • Slack Collector (WebSocket)")
    logger.info("  • Discord Collector (WebSocket)")
    logger.info("  • Auditor (every 5 minutes)")
    logger.info("")
    logger.info("Press Ctrl+C to stop all components")
    logger.info("=" * 60)
    logger.info("")
    
    # Create tasks for all components
    tasks = [
        asyncio.create_task(run_slack_collector(), name="SlackCollector"),
        asyncio.create_task(run_discord_collector(), name="DiscordCollector"),
        asyncio.create_task(run_auditor(), name="Auditor")
    ]
    
    try:
        # Wait for all tasks (they run indefinitely)
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.info("🛑 Shutting down all components...")
        for task in tasks:
            task.cancel()
        logger.info("✅ All components stopped")


if __name__ == "__main__":
    try:
        # Check for debug mode
        set_log_level(os.environ.get('LOG_LEVEL', 'INFO').upper())
        logger.info(f"🐛 Log level set to {os.environ.get('LOG_LEVEL', 'INFO').upper()}")
        
        # Run main orchestrator
        asyncio.run(main())
        
    except KeyboardInterrupt:
        logger.info("")
        logger.info("🛑 Received interrupt signal")
        logger.info("✅ Community Tools stopped gracefully")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)
        sys.exit(1)
