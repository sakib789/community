# Centralized Logging System

## 📊 Changes Summary

### New Files Created

1. **`tools/logging_config.py`** - Centralized logging configuration
   - `setup_logger(name, log_file, level)` - Creates configured loggers
   - `get_logger(name)` - Gets existing logger
   - `set_log_level(level)` - Changes level for all loggers
   - Consistent format: `YYYY-MM-DD HH:MM:SS [Module.Component] [LEVEL] Message`

2. **`tools/main.py`** - Main orchestrator for all components
   - Runs Slack collector (async WebSocket)
   - Runs Discord collector (async WebSocket)
   - Runs Auditor (every 5 minutes)
   - Auto-restart on component failure
   - Graceful shutdown on Ctrl+C

3. **`tools/README_ORCHESTRATOR.md`** - Documentation
   - Architecture overview
   - Usage instructions
   - Module structure
   - Troubleshooting guide

### Modified Files

All these files now use centralized logging with module identifiers:

| File | Logger Name | Description |
|------|-------------|-------------|
| `collector/slack_gw_v2.py` | `Collector.Slack` | Slack WebSocket gateway |
| `collector/discord_gw.py` | `Collector.Discord` | Discord WebSocket gateway |
| `indexer/opensearch_indexer.py` | `Indexer` | OpenSearch document indexer |
| `auditor/opensearch_cache.py` | `Auditor.Cache` | OpenSearch cache manager |
| `auditor/opensearch_quota.py` | `Auditor.Quota` | Quota tracking manager |
| `assigner/assigner.py` | `Assigner` | Auto-assignment library |

## 🔄 Before & After

### Before

Each module had its own logging configuration:

```python
# Slack gateway
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [Collector: Slack] %(message)s",
    handlers=[...]
)
logging.info("Message")  # Direct module call
```

```python
# Discord gateway
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [Collector: Discord] %(message)s",
    handlers=[...]
)
logging.info("Message")  # Direct module call
```

**Problems:**
- ❌ Duplicated configuration
- ❌ Inconsistent formats
- ❌ Hard to control globally
- ❌ Module conflicts

### After

Centralized logging with module identifiers:

```python
# Any module
from logging_config import setup_logger

logger = setup_logger("Module.Component", log_file="optional.log")
logger.info("Message")  # Logger instance
```

**Benefits:**
- ✅ Single configuration point
- ✅ Consistent format everywhere
- ✅ Module names in logs
- ✅ Easy global control (`LOG_LEVEL` env var)
- ✅ No conflicts

## 📝 Log Output Examples

### Slack Collector
```
2026-01-26 15:30:45 [Collector.Slack] [INFO] 🚀 Starting Slack collector...
2026-01-26 15:30:46 [Collector.Slack] [INFO] 📝 Creating new GitHub issue for message 1760450458.359049
2026-01-26 15:30:47 [Collector.Slack] [INFO] ✅ Created GitHub issue #123: How to configure indexer?
```

### Discord Collector
```
2026-01-26 15:30:45 [Collector.Discord] [INFO] 🚀 Starting Discord collector...
2026-01-26 15:30:46 [Collector.Discord] [INFO] 📝 Creating new GitHub issue for Discord message 1234567890
2026-01-26 15:30:47 [Collector.Discord] [INFO] ✅ Created GitHub issue #124: Error with installation
```

### Indexer
```
2026-01-26 15:30:47 [Indexer] [INFO] ✅ Indexed parent document
2026-01-26 15:30:48 [Indexer] [DEBUG] ✅ Found document: slack_1760450458.359049
```

### Auditor
```
2026-01-26 15:35:00 [Auditor] [INFO] 🔄 Starting auditor iteration #1
2026-01-26 15:35:01 [Auditor.Cache] [INFO] 💾 Saved 150 Slack members to cache
2026-01-26 15:35:02 [Auditor.Quota] [INFO] 📊 Updated quota for 50 users
2026-01-26 15:35:03 [Auditor] [INFO] ✅ Auditor iteration #1 completed
```

### Assigner
```
2026-01-26 15:30:48 [Assigner] [INFO] 🎯 Assigning issue #123...
2026-01-26 15:30:49 [Assigner] [INFO]    Auto-assigned to: user123 (current tickets: 0)
2026-01-26 15:30:50 [Assigner] [INFO] ✅ Successfully assigned issue #123 to user123
```

## 🚀 Running the System

### Option 1: Main Orchestrator (Recommended)

Run everything from one command:

```bash
cd tools
python main.py
```

