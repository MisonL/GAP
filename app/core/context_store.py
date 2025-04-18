# -*- coding: utf-8 -*-
"""
处理 SQLite 数据库交互，用于存储代理密钥、对话上下文和设置。
支持文件存储（持久化）和内存存储（临时）。
"""
import sqlite3
import logging
import os
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any, Tuple
# from contextlib import contextmanager # 不再需要

# 导入配置以获取默认值 (现在由 db_settings 处理)
# from .. import config as app_config
from ..core import key_management
# 导入新的设置管理模块
from .db_settings import get_ttl_days, set_ttl_days
# 导入共享的数据库工具 和 新配置项
from .db_utils import get_db_connection, DATABASE_PATH, IS_MEMORY_DB, DEFAULT_CONTEXT_TTL_DAYS
from ..config import MAX_CONTEXT_RECORDS_MEMORY # 导入最大记录数配置

logger = logging.getLogger('my_logger')

# --- 数据库路径配置 (已移至 db_utils.py) ---
# ...

# --- 数据库连接 (已移至 db_utils.py) ---
# @contextmanager
# def get_db_connection(): ...

# --- 数据库初始化 (已移至 db_utils.py) ---
# def initialize_database(): ...

# --- 设置管理 (已移至 db_settings.py) ---
# def get_setting(...): ...
# def set_setting(...): ...
# def get_ttl_days(...): ...
# def set_ttl_days(...): ...

# --- 代理 Key 管理 (部分保留，用于 API 认证) ---
# generate_proxy_key, add_proxy_key, list_proxy_keys, update_proxy_key, delete_proxy_key 已移除，因为 Web UI 已移除

def get_proxy_key(key: str) -> Optional[Dict[str, Any]]:
     """获取单个代理 Key 的信息"""
     if not key: return None
     try:
         with get_db_connection() as conn:
             cursor = conn.cursor()
             cursor.execute("SELECT key, description, created_at, is_active FROM proxy_keys WHERE key = ?", (key,))
             row = cursor.fetchone()
             return dict(row) if row else None
     except sqlite3.Error as e:
         logger.error(f"获取代理 Key {key[:8]}... 信息失败: {e}", exc_info=True)
         return None

def is_valid_proxy_key(key: str) -> bool:
    """检查代理 Key 是否有效且处于活动状态 (从数据库)"""
    key_info = get_proxy_key(key)
    return bool(key_info and key_info.get('is_active'))

# list_proxy_keys 已移除
# update_proxy_key 已移除
# delete_proxy_key 已移除

