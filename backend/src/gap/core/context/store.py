# -*- coding: utf-8 -*-
"""
处理 SQLite 数据库交互，用于存储和管理对话上下文。
支持文件存储（持久化）和内存存储（临时）。
包含加载、保存、删除上下文，以及检查 TTL 和清理内存数据库的功能。
"""
import aiosqlite # 导入 aiosqlite 模块，用于异步 SQLite 操作
import logging # 导入日志模块
import os # 导入 os 模块 (在此文件中未使用，但保留可能有用)
import json # 导入 json 模块，用于序列化和反序列化上下文内容
import uuid # 导入 uuid 模块 (在此文件中未使用，但保留可能有用)
import asyncio # 导入 asyncio 库，用于异步操作和线程池
from datetime import datetime, timedelta, timezone # 导入日期、时间、时间差和时区处理
from contextlib import asynccontextmanager # 导入异步上下文管理器
from typing import Optional, List, Dict, Any, Tuple, Union, AsyncGenerator # 导入类型提示
from sqlalchemy import select, delete, update as sqlalchemy_update 
from sqlalchemy.ext.asyncio import AsyncSession # 导入 AsyncSession
from sqlalchemy.dialects.sqlite import insert as sqlite_insert # 用于 INSERT OR REPLACE
from gap.core.context.converter import convert_messages # 导入消息转换函数 (新路径)

# 导入 Message Pydantic 模型，用于类型检查和数据结构定义
from gap.api.models import Message
# 导入新的数据库模型
from gap.core.database.models import DialogContext

# 导入数据库设置管理模块中的函数
from gap.core.database.settings import get_ttl_days, set_ttl_days # (新路径)
# 导入应用配置中的内存数据库最大记录数限制
from gap.config import MAX_CONTEXT_RECORDS_MEMORY, CONTEXT_STORAGE_MODE, CONTEXT_DB_PATH, DEFAULT_CONTEXT_TTL_DAYS # 导入配置 (添加 DEFAULT_CONTEXT_TTL_DAYS)
from gap import config as app_config # 确保 app_config 也被导入以备他用

logger = logging.getLogger('my_logger') # 获取日志记录器实例

async def get_proxy_key(key: str) -> Optional[Dict[str, Any]]:
     """
     (可能需要审查/移除) 获取单个代理 Key 的信息 (似乎与 Key 管理功能重复)。
     """
     if not key: return None 
     try:
         from gap.core.database.utils import get_db_connection 
         async with get_db_connection() as conn: 
             async with conn.cursor() as cursor: 
                 await cursor.execute("SELECT key, description, created_at, is_active FROM proxy_keys WHERE key = ?", (key,))
                 row = await cursor.fetchone() 
             return dict(row) if row else None
     except aiosqlite.Error as e: 
         logger.error(f"获取代理 Key {key[:8]}... 信息失败: {e}", exc_info=True) 
         return None

async def is_valid_proxy_key(key: str) -> bool:
    """
    (可能需要审查/移除) 检查代理 Key 是否有效且处于活动状态 (似乎与 Key 管理功能重复)。
    """
    key_info = await get_proxy_key(key) 
    return bool(key_info and key_info.get('is_active'))


async def save_context(proxy_key: str, contents: List[Dict[str, Any]]):
    """
    异步保存或更新指定代理 Key (通常是 user_id) 的对话上下文到数据库。
    """
    if not proxy_key or not contents:
        logger.warning(f"尝试为 Key {proxy_key[:8]}... 保存空的上下文，已跳过。")
        return

    from gap.core.dependencies import get_db_session 

    try:
        contents_json = await asyncio.to_thread(json.dumps, contents, ensure_ascii=False)
    except TypeError as json_err:
        logger.error(f"序列化上下文为 JSON 时失败 (TypeError) (Key: {proxy_key[:8]}...): {json_err}", exc_info=True)
        return

    async for db in get_db_session(): 
        try:
            now_dt = datetime.now(timezone.utc)
            stmt = sqlite_insert(DialogContext).values(
                proxy_key=proxy_key,
                contents=contents_json,
                last_used_at=now_dt,
                created_at=now_dt 
            )
            update_dict = {
                "contents": stmt.excluded.contents,
                "last_used_at": stmt.excluded.last_used_at
            }
            stmt = stmt.on_conflict_do_update(
                index_elements=[DialogContext.proxy_key], 
                set_=update_dict
            )
            await db.execute(stmt)
            await db.commit()
            logger.info(f"上下文已为 Key {proxy_key[:8]}... 使用 ORM 保存/更新。")
            break 
        except Exception as e:
            logger.error(f"为 Key {proxy_key[:8]}... 使用 ORM 保存上下文失败: {e}", exc_info=True)
            await db.rollback() 
            break
        finally:
            pass


