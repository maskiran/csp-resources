"""
Configuration module for MCP STE Jira integration.

This module provides access to configuration values loaded from config.json.
"""

import json
from pathlib import Path
from typing import Any

_config: dict[str, Any] = {}


def load_config() -> dict[str, Any]:
    """Load configuration from config.json file."""
    global _config
    if _config:
        return _config

    config_path = Path(__file__).parent / "config.json"
    try:
        _config = json.loads(config_path.read_text())
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Configuration file not found: {config_path}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in config file: {e}")
    return _config


def get_aws_profiles() -> list[str]:
    """Get AWS profiles from configuration."""
    config = load_config()
    return config.get("aws_profiles", [])


def get_azure_subs() -> list[str]:
    """Get Azure subscriptions from configuration."""
    config = load_config()
    return config.get("azure_subs", [])


def get_gcp_projects() -> list[str]:
    """Get GCP projects from configuration."""
    config = load_config()
    return config.get("gcp_projects", [])
