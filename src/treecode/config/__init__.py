"""Configuration system for TreeCode.

Provides settings management, path resolution, and API key handling.
"""

from treecode.config.paths import (
    get_config_dir,
    get_config_file_path,
    get_data_dir,
    get_logs_dir,
)
from treecode.config.settings import Settings, load_settings

__all__ = [
    "Settings",
    "get_config_dir",
    "get_config_file_path",
    "get_data_dir",
    "get_logs_dir",
    "load_settings",
]