async def _is_context_expired(last_used_dt: datetime, ttl_delta: Optional[timedelta], proxy_key: str, db: AsyncSession) -> bool:
    """
    (内部辅助函数) 检查上下文是否已过期。
    """
    if not ttl_delta:
        return False
    now_utc = datetime.now(timezone.utc)
    if last_used_dt.tzinfo is None:
        last_used_dt = last_used_dt.replace(tzinfo=timezone.utc)
    if now_utc - last_used_dt > ttl_delta:
        logger.info(f"Key {proxy_key[:8]}... 的上下文已超过 TTL ({ttl_delta})，将被视为过期。")
        await delete_context_for_key(proxy_key, db) 
        return True
    return False

async def delete_context_for_key(proxy_key: str, db: AsyncSession) -> bool:
    """
    异步删除指定代理 Key 的所有上下文记录。
    """
    if not proxy_key: return False
    try:
        stmt = delete(DialogContext).where(DialogContext.proxy_key == proxy_key)
        result = await db.execute(stmt)
        await db.commit()
        if result.rowcount > 0:
            logger.info(f"上下文已为 Key {proxy_key[:8]}... 使用 ORM 删除。")
            return True
        else:
            logger.warning(f"尝试使用 ORM 删除 Key {proxy_key[:8]}... 的上下文，但未找到记录。")
            return True 
    except Exception as e:
        logger.error(f"使用 ORM 删除 Key {proxy_key[:8]}... 的上下文失败: {e}", exc_info=True)
        await db.rollback()
        return False

async def _deserialize_context_contents(contents_json: str, proxy_key: str, db: AsyncSession) -> Optional[List[Dict[str, Any]]]:
    """
    (内部辅助函数) 异步反序列化存储的上下文 JSON 字符串。
    """
    try:
        contents = await asyncio.to_thread(json.loads, contents_json)
        logger.debug(f"上下文 JSON 已为 Key {proxy_key[:8]}... 反序列化。")
        if isinstance(contents, list):
            return contents
        else:
            logger.error(f"反序列化的上下文格式不正确 (期望列表，得到 {type(contents)}) (Key: {proxy_key[:8]}...)")
            await delete_context_for_key(proxy_key, db) 
            return None
    except json.JSONDecodeError as e:
        logger.error(f"反序列化存储的上下文时失败 (Key: {proxy_key[:8]}...): {e}", exc_info=True)
        await delete_context_for_key(proxy_key, db) 
        return None
    except Exception as e:
        logger.error(f"反序列化上下文时发生意外错误 (Key: {proxy_key[:8]}...): {e}", exc_info=True)
        await delete_context_for_key(proxy_key, db) 
        return None

async def load_context(proxy_key: str, db: AsyncSession) -> Optional[List[Dict[str, Any]]]:
    logger.info(f"load_context: Received db type: {type(db)}, db repr: {repr(db)}") # 添加日志
    """
    异步加载指定代理 Key 的对话上下文。
    """
    if not proxy_key: return None
    ttl_days = await get_ttl_days(db=db) 
    ttl_delta = timedelta(days=ttl_days) if ttl_days > 0 else None
    try:
        stmt = select(DialogContext).where(DialogContext.proxy_key == proxy_key)
        result = await db.execute(stmt)
        record: Optional[DialogContext] = result.scalar_one_or_none()
        if not record or not record.contents:
            logger.debug(f"未找到 Key {proxy_key[:8]}... 的上下文 (ORM)。")
            return None
        if await _is_context_expired(record.last_used_at, ttl_delta, proxy_key, db):
             return None
        return await _deserialize_context_contents(record.contents, proxy_key, db)
    except Exception as e:
        logger.error(f"为 Key {proxy_key[:8]}... 使用 ORM 加载上下文失败: {e}", exc_info=True)
        return None