# --- 上下文管理 ---
def save_context(proxy_key: str, contents: List[Dict[str, Any]]):
    """保存或更新指定代理 Key 的上下文"""
    if not proxy_key or not contents:
        logger.warning(f"尝试为 Key {proxy_key[:8]}... 保存空的上下文，已跳过。")
        return
    try:
        try:
            contents_json = json.dumps(contents, ensure_ascii=False)
        except TypeError as json_err:
            logger.error(f"序列化上下文为 JSON 时失败 (TypeError) (Key: {proxy_key[:8]}...): {json_err}", exc_info=True)
            return # 无法序列化，直接返回

        with get_db_connection() as conn:
            cursor = conn.cursor()
            # 使用 ISO 格式存储 UTC 时间戳
            last_used_ts = datetime.now(timezone.utc).isoformat()
            # 在引用之前确保 proxy_key 存在于 proxy_keys 表中
            # 这对于内存模式至关重要，因为 Key 可能不会预先填充
            cursor.execute("INSERT OR IGNORE INTO proxy_keys (key) VALUES (?)", (proxy_key,))
            logger.info(f"准备在连接 {id(conn)} 上为 Key {proxy_key[:8]}... 执行 INSERT OR REPLACE...") # 日志级别改为 info
            cursor.execute("""
                INSERT OR REPLACE INTO contexts (proxy_key, contents, last_used)
                VALUES (?, ?, ?)
            """, (proxy_key, contents_json, last_used_ts))
            logger.info(f"在连接 {id(conn)} 上为 Key {proxy_key[:8]}... 执行 INSERT OR REPLACE 完成。") # 移除了 "准备提交" 日志

            # --- 新增：内存数据库记录数限制 ---
            if IS_MEMORY_DB and MAX_CONTEXT_RECORDS_MEMORY > 0:
                try:
                    # 获取当前记录数
                    cursor.execute("SELECT COUNT(*) FROM contexts")
                    count_row = cursor.fetchone()
                    current_count = count_row[0] if count_row else 0
                    # logger.debug(f"内存数据库当前记录数: {current_count}, 限制: {MAX_CONTEXT_RECORDS_MEMORY}") # 调试日志

                    if current_count > MAX_CONTEXT_RECORDS_MEMORY:
                        num_to_delete = current_count - MAX_CONTEXT_RECORDS_MEMORY
                        logger.info(f"内存数据库记录数 ({current_count}) 已超过限制 ({MAX_CONTEXT_RECORDS_MEMORY})，将删除 {num_to_delete} 条最旧的记录...")
                        # 删除 last_used 最早的记录
                        # 使用 rowid 可以确保删除的是物理上最早插入（或最近未更新）的行
                        cursor.execute("""
                            DELETE FROM contexts
                            WHERE rowid IN (
                                SELECT rowid FROM contexts ORDER BY last_used ASC LIMIT ?
                            )
                        """, (num_to_delete,))
                        logger.info(f"成功删除了 {cursor.rowcount} 条最旧的内存上下文记录。")
                except sqlite3.Error as prune_err:
                    # 记录修剪错误，但不影响主保存操作的提交
                    logger.error(f"修剪内存上下文记录时出错 (Key: {proxy_key[:8]}...): {prune_err}", exc_info=True)

            # 提交事务（包括插入/替换和可能的删除）
            logger.info(f"准备在连接 {id(conn)} 上为 Key {proxy_key[:8]}... 提交事务...")
            conn.commit()
            logger.info(f"在连接 {id(conn)} 上为 Key {proxy_key[:8]}... 提交事务完成。")
    except sqlite3.Error as e:
        logger.error(f"为 Key {proxy_key[:8]}... 保存上下文失败: {e}", exc_info=True)
    except json.JSONDecodeError as e:
        logger.error(f"反序列化上下文为 JSON 时失败 (Key: {proxy_key[:8]}...): {e}", exc_info=True) # 修正了日志消息：反序列化错误
    except Exception as e: # 捕获保存期间任何其他意外错误
        logger.error(f"保存上下文时发生意外错误 (Key: {proxy_key[:8]}...): {e}", exc_info=True)

def load_context(proxy_key: str) -> Optional[List[Dict[str, Any]]]:
    """加载指定代理 Key 的上下文，并检查 TTL"""
    if not proxy_key: return None

    ttl_days = get_ttl_days()
    # 如果 TTL <= 0，则禁用 TTL 检查
    if ttl_days <= 0:
        ttl_delta = None
    else:
        ttl_delta = timedelta(days=ttl_days)

    now_utc = datetime.now(timezone.utc)

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT contents, last_used FROM contexts WHERE proxy_key = ?", (proxy_key,))
            row = cursor.fetchone()

            if row and row['contents']:
                last_used_str = row['last_used']
                # 检查 TTL (仅当 ttl_delta 有效时)
                if ttl_delta:
                    try:
                        # 解析存储的 ISO 格式 UTC 时间戳
                        last_used_dt = datetime.fromisoformat(last_used_str).replace(tzinfo=timezone.utc)
                        if now_utc - last_used_dt > ttl_delta:
                            logger.info(f"Key {proxy_key[:8]}... 的上下文已超过 TTL ({ttl_days} 天)，将被删除。")
                            delete_context_for_key(proxy_key) # 调用删除函数
                            return None
                    except (ValueError, TypeError) as dt_err:
                         logger.error(f"解析 Key {proxy_key[:8]}... 的 last_used 时间戳 '{last_used_str}' 失败: {dt_err}")
                         # 时间戳无效，可能也需要删除？或者忽略 TTL 检查？暂时忽略 TTL 检查。
                         pass # 继续尝试加载内容

                # TTL 检查通过、被禁用或解析失败，尝试加载内容
                try:
                    contents = json.loads(row['contents'])
                    logger.debug(f"上下文已为 Key {proxy_key[:8]}... 加载。")
                    return contents
                except json.JSONDecodeError as e:
                    logger.error(f"反序列化存储的上下文时失败 (Key: {proxy_key[:8]}...): {e}", exc_info=True)
                    # 删除损坏的数据，避免下次加载时再次出错
                    delete_context_for_key(proxy_key)
                    return None
            else:
                logger.debug(f"未找到 Key {proxy_key[:8]}... 的上下文。")
                return None
    except sqlite3.Error as e:
        logger.error(f"为 Key {proxy_key[:8]}... 加载上下文失败: {e}", exc_info=True)
        return None

