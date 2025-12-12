# -*- coding: utf-8 -*-
"""
资源清理模块。
提供统一的资源管理和清理机制。
"""

from .manager import (
    ResourceCleaner,
    ResourceManager,
    ResourcePriority,
    auto_cleanup,
    cleanup_all_resources,
    managed_resource,
    register_resource_cleaner,
    resource_manager,
)

__all__ = [
    "ResourceManager",
    "ResourcePriority",
    "ResourceCleaner",
    "resource_manager",
    "register_resource_cleaner",
    "cleanup_all_resources",
    "auto_cleanup",
    "managed_resource",
]
