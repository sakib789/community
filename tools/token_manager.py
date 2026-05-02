#!/usr/bin/env python3
"""
Centralized Token Manager
Loads and manages all authentication tokens from a single location
"""

import os
from typing import Optional, Dict
from logging_config import setup_logger

logger = setup_logger("TokenManager")

# Token file locations (all in tools/ directory)
TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILES = {
    'github': os.path.join(TOOLS_DIR, '.token_github'),
    'slack_bot': os.path.join(TOOLS_DIR, '.token_slack'),
    'slack_app': os.path.join(TOOLS_DIR, '.token_slack_app'),
    'discord': os.path.join(TOOLS_DIR, '.token_discord'),
    'opensearch': os.path.join(TOOLS_DIR, '.token_opensearch'),
    'slack_user_workspace_wazuh_team': os.path.join(TOOLS_DIR, '.token_slack_user_workspace_wazuh_team'),
}


class TokenManager:
    """Centralized token management for all components"""
    
    def __init__(self):
        """Initialize token manager and load all tokens"""
        self.tokens: Dict[str, Optional[str]] = {}
        self._load_all_tokens()
    
    def _load_token(self, token_type: str, filepath: str) -> Optional[str]:
        """
        Load a token from file
        
        Args:
            token_type: Type of token (for logging)
            filepath: Path to token file
        
        Returns:
            Token string or None if not found
        """
        if not os.path.exists(filepath):
            logger.debug(f"Token file not found: {filepath}")
            return None
        
        try:
            with open(filepath, 'r') as f:
                lines = f.readlines()
                for line in lines:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        # Remove any whitespace/newlines
                        token = ''.join(line.split())
                        if token:
                            logger.debug(f"✅ Loaded {token_type} token (prefix: {token[:10]}...)")
                            return token
            
            logger.warning(f"⚠️  Token file is empty or contains only comments: {filepath}")
            return None
        
        except Exception as e:
            logger.error(f"❌ Error reading token file {filepath}: {e}")
            return None
    
    def _load_all_tokens(self):
        """Load all tokens from their files"""
        for token_type, filepath in TOKEN_FILES.items():
            self.tokens[token_type] = self._load_token(token_type, filepath)
        
        # Log summary
        loaded = sum(1 for token in self.tokens.values() if token is not None)
        total = len(self.tokens)
        logger.info(f"📋 Loaded {loaded}/{total} tokens")
    
    def get_token(self, token_type: str) -> Optional[str]:
        """
        Get a specific token
        
        Args:
            token_type: Type of token ('github', 'slack_bot', 'slack_app', 'discord', 'opensearch')
        
        Returns:
            Token string or None if not available
        """
        return self.tokens.get(token_type)
    
    def require_token(self, token_type: str) -> str:
        """
        Get a token and raise exception if not available
        
        Args:
            token_type: Type of token
        
        Returns:
            Token string
        
        Raises:
            FileNotFoundError: If token is not available
        """
        token = self.get_token(token_type)
        if token is None:
            raise FileNotFoundError(
                f"Required token '{token_type}' not found. "
                f"Expected at: {TOKEN_FILES.get(token_type, 'unknown')}"
            )
        return token
    
    def has_token(self, token_type: str) -> bool:
        """Check if a token is available"""
        return self.tokens.get(token_type) is not None
    
    def get_available_tokens(self) -> Dict[str, bool]:
        """Get availability status of all tokens"""
        return {
            token_type: token is not None
            for token_type, token in self.tokens.items()
        }
    
    def reload_token(self, token_type: str):
        """Reload a specific token from disk"""
        if token_type not in TOKEN_FILES:
            logger.error(f"❌ Unknown token type: {token_type}")
            return
        
        filepath = TOKEN_FILES[token_type]
        self.tokens[token_type] = self._load_token(token_type, filepath)
    
    def reload_all_tokens(self):
        """Reload all tokens from disk"""
        logger.info("🔄 Reloading all tokens...")
        self._load_all_tokens()


# Global token manager instance
_token_manager = None


def get_token_manager() -> TokenManager:
    """Get the global token manager instance"""
    global _token_manager
    if _token_manager is None:
        _token_manager = TokenManager()
    return _token_manager


# Convenience functions for backward compatibility
def get_github_token() -> Optional[str]:
    """Get GitHub token"""
    return get_token_manager().get_token('github')


def get_slack_bot_token() -> Optional[str]:
    """Get Slack bot token"""
    return get_token_manager().get_token('slack_bot')


def get_slack_app_token() -> Optional[str]:
    """Get Slack app token"""
    return get_token_manager().get_token('slack_app')

def get_slack_user_workspace_wazuh_team() -> Optional[str]:
    """Get Slack User Wazuh Community Wazuh team workspace token"""
    return get_token_manager().get_token('slack_user_workspace_wazuh_team')

def get_discord_token() -> Optional[str]:
    """Get Discord token"""
    return get_token_manager().get_token('discord')


def get_opensearch_password() -> Optional[str]:
    """Get OpenSearch password"""
    return get_token_manager().get_token('opensearch')


if __name__ == "__main__":
    # Test token manager
    print("🧪 Testing Token Manager\n")
    
    tm = TokenManager()
    
    print("\n📊 Token Availability:")
    for token_type, available in tm.get_available_tokens().items():
        status = "✅" if available else "❌"
        print(f"  {status} {token_type}")
    
    print("\n✅ Token Manager test complete!")