def delete_context_for_key(proxy_key: str) -> bool:
    """删除指定代理 Key 的上下文记录"""
    if not proxy_key: return False
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM contexts WHERE proxy_key = ?", (proxy_key,))
            conn.commit()
            if cursor.rowcount > 0:
                logger.info(f"上下文已为 Key {proxy_key[:8]}... 删除。")
                return True
            else:
                # 这不一定是警告，可能只是记录不存在或已被 TTL 清理
                logger.debug(f"尝试删除 Key {proxy_key[:8]}... 的上下文，但未找到记录。")
                return False
    except sqlite3.Error as e:
        logger.error(f"删除 Key {proxy_key[:8]}... 的上下文失败: {e}", exc_info=True)
        return False

def get_context_info(proxy_key: str) -> Optional[Dict[str, Any]]:
     """获取指定代理 Key 上下文的元信息"""
     if not proxy_key: return None
     try:
         with get_db_connection() as conn:
             cursor = conn.cursor()
             cursor.execute("SELECT length(contents) as content_length, last_used FROM contexts WHERE proxy_key = ?", (proxy_key,))
             row = cursor.fetchone()
             return dict(row) if row else None
     except sqlite3.Error as e:
         logger.error(f"获取 Key {proxy_key[:8]}... 的上下文信息失败: {e}", exc_info=True)
         return None

def list_all_context_keys_info() -> List[Dict[str, Any]]:
    """获取所有存储的上下文的 Key 和元信息"""
    contexts_info = []
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # 获取 key, 长度和最后使用时间
            logger.info(f"list_all_context_keys_info: Preparing to execute SELECT query on connection {id(conn)}...")
            cursor.execute("SELECT proxy_key, length(contents) as content_length, last_used FROM contexts ORDER BY last_used DESC")
            rows = cursor.fetchall()
            # 以 INFO 级别记录从数据库获取的原始行
            logger.info(f"list_all_context_keys_info: Fetched {len(rows)} rows from DB. Raw rows: {rows}")
            contexts_info = [dict(row) for row in rows]
    except sqlite3.Error as e:
        logger.error(f"列出所有上下文信息失败 ({DATABASE_PATH}): {e}", exc_info=True)
        # 出错时返回空列表
        contexts_info = []
    return contexts_info

# --- 内存数据库清理 ---
def cleanup_memory_context(max_age_seconds: int):
    """清理内存数据库中超过指定时间的旧上下文记录"""
    if not IS_MEMORY_DB:
        # logger.debug("非内存数据库模式，跳过内存清理任务。") # 减少不必要的日志噪音
        return

    if max_age_seconds <= 0:
        logger.warning("内存上下文清理间隔无效 (<= 0)，跳过清理。")
        return

    cutoff_time = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
    # 使用 ISO 格式进行比较
    cutoff_timestamp_str = cutoff_time.isoformat()
    deleted_count = 0

    logger.info(f"开始清理内存数据库中早于 {cutoff_timestamp_str} UTC 的上下文...")
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # 删除 last_used 早于截止时间的记录
            # 注意：SQLite 的时间字符串比较依赖于一致的格式 (ISO 8601)
            cursor.execute("DELETE FROM contexts WHERE last_used < ?", (cutoff_timestamp_str,))
            deleted_count = cursor.rowcount
            conn.commit()
        if deleted_count > 0:
            logger.info(f"成功清理了 {deleted_count} 条过期的内存上下文记录。")
        else:
            logger.info("没有需要清理的过期内存上下文记录。")
    except sqlite3.Error as e:
        logger.error(f"清理内存上下文时出错: {e}", exc_info=True)