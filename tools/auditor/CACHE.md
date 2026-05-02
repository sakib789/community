# Cache System Documentation

## Overview

The Community Auditor includes a SQLite-based cache system to reduce API calls and speed up execution. The cache stores data from GitHub, Slack, and GitHub GraphQL APIs.

## Configuration

All cache settings are at the top of `auditor.py`:

```python
# Global cache toggle - Set to True to use cache, False to always fetch fresh data
CACHE_ENABLED = True

# Individual cache toggles for each data type
CACHE_GITHUB_TEAMS = True      # Cache GitHub teams data
CACHE_SLACK_MEMBERS = True     # Cache Slack members data  
CACHE_PROJECT_ISSUES = True    # Cache GitHub project issues
```

### Cache Expiry Times

Data is automatically refreshed after the expiry time:

```python
CACHE_EXPIRY_HOURS = {
    'github_teams': 24,      # Teams don't change often
    'slack_members': 12,     # Member profiles change moderately
    'project_issues': 1      # Issues change frequently
}
```

## Usage

### Normal Operation

Just run the script normally. Cache will be used automatically if enabled:

```bash
python auditor.py
```

Output shows cache status:
```
📊 Community Auditor - Team Summary Generator
============================================================
💾 Cache: ENABLED
   - GitHub Teams: ON
   - Slack Members: ON
   - Project Issues: ON
============================================================
```

### Disable Cache Globally

Edit `auditor.py` and set:
```python
CACHE_ENABLED = False
```

### Disable Specific Cache Types

Edit `auditor.py` and set individual toggles:
```python
CACHE_GITHUB_TEAMS = False     # Disable only teams cache
CACHE_SLACK_MEMBERS = False    # Disable only Slack cache
CACHE_PROJECT_ISSUES = False   # Disable only issues cache
```

## Cache Management

### View Cache Status

```bash
python auditor.py --clear-cache
```

Shows current configuration and cache file location.

### Clear Specific Cache

Clear GitHub teams cache:
```bash
python auditor.py --clear-cache github_teams
```

Clear Slack members cache:
```bash
python auditor.py --clear-cache slack_members
```

Clear project issues cache:
```bash
python auditor.py --clear-cache project_issues
```

### Clear All Cache

```bash
python auditor.py --clear-cache all
```

## Cache Database

- **Location**: `auditor_cache.db` (in the same directory as auditor.py)
- **Format**: SQLite 3
- **Tables**: 
  - `github_teams` - GitHub team information
  - `team_members` - Members of each team
  - `slack_members` - Slack user profiles
  - `project_issues` - GitHub project issues

## How It Works

1. **First Run**: Fetches all data from APIs and saves to cache
   ```
   📋 Fetching GitHub teams from API...
   ✅ Found 16 allowed teams (out of 85 total)
   💾 Saved 16 GitHub teams to cache
   ```

2. **Subsequent Runs**: Loads from cache if not expired
   ```
   💾 Loaded 16 GitHub teams from cache
   💾 Loaded 223 Slack members from cache
   💾 Loaded 927 project issues from cache
   ```

3. **After Expiry**: Automatically fetches fresh data and updates cache

## Benefits

- **Speed**: 10-20x faster execution after first run
- **API Limits**: Reduces API calls to stay within rate limits
- **Offline Testing**: Can work with cached data during development
- **Flexibility**: Per-data-type control

## Performance Comparison

### Without Cache
```
First run: ~166 seconds
- GitHub teams: ~1.6s
- Slack members: ~60s
- Project issues: ~34s
- Working hours check: ~70s
```

### With Cache
```
First run: ~166 seconds (same, building cache)
Second run: ~15-20 seconds
- GitHub teams: <0.1s (cached)
- Slack members: <0.5s (cached)  
- Project issues: <1s (cached)
- Working hours check: ~70s (always live)
```

**Note**: Working hours checks are NEVER cached as they need real-time presence data.

## Troubleshooting

### Stale Data

If you suspect cached data is outdated:
```bash
python auditor.py --clear-cache all
```

### Cache Not Working

Check the configuration:
```bash
python auditor.py --clear-cache
```

Ensure `CACHE_ENABLED = True` and individual toggles are enabled.

### Database Errors

If you get SQLite errors, delete the cache file and rebuild:
```bash
rm auditor_cache.db
python auditor.py
```

## Advanced: Manual Cache Inspection

Using SQLite CLI:
```bash
sqlite3 auditor_cache.db

# View cached teams
SELECT * FROM github_teams;

# View cached Slack members
SELECT full_name, github_username, country FROM slack_members LIMIT 10;

# View cache age
SELECT 
    'github_teams' as cache_type, 
    MAX(cached_at) as last_updated,
    (julianday('now') - julianday(MAX(cached_at))) * 24 as hours_old
FROM github_teams;
```

## Best Practices

1. **Development**: Enable all caches to speed up testing
2. **Production**: Use conservative expiry times (current defaults are good)
3. **CI/CD**: Disable cache or clear before automated runs
4. **Debugging API Issues**: Temporarily disable specific cache to force fresh fetches

## Future Enhancements

Potential improvements:
- [ ] Per-issue granular caching
- [ ] Cache warming script
- [ ] Cache statistics/metrics
- [ ] Automatic cache cleanup of old data