Output:
```
2026-01-26 15:30:00 [Main] [INFO] ============================================================
2026-01-26 15:30:00 [Main] [INFO] 🚀 Community Tools - Main Orchestrator
2026-01-26 15:30:00 [Main] [INFO] ============================================================
2026-01-26 15:30:00 [Main] [INFO] 
2026-01-26 15:30:00 [Main] [INFO] Components:
2026-01-26 15:30:00 [Main] [INFO]   • Slack Collector (WebSocket)
2026-01-26 15:30:00 [Main] [INFO]   • Discord Collector (WebSocket)
2026-01-26 15:30:00 [Main] [INFO]   • Auditor (every 5 minutes)
2026-01-26 15:30:00 [Main] [INFO] 
2026-01-26 15:30:00 [Main] [INFO] Press Ctrl+C to stop all components
2026-01-26 15:30:00 [Main] [INFO] ============================================================
2026-01-26 15:30:00 [Main] [INFO] 
2026-01-26 15:30:01 [Collector.Slack] [INFO] 🚀 Starting Slack collector...
2026-01-26 15:30:01 [Collector.Discord] [INFO] 🚀 Starting Discord collector...
2026-01-26 15:30:01 [Auditor] [INFO] 🔄 Starting auditor iteration #1
...
```

### Option 2: Individual Components

```bash
# Slack only
cd tools/collector
python slack_gw_v2.py

# Discord only
cd tools/collector
python discord_gw.py

# Auditor only
cd tools/auditor
python auditor.py
```

### Debug Mode

```bash
export LOG_LEVEL=DEBUG
python main.py
```

or

```bash
LOG_LEVEL=DEBUG python main.py
```

## 🎯 Key Features

### 1. Module Identification
Every log line shows which module/component generated it:
- `[Collector.Slack]`
- `[Collector.Discord]`
- `[Indexer]`
- `[Auditor]`
- `[Auditor.Cache]`
- `[Auditor.Quota]`
- `[Assigner]`

### 2. Environment Control
Change log level for ALL components:
```bash
export LOG_LEVEL=DEBUG  # Show debug messages
export LOG_LEVEL=INFO   # Normal operation
export LOG_LEVEL=WARNING # Only warnings and errors
```

### 3. File + Console Output
- Console: Real-time monitoring
- File: Persistent logs for debugging

### 4. Auto-Restart
Components restart automatically on failure:
```
2026-01-26 15:35:00 [Collector.Slack] [ERROR] ❌ Slack collector error: Connection lost
2026-01-26 15:35:30 [Collector.Slack] [INFO] 🔄 Restarting Slack collector...
2026-01-26 15:35:31 [Collector.Slack] [INFO] 🚀 Starting Slack collector...
```

## 📚 Migration Guide

### For New Modules

1. Import the centralized logger:
   ```python
   from logging_config import setup_logger
   
   logger = setup_logger("YourModule.Component")
   ```

2. Replace all `logging.*` calls with `logger.*`:
   ```python
   # Before
   logging.info("Message")
   logging.error("Error")
   
   # After
   logger.info("Message")
   logger.error("Error")
   ```

3. Remove old `logging.basicConfig()` calls

### For Existing Modules

Already done for:
- ✅ collector/slack_gw_v2.py
- ✅ collector/discord_gw.py
- ✅ indexer/opensearch_indexer.py
- ✅ auditor/opensearch_cache.py
- ✅ auditor/opensearch_quota.py
- ✅ assigner/assigner.py

## 🔧 Technical Details

### Logger Hierarchy

```
Main
├── Collector
│   ├── Slack
│   └── Discord
├── Auditor
│   ├── Cache
│   └── Quota
├── Indexer
└── Assigner
```

### Format String

```python
LOG_FORMAT = "%(asctime)s [%(name)s] [%(levelname)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
```

### Log Levels

```python
DEBUG    # Detailed information, typically for debugging
INFO     # Confirmation that things are working as expected
WARNING  # Something unexpected, but still working
ERROR    # Error occurred, but application continues
CRITICAL # Serious error, application may not continue
```

## 📦 File Structure

```
tools/
├── logging_config.py          # ⭐ NEW: Centralized logging
├── main.py                     # ⭐ NEW: Main orchestrator
├── README_ORCHESTRATOR.md      # ⭐ NEW: Documentation
│
├── main.log                    # Main orchestrator logs
│
├── collector/
│   ├── slack_gw_v2.py         # ✏️  MODIFIED: Uses centralized logging
│   ├── discord_gw.py          # ✏️  MODIFIED: Uses centralized logging
│   ├── slack_gateway.log      # Slack logs
│   └── discord_gateway.log    # Discord logs
│
├── auditor/
│   ├── auditor.py             # ✏️  MODIFIED: Uses centralized logging
│   ├── opensearch_cache.py    # ✏️  MODIFIED: Uses centralized logging
│   ├── opensearch_quota.py    # ✏️  MODIFIED: Uses centralized logging
│   └── community_auditor.log  # Auditor logs
│
├── indexer/
│   └── opensearch_indexer.py  # ✏️  MODIFIED: Uses centralized logging
│
└── assigner/
    └── assigner.py            # ✏️  MODIFIED: Uses centralized logging
```

## ✅ Benefits Summary

1. **Consistency** - Same format everywhere
2. **Clarity** - Know which module generated each log
3. **Control** - One place to change logging behavior
4. **Debugging** - Easy to filter logs by module
5. **Maintenance** - Less code duplication
6. **Scalability** - Easy to add new modules

## 🐛 Troubleshooting

See [README_ORCHESTRATOR.md](README_ORCHESTRATOR.md) for detailed troubleshooting.
