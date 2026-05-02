# Community Tools - Main Orchestrator

This directory contains the main orchestrator for all community tools components.

## 🏗️ Architecture

### Centralized Logging (`logging_config.py`)

All modules use a centralized logging configuration:

```python
from logging_config import setup_logger

# Create a logger with module identifier
logger = setup_logger("Module.Component", log_file="optional.log")

# Use the logger
logger.info("Message")
logger.debug("Debug info")
logger.warning("Warning")
logger.error("Error occurred")
```

**Benefits:**
- ✅ Consistent log format across all modules
- ✅ Module names in logs (e.g., `[Collector.Slack]`, `[Auditor.Cache]`, `[Indexer]`)
- ✅ Environment variable control: `LOG_LEVEL=DEBUG`
- ✅ Centralized file and console output

### Main Orchestrator (`main.py`)

Runs all components concurrently using async tasks:

```bash
cd tools
python main.py
```

**Components:**
1. **Slack Collector** - WebSocket connection to Slack
2. **Discord Collector** - WebSocket connection to Discord  
3. **Auditor** - Runs every 5 minutes

All components run in separate async tasks with auto-restart on failure.

## 📊 Module Structure

```
tools/
├── main.py                      # Main orchestrator
├── logging_config.py            # Centralized logging
│
├── collector/
│   ├── slack_gw_v2.py          # Uses: Collector.Slack
│   ├── discord_gw.py           # Uses: Collector.Discord
│   └── main.py                 # Old individual orchestrator
│
├── auditor/
│   ├── auditor.py              # Uses: Auditor
│   ├── opensearch_cache.py     # Uses: Auditor.Cache
│   └── opensearch_quota.py     # Uses: Auditor.Quota
│
├── indexer/
│   └── opensearch_indexer.py   # Uses: Indexer
│
└── assigner/
    └── assigner.py             # Uses: Assigner
```

## 🚀 Usage

### Run Everything (Recommended)

```bash
cd tools
python main.py
```

This starts:
- Slack gateway (WebSocket)
- Discord gateway (WebSocket)
- Auditor (every 5 minutes)

### Run Individual Components

If you only want to run specific components:

```bash
# Slack collector only
cd tools/collector
python slack_gw_v2.py

# Discord collector only
cd tools/collector
python discord_gw.py

# Auditor only (continuous mode)
cd tools/auditor
python auditor.py
```

### Debug Mode

Enable detailed logging:

```bash
export LOG_LEVEL=DEBUG
python main.py
```

Or:

```bash
export DEBUG=1
python main.py
```

## 📝 Log Format

All logs follow this format:

```
YYYY-MM-DD HH:MM:SS [Module.Component] [LEVEL] Message
```

**Examples:**

```
2026-01-26 15:30:45 [Collector.Slack] [INFO] 🚀 Starting Slack collector...
2026-01-26 15:30:46 [Indexer] [INFO] ✅ Indexed parent document
2026-01-26 15:30:47 [Auditor.Quota] [INFO] 📊 Updated quota for user123
2026-01-26 15:30:48 [Assigner] [INFO] ✅ Assigned issue #456 to user789
```

## 🔧 Environment Variables

- `LOG_LEVEL` - Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- `DEBUG` - Set to `1` to enable debug mode
- `GITHUB_REPO` - Target GitHub repository (e.g., `wazuh/community-dev`)

## 🛠️ Adding New Modules

1. Import centralized logging:
   ```python
   from logging_config import setup_logger
   logger = setup_logger("YourModule.Component")
   ```

2. Use logger throughout your code:
   ```python
   logger.info("Your message")
   logger.error(f"Error: {error}")
   ```

3. Add to orchestrator if needed (in `main.py`):
   ```python
   async def run_your_component():
       logger = setup_logger("YourModule")
       # ... your component logic
   ```

## 📦 Log Files

Each component can have its own log file:

- `tools/main.log` - Main orchestrator log
- `tools/collector/slack_gateway.log` - Slack collector
- `tools/collector/discord_gateway.log` - Discord collector
- `tools/auditor/community_auditor.log` - Auditor

All logs are also sent to console (stdout) for real-time monitoring.

## 🔄 Component Lifecycle

1. **Startup**: Main orchestrator starts all components concurrently
2. **Running**: Components run indefinitely with their own logic
3. **Error Handling**: Each component has auto-restart on failure
4. **Shutdown**: Ctrl+C gracefully stops all components

## 📚 Dependencies

All dependencies are consolidated in the main requirements file:

```bash
cd tools
pip install -r requirements.txt
```

This includes all requirements for collector, auditor, assigner, and indexer components.

## 🎯 Benefits of New Architecture

✅ **Unified Logging** - Consistent format and module identification  
✅ **Single Entry Point** - One command runs everything  
✅ **Auto-Recovery** - Components restart on failure  
✅ **Easy Debugging** - LOG_LEVEL control for all components  
✅ **Modular** - Each component can still run independently  
✅ **Scalable** - Easy to add new components to orchestrator  

## 🐛 Troubleshooting

### No logs appearing?

Check LOG_LEVEL:
```bash
export LOG_LEVEL=DEBUG
python main.py
```

### Component not starting?

Check individual component:
```bash
cd tools/collector
LOG_LEVEL=DEBUG python slack_gw_v2.py
```

### Import errors?

Make sure you're running from the correct directory:
```bash
cd tools  # Must be in tools/ directory
python main.py
```
