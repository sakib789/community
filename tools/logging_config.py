#!/usr/bin/env python3
"""
Centralized Logging Configuration
All modules should use this to ensure consistent logging format and behavior
"""

import logging
import os
import sys
from typing import Optional


# ======================== Configuration ========================

# Default logging level (can be overridden by environment variable)
DEFAULT_LOG_LEVEL = "INFO"

# Log format with module name
LOG_FORMAT = "%(asctime)s [%(name)s] [%(levelname)s] %(message)s"

# Date format
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


# ======================== Logger Setup ========================

def setup_logger(name: str, log_file: Optional[str] = None, level: Optional[str] = None) -> logging.Logger:
    """
    Setup a logger with centralized configuration
    
    Args:
        name: Logger name (usually module name like "Collector.Slack")
        log_file: Optional log file path (if None, only console output)
        level: Optional log level override (if None, uses LOG_LEVEL env var or INFO)
    
    Returns:
        Configured logger instance
    """
    # Get log level from parameter, environment, or default
    if level is None:
        level = os.environ.get('LOG_LEVEL', DEFAULT_LOG_LEVEL).upper()
    
    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level, logging.INFO))
    
    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()
    
    # Create formatter
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    
    # Console handler (always present)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(getattr(logging, level, logging.INFO))
    logger.addHandler(console_handler)
    
    # File handler (optional)
    if log_file:
        try:
            file_handler = logging.FileHandler(log_file, mode="a")
            file_handler.setFormatter(formatter)
            file_handler.setLevel(getattr(logging, level, logging.INFO))
            logger.addHandler(file_handler)
        except Exception as e:
            logger.warning(f"Failed to create file handler for {log_file}: {e}")
    
    # Prevent propagation to avoid duplicate logs
    logger.propagate = False
    
    return logger


def get_logger(name: str) -> logging.Logger:
    """
    Get an existing logger or create a new one with default settings
    
    Args:
        name: Logger name
    
    Returns:
        Logger instance
    """
    logger = logging.getLogger(name)
    
    # If logger has no handlers, set it up with defaults
    if not logger.handlers:
        return setup_logger(name)
    
    return logger


def set_log_level(level: str):
    """
    Change log level for all existing loggers
    
    Args:
        level: New log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    level_obj = getattr(logging, level.upper(), logging.INFO)
    
    # Update all existing loggers
    for name in logging.Logger.manager.loggerDict:
        logger = logging.getLogger(name)
        logger.setLevel(level_obj)
        for handler in logger.handlers:
            handler.setLevel(level_obj)


# ======================== Example Usage ========================

if __name__ == "__main__":
    # Example: Create loggers for different modules
    collector_logger = setup_logger("Collector.Slack", log_file="collector.log")
    indexer_logger = setup_logger("Indexer")
    auditor_logger = setup_logger("Auditor.Cache")
    
    # Test logging
    collector_logger.info("Slack gateway started")
    indexer_logger.debug("Indexing document to OpenSearch")
    auditor_logger.warning("Cache expired, fetching fresh data")
    
    # Change log level dynamically
    set_log_level("DEBUG")
    collector_logger.debug("Now you can see debug messages!")