async def get_context_info(proxy_key: str, db: AsyncSession) -> Optional[Dict[str, Any]]:
     """
     异步获取指定代理 Key 上下文的元信息。
     """
     if not proxy_key: return None
     try:
         stmt = select(DialogContext.contents, DialogContext.last_used_at).where(DialogContext.proxy_key == proxy_key)
         result = await db.execute(stmt)
         row = result.one_or_none()
         if row:
             content_length = len(row.contents) if row.contents else 0
             last_used_iso = row.last_used_at.isoformat() if row.last_used_at else None
             return {"content_length": content_length, "last_used": last_used_iso}
         else:
             return None
     except Exception as e:
         logger.error(f"使用 ORM 获取 Key {proxy_key[:8]}... 的上下文信息失败: {e}", exc_info=True)
         return None

async def list_all_context_keys_info(db: AsyncSession, user_key: Optional[str] = None, is_admin: bool = False) -> List[Dict[str, Any]]:
    """
    异步获取存储的上下文的 Key 和元信息列表。
    """
    contexts_info = []
    try:
        stmt = select(DialogContext.proxy_key, DialogContext.contents, DialogContext.last_used_at)
        if is_admin:
            logger.info(f"管理员请求所有上下文信息 (ORM)...")
            stmt = stmt.order_by(DialogContext.last_used_at.desc())
        elif user_key:
            logger.info(f"用户 {user_key[:8]}... 请求其上下文信息 (ORM)...")
            stmt = stmt.where(DialogContext.proxy_key == user_key).order_by(DialogContext.last_used_at.desc())
        else:
            logger.warning(f"非管理员尝试列出上下文但未提供 user_key (ORM)。")
            return []
        result = await db.execute(stmt)
        rows = result.all()
        for row in rows:
            contexts_info.append({
                "proxy_key": row.proxy_key,
                "contents": row.contents, 
                "content_length": len(row.contents) if row.contents else 0,
                "last_used": row.last_used_at.isoformat() if row.last_used_at else None
            })
    except Exception as e:
        log_prefix = f"管理员" if is_admin else f"用户 {user_key[:8]}..." if user_key else "未知用户"
        logger.error(f"{log_prefix} 使用 ORM 列出上下文信息失败: {e}", exc_info=True)
        contexts_info = []
    return contexts_info

def convert_openai_to_gemini_contents(history: List[Dict]) -> List[Dict]:
    """
    (辅助函数) 将 OpenAI 格式转换为 Gemini contents 格式。
    """
    gemini_contents = []
    for message in history:
        openai_role = message.get('role')
        openai_content = message.get('content')
        if openai_role and openai_content is not None:
            if openai_role == 'user': gemini_role = 'user'
            elif openai_role == 'assistant': gemini_role = 'model'
            elif openai_role == 'system': gemini_role = 'user'; logger.debug("OpenAI 'system' role mapped to Gemini 'user'.")
            else: logger.warning(f"Skipping invalid OpenAI role: {openai_role}"); continue
            if isinstance(openai_content, str): gemini_parts = [{'text': openai_content}]
            else: logger.warning(f"Skipping non-string OpenAI content: {type(openai_content)}"); continue
            gemini_contents.append({'role': gemini_role, 'parts': gemini_parts})
        else: logger.warning(f"Skipping invalid OpenAI message (missing role/content): {message}")
    return gemini_contents

async def load_context_as_gemini(proxy_key: str, db: AsyncSession) -> Optional[List[Dict[str, Any]]]:
    """
    异步加载并返回 Gemini 格式的上下文。
    """
    loaded_context = await load_context(proxy_key, db)
    if loaded_context is None: return None
    if isinstance(loaded_context, list): return loaded_context
    else:
        logger.error(f"Loaded context format error (expected list, got {type(loaded_context)}) for Key: {proxy_key[:8]}...")
        await delete_context_for_key(proxy_key, db)
        return None

def convert_gemini_to_storage_format(request_content: Dict, response_content: Dict) -> List[Dict]:
    """
    (辅助函数) 将 Gemini 请求和响应内容转换为存储格式。
    """
    storage_format = []
    user_role, user_parts = request_content.get('role'), request_content.get('parts')
    if user_role == 'user' and user_parts is not None: storage_format.append({'role': 'user', 'parts': user_parts})
    else: logger.warning(f"Invalid Gemini user request content for storage: {request_content}")
    model_role, model_parts = response_content.get('role'), response_content.get('parts')
    if model_role == 'model' and model_parts is not None: storage_format.append({'role': 'model', 'parts': model_parts})
    else: logger.warning(f"Invalid Gemini model response content for storage: {response_content}")
    return storage_format

async def update_ttl(context_key: str, ttl_seconds: int, db: AsyncSession) -> Optional[bool]:
    """
    异步更新 DialogContext 记录的 TTL。
    """
    if not context_key: return False
    try:
        now_dt = datetime.now(timezone.utc)
        values_to_update = {"last_used_at": now_dt}
        if ttl_seconds is not None and ttl_seconds > 0 : values_to_update["ttl_seconds"] = ttl_seconds
        stmt = (sqlalchemy_update(DialogContext).where(DialogContext.proxy_key == context_key).values(**values_to_update))
        result = await db.execute(stmt)
        await db.commit()
        if result.rowcount > 0: logger.info(f"Context TTL info updated for Key {context_key[:8]}..."); return True
        else: logger.warning(f"Attempted to update TTL for Key {context_key[:8]}..., but no record found."); return False
    except Exception as e: logger.error(f"Failed to update TTL for Key {context_key[:8]}...: {e}", exc_info=True); await db.rollback(); return None

async def update_global_ttl(ttl_days: int) -> bool: 
    """
    异步更新全局上下文 TTL。
    """
    try:
        from gap.core.dependencies import get_db_session
        async for db in get_db_session():
            try:
                await set_ttl_days(db, ttl_days) 
                logger.info(f"全局上下文 TTL 已更新为 {ttl_days} 天。")
                return True
            except Exception as e_inner: 
                logger.error(f"set_ttl_days 调用失败: {e_inner}", exc_info=True)
                return False
            finally:
                break 
    except ValueError as ve: logger.error(f"更新全局上下文 TTL failed: {ve}"); return False
    except Exception as e: logger.error(f"更新全局上下文 TTL 时发生意外错误: {e}", exc_info=True); return False

async def get_all_contexts_with_ttl(db: AsyncSession) -> Dict[str, Dict[str, Any]]:
    """
    异步获取所有 DialogContext 记录及其元信息。
    """
    all_contexts_data = {}
    try:
        global_ttl_days = await get_ttl_days(db=db) 
        stmt = select(DialogContext).order_by(DialogContext.last_used_at.desc())
        result = await db.execute(stmt)
        records = result.scalars().all()
        now_utc = datetime.now(timezone.utc)
        for record in records:
            proxy_key, contents_json, last_used_dt, record_ttl_seconds = record.proxy_key, record.contents, record.last_used_at, record.ttl_seconds
            context_summary = "N/A"
            if contents_json:
                try:
                    contents_list = await asyncio.to_thread(json.loads, contents_json)
                    if contents_list and isinstance(contents_list, list) and contents_list:
                        first_message = contents_list[0]
                        if isinstance(first_message, dict) and 'parts' in first_message and isinstance(first_message['parts'], list) and first_message['parts']:
                            first_part = first_message['parts'][0]
                            if isinstance(first_part, dict) and 'text' in first_part:
                                content_text = str(first_part['text']); summary = content_text[:100] + "..." if len(content_text) > 100 else content_text
                        elif isinstance(first_message, dict) and 'content' in first_message:
                            content_text = str(first_message['content']); summary = content_text[:100] + "..." if len(content_text) > 100 else content_text
                        context_summary = summary
                except Exception as e: logger.warning(f"提取 Key {proxy_key[:8]}... 的上下文摘要时出错: {e}")
            ttl_remaining_str = "永不"
            effective_ttl_seconds = record_ttl_seconds if (record_ttl_seconds is not None and record_ttl_seconds > 0) else (global_ttl_days * 86400 if global_ttl_days > 0 else None)
            if last_used_dt and effective_ttl_seconds:
                last_used_aware = last_used_dt if last_used_dt.tzinfo else last_used_dt.replace(tzinfo=timezone.utc)
                expiry_time = last_used_aware + timedelta(seconds=effective_ttl_seconds)
                if expiry_time < now_utc: ttl_remaining_str = "已过期"
                else:
                    remaining_delta = expiry_time - now_utc
                    days = remaining_delta.days
                    hours, rem_secs = divmod(remaining_delta.seconds, 3600)
                    minutes, _ = divmod(rem_secs, 60)
                    if days > 0: ttl_remaining_str = f"{int(days)}天{int(hours)}小时"
                    elif hours > 0: ttl_remaining_str = f"{int(hours)}小时{int(minutes)}分钟"
                    else: ttl_remaining_str = f"{int(minutes)}分钟"
            all_contexts_data[proxy_key] = {
                "ttl": ttl_remaining_str,
                "last_accessed": last_used_dt.strftime("%Y-%m-%d %H:%M:%S %Z") if last_used_dt else "N/A",
                "context_summary": context_summary
            }
        logger.info(f"成功使用 ORM 获取了 {len(all_contexts_data)} 条上下文记录及其 TTL 信息。")
    except Exception as e: logger.error(f"使用 ORM 获取所有上下文及其 TTL 信息 failed: {e}", exc_info=True)
    return all_contexts_data

class ContextStore:
    def __init__(self, storage_mode: str = app_config.CONTEXT_STORAGE_MODE, db_path: str = app_config.CONTEXT_DB_PATH):
        self.storage_mode = storage_mode
        self.db_path = db_path
        if self.storage_mode == "memory":
            self.memory_store: Dict[str, Dict[str, Any]] = {}
            self.memory_lock = asyncio.Lock()
            logger.info("上下文存储已初始化为内存模式。")
        elif self.storage_mode == "database":
            logger.info(f"上下文存储已初始化为数据库模式 (路径: {self.db_path})。")
        else: raise ValueError(f"未知的上下文存储模式: {storage_mode}")

    async def perform_memory_cleanup(self):
        if self.storage_mode != "memory": return
        async with self.memory_lock:
            now_iso, keys_to_delete = datetime.now(timezone.utc).isoformat(), []
            for key, data in self.memory_store.items():
                if data.get("expires_at") and data["expires_at"] < now_iso: keys_to_delete.append(key)
            for key in keys_to_delete: del self.memory_store[key]; logger.info(f"内存上下文 Key '{key}' 已过期清理。")
            if MAX_CONTEXT_RECORDS_MEMORY > 0 and len(self.memory_store) > MAX_CONTEXT_RECORDS_MEMORY:
                num_to_prune = len(self.memory_store) - MAX_CONTEXT_RECORDS_MEMORY
                sorted_keys = sorted(self.memory_store.items(), key=lambda item: item[1].get('last_used', ''))
                for key_to_prune in [item[0] for item in sorted_keys[:num_to_prune]]: del self.memory_store[key_to_prune]
                logger.info(f"ContextStore: 内存超出最大记录数，清理 {num_to_prune} 条旧记录。")

    async def store_context(self, user_id: str, context_key: str, context_value: Any, ttl_seconds: Optional[int] = None):
        if not context_key or context_value is None: logger.warning(f"ContextStore: Key {context_key[:8]}... 保存空上下文跳过。"); return
        now = datetime.now(timezone.utc)
        final_ttl_seconds_for_memory = ttl_seconds
        if final_ttl_seconds_for_memory is None:
            global_ttl_days = app_config.DEFAULT_CONTEXT_TTL_DAYS
            final_ttl_seconds_for_memory = global_ttl_days * 86400 if global_ttl_days > 0 else None
        
        expires_at_iso_for_memory = (now + timedelta(seconds=final_ttl_seconds_for_memory)).isoformat() if final_ttl_seconds_for_memory else None

        if self.storage_mode == "memory":
            async with self.memory_lock:
                self.memory_store[context_key] = {"user_id": user_id, "content": context_value, "last_used": now.isoformat(), "expires_at": expires_at_iso_for_memory, "created_at": now.isoformat()}
                logger.info(f"ContextStore: 上下文 Key {context_key[:8]}... (用户 {user_id}) 存入内存。")
        elif self.storage_mode == "database":
            from gap.core.dependencies import get_db_session
            async for db in get_db_session():
                try:
                    contents_json = await asyncio.to_thread(json.dumps, context_value, ensure_ascii=False)
                    stmt = sqlite_insert(DialogContext).values(proxy_key=context_key, contents=contents_json, last_used_at=now, created_at=now, ttl_seconds=ttl_seconds)
                    update_values = {"contents": stmt.excluded.contents, "last_used_at": stmt.excluded.last_used_at}
                    if ttl_seconds is not None: update_values["ttl_seconds"] = stmt.excluded.ttl_seconds
                    stmt = stmt.on_conflict_do_update(index_elements=[DialogContext.proxy_key], set_=update_values)
                    await db.execute(stmt); await db.commit()
                    logger.info(f"ContextStore: 上下文 Key {context_key[:8]}... (用户 {user_id}) 数据库保存/更新。")
                    break
                except Exception as e: logger.error(f"ContextStore: Key {context_key[:8]}... 数据库保存失败: {e}", exc_info=True); await db.rollback(); break
        else: logger.error(f"ContextStore: 未知存储模式 '{self.storage_mode}'。")

    async def retrieve_context(self, user_id: str, context_key: str) -> Optional[Any]:
        if self.storage_mode == "memory":
            async with self.memory_lock:
                data = self.memory_store.get(context_key)
                if data and (not data.get("expires_at") or data["expires_at"] >= datetime.now(timezone.utc).isoformat()):
                    data["last_used"] = datetime.now(timezone.utc).isoformat(); return data.get("content")
                elif data: del self.memory_store[context_key]; logger.info(f"内存上下文 Key '{context_key}' 过期删除。")
                return None
        elif self.storage_mode == "database":
            from gap.core.dependencies import get_db_session
            async for db in get_db_session():
                try:
                    retrieved_value = await load_context(proxy_key=context_key, db=db)
                    if retrieved_value is not None:
                        update_stmt = sqlalchemy_update(DialogContext).where(DialogContext.proxy_key == context_key).values(last_used_at=datetime.now(timezone.utc))
                        await db.execute(update_stmt); await db.commit()
                    return retrieved_value
                except Exception as e: logger.error(f"ContextStore: 数据库检索 Key '{context_key}' 失败: {e}", exc_info=True); await db.rollback(); return None
                finally: break
        return None

    async def delete_context(self, user_id: str, context_key: str) -> bool:
        if self.storage_mode == "memory":
            async with self.memory_lock:
                if context_key in self.memory_store: del self.memory_store[context_key]; logger.info(f"内存上下文 Key '{context_key}' 删除。"); return True
                return False
        elif self.storage_mode == "database":
            from gap.core.dependencies import get_db_session
            async for db in get_db_session():
                try: return await delete_context_for_key(proxy_key=context_key, db=db)
                except Exception as e: logger.error(f"ContextStore: 数据库删除 Key '{context_key}' 失败: {e}", exc_info=True); await db.rollback(); return False
                finally: break
        return False

    async def get_context_info_for_management(self, user_id: Optional[str] = None, is_admin: bool = False) -> List[Dict[str, Any]]:
        contexts_info = []
        now_utc = datetime.now(timezone.utc)
        
        if self.storage_mode == "memory":
            global_ttl_days = app_config.DEFAULT_CONTEXT_TTL_DAYS
            global_ttl_delta = timedelta(days=global_ttl_days) if global_ttl_days > 0 else None
            async with self.memory_lock:
                for key, data in self.memory_store.items():
                    if not is_admin and data.get("user_id") != user_id:
                        continue
                    summary = "N/A" 
                    if data.get("content") and isinstance(data["content"], list) and data["content"]:
                        summary = str(data["content"][0])[:100]
                    
                    last_used_dt = datetime.fromisoformat(data["last_used"].replace('Z', '+00:00')) if data.get("last_used") else now_utc
                    expires_at_dt = datetime.fromisoformat(data["expires_at"].replace('Z', '+00:00')) if data.get("expires_at") else None
                    ttl_str = "永不"

                    if expires_at_dt:
                        if expires_at_dt < now_utc:
                            ttl_str = "已过期"
                        else: 
                            delta = expires_at_dt - now_utc
                            d = delta.days
                            h, rem = divmod(delta.seconds, 3600)
                            m, _ = divmod(rem, 60)
                            if d > 0:
                                ttl_str = f"{d}天{h}小时"
                            elif h > 0:
                                ttl_str = f"{h}小时{m}分钟"
                            else:
                                ttl_str = f"{m}分钟"
                    elif global_ttl_delta: 
                        effective_expiry = last_used_dt + global_ttl_delta
                        if effective_expiry < now_utc:
                            ttl_str = "已过期 (全局)"
                        else:
                            delta = effective_expiry - now_utc
                            d = delta.days
                            h, rem = divmod(delta.seconds, 3600)
                            m, _ = divmod(rem, 60)
                            if d > 0:
                                ttl_str = f"{d}天{h}小时 (全局)"
                            elif h > 0:
                                ttl_str = f"{h}小时{m}分钟 (全局)"
                            else:
                                ttl_str = f"{m}分钟 (全局)"
                    
                    created_at_iso = data.get("created_at")
                    ttl_seconds_val = "N/A"
                    if expires_at_dt and created_at_iso:
                        try:
                            created_dt = datetime.fromisoformat(created_at_iso.replace('Z', '+00:00'))
                            ttl_seconds_val = (expires_at_dt - created_dt).total_seconds()
                        except ValueError:
                            logger.warning(f"无法解析 created_at 时间戳: {created_at_iso}")


                    contexts_info.append({
                        "id": key,
                        "user_id": data.get("user_id", "N/A"),
                        "context_key": key,
                        "created_at": created_at_iso,
                        "last_accessed_at": data.get("last_used", "N/A"),
                        "ttl_seconds": ttl_seconds_val,
                        "context_value_summary": summary,
                        "ttl_display": ttl_str
                    })
            contexts_info.sort(key=lambda x: x.get('created_at', ''), reverse=True)

        elif self.storage_mode == "database":
            from gap.core.dependencies import get_db_session
            async for db in get_db_session():
                try:
                    return await get_all_contexts_with_ttl(db=db) 
                except Exception as e:
                    logger.error(f"ContextStore: 获取数据库上下文信息 (DialogContext) failed: {e}", exc_info=True)
                    return [] 
                finally: 
                    break
        return contexts_info

    async def delete_context_by_id(self, context_id: int, user_id: Optional[str] = None, is_admin: bool = False) -> bool:
        if self.storage_mode == "memory":
            async with self.memory_lock:
                key_to_delete = str(context_id) 
                if key_to_delete in self.memory_store:
                    if not is_admin and self.memory_store[key_to_delete].get("user_id") != user_id:
                        logger.warning(f"用户 {user_id} 尝试删除不属于自己的内存上下文 ID {key_to_delete}")
                        return False
                    del self.memory_store[key_to_delete]
                    logger.info(f"内存上下文 ID '{key_to_delete}' 已被删除。")
                    return True
                return False
        elif self.storage_mode == "database":
            from gap.core.dependencies import get_db_session
            async for db in get_db_session(): 
                try:
                    stmt = select(DialogContext).where(DialogContext.id == context_id)
                    if not is_admin and user_id:
                        stmt = stmt.where(DialogContext.proxy_key == user_id)
                    result = await db.execute(stmt)
                    record_to_delete = result.scalar_one_or_none()
                    if record_to_delete:
                        await db.delete(record_to_delete); await db.commit()
                        logger.info(f"ContextStore: 数据库上下文 ID '{context_id}' 已删除。")
                        return True
                    logger.warning(f"ContextStore: 删除数据库上下文 ID '{context_id}' 未找到或权限不足。")
                    return False
                except Exception as e: logger.error(f"ContextStore: ID删除数据库上下文失败: {e}", exc_info=True); await db.rollback(); return False
                finally: break
        return False

async def update_ttl(context_key: str, ttl_seconds: int, db: AsyncSession) -> Optional[bool]:
    if not context_key: return False
    try:
        now_dt = datetime.now(timezone.utc)
        values_to_update = {"last_used_at": now_dt}
        if ttl_seconds is not None and ttl_seconds > 0 : values_to_update["ttl_seconds"] = ttl_seconds
        stmt = (sqlalchemy_update(DialogContext).where(DialogContext.proxy_key == context_key).values(**values_to_update))
        result = await db.execute(stmt)
        await db.commit()
        if result.rowcount > 0: logger.info(f"Key {context_key[:8]}... 上下文 TTL 更新成功。"); return True
        else: logger.warning(f"尝试更新 Key {context_key[:8]}... 上下文 TTL，但未找到记录。"); return False
    except Exception as e: logger.error(f"Key {context_key[:8]}... 上下文 TTL 更新失败: {e}", exc_info=True); await db.rollback(); return None

async def update_global_ttl(ttl_days: int) -> bool: 
    try:
        from gap.core.dependencies import get_db_session
        async for db in get_db_session():
            try:
                await set_ttl_days(db, ttl_days) # Pass db to set_ttl_days
                logger.info(f"全局上下文 TTL 已更新为 {ttl_days} 天。")
                return True
            except Exception as e_inner: 
                logger.error(f"set_ttl_days 调用失败: {e_inner}", exc_info=True)
                return False
            finally:
                break 
    except ValueError as ve: logger.error(f"更新全局上下文 TTL failed: {ve}"); return False
    except Exception as e: logger.error(f"更新全局上下文 TTL 时发生意外错误: {e}", exc_info=True); return False

async def get_all_contexts_with_ttl(db: AsyncSession) -> Dict[str, Dict[str, Any]]:
    all_contexts_data = {}
    try:
        global_ttl_days = await get_ttl_days(db=db) # Pass db here
        stmt = select(DialogContext).order_by(DialogContext.last_used_at.desc())
        result = await db.execute(stmt)
        records = result.scalars().all()
        now_utc = datetime.now(timezone.utc)
        for record in records:
            proxy_key, contents_json, last_used_dt, record_ttl_seconds = record.proxy_key, record.contents, record.last_used_at, record.ttl_seconds
            context_summary = "N/A"
            if contents_json:
                try:
                    contents_list = await asyncio.to_thread(json.loads, contents_json)
                    if contents_list and isinstance(contents_list, list) and contents_list:
                        first_message = contents_list[0]
                        if isinstance(first_message, dict) and 'parts' in first_message and isinstance(first_message['parts'], list) and first_message['parts']:
                            first_part = first_message['parts'][0]
                            if isinstance(first_part, dict) and 'text' in first_part:
                                content_text = str(first_part['text']); summary = content_text[:100] + "..." if len(content_text) > 100 else content_text
                        elif isinstance(first_message, dict) and 'content' in first_message:
                            content_text = str(first_message['content']); summary = content_text[:100] + "..." if len(content_text) > 100 else content_text
                        context_summary = summary
                except Exception as e: logger.warning(f"提取 Key {proxy_key[:8]}... 的上下文摘要时出错: {e}")
            ttl_remaining_str = "永不"
            effective_ttl_seconds = record_ttl_seconds if (record_ttl_seconds is not None and record_ttl_seconds > 0) else (global_ttl_days * 86400 if global_ttl_days > 0 else None)
            if last_used_dt and effective_ttl_seconds:
                last_used_aware = last_used_dt if last_used_dt.tzinfo else last_used_dt.replace(tzinfo=timezone.utc)
                expiry_time = last_used_aware + timedelta(seconds=effective_ttl_seconds)
                if expiry_time < now_utc: ttl_remaining_str = "已过期"
                else:
                    remaining_delta = expiry_time - now_utc
                    days = remaining_delta.days
                    hours, rem_secs = divmod(remaining_delta.seconds, 3600)
                    minutes, _ = divmod(rem_secs, 60)
                    if days > 0: ttl_remaining_str = f"{int(days)}天{int(hours)}小时"
                    elif hours > 0: ttl_remaining_str = f"{int(hours)}小时{int(minutes)}分钟"
                    else: ttl_remaining_str = f"{int(minutes)}分钟"
            all_contexts_data[proxy_key] = {
                "ttl": ttl_remaining_str,
                "last_accessed": last_used_dt.strftime("%Y-%m-%d %H:%M:%S %Z") if last_used_dt else "N/A",
                "context_summary": context_summary
            }
        logger.info(f"成功使用 ORM 获取了 {len(all_contexts_data)} 条上下文记录及其 TTL 信息。")
    except Exception as e: logger.error(f"使用 ORM 获取所有上下文及其 TTL 信息 failed: {e}", exc_info=True)
    return all_contexts_data
