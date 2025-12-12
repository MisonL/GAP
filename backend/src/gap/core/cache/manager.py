# -*- coding: utf-8 -*-
"""
缓存管理模块。
负责处理与 Gemini API 原生缓存相关的操作，包括：
- 计算内容的哈希值。
- 将字典格式的内容转换为 Gemini API SDK 的 Content 对象列表。
- 调用 Gemini API 创建缓存。
- 在本地数据库中存储和管理缓存元数据 (CachedContent 模型)。
- 根据内容哈希或用户 ID 和消息查找有效缓存。
- 删除缓存（包括数据库记录和 Gemini API 端的缓存）。
- 清理过期和无效的缓存条目。
"""
import hashlib  # 导入哈希库
import json  # 导入 JSON 库
import logging  # 导入日志库
from datetime import datetime, timedelta, timezone  # 导入日期时间处理，增加 timezone
from typing import Any, Dict, List, Optional  # 导入类型提示

import google.generativeai as genai  # 导入 Gemini SDK
from google.api_core import exceptions as google_exceptions  # 导入 Google API 核心异常
from sqlalchemy import delete, select  # 导入 SQLAlchemy Core API 函数
from sqlalchemy.ext.asyncio import AsyncSession  # 导入 AsyncSession 以备后续统一类型

from gap.core.database.models import (  # 导入数据库模型 CachedContent (新路径)
    CachedContent,
)

# from gap.core.database.utils import get_db # 假设需要获取数据库会话 # 已移除 (新路径)

# 获取名为 'my_logger' 的日志记录器实例
logger = logging.getLogger("my_logger")


class CacheManager:
    """
    缓存管理器类。
    封装了与 Gemini API 缓存和本地数据库缓存记录交互的所有逻辑。
    """

    def _calculate_hash(self, content: dict) -> str:
        """
        (内部辅助方法) 计算给定内容字典的 SHA-256 哈希值。
        为了确保哈希的一致性，字典在序列化为 JSON 字符串之前会按键排序。

        Args:
            content (dict): 需要计算哈希的内容字典。

        Returns:
            str: 计算得到的十六进制哈希字符串。

        Raises:
            TypeError: 如果输入的内容不是字典类型。
        """
        try:
            # 将字典序列化为 JSON 字符串，确保 key 按序排列 (sort_keys=True)
            # ensure_ascii=False 保证非 ASCII 字符（如中文）正确处理
            # 然后将字符串编码为 UTF-8 字节串
            content_str = json.dumps(content, sort_keys=True).encode("utf-8")
            # 计算 SHA-256 哈希值并返回其十六进制表示
            return hashlib.sha256(content_str).hexdigest()
        except Exception as e:
            logger.error(
                f"计算内容哈希时发生错误: {e}", exc_info=True
            )  # 记录序列化或编码错误
            raise  # 重新抛出异常

    def _convert_dict_to_gemini_content(
        self, content_dict: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        (内部辅助方法) 将包含 parts 的字典格式内容转换为 Gemini SDK 0.8.5 版本期望的字典列表格式。
        主要用于将要缓存的内容转换为 Gemini API `create_cached_content` 方法接受的格式。
        支持 text 和 inline_data (假设为 base64 编码) 类型的 part。

        Args:
            content_dict (Dict[str, Any]): 包含 "parts" 键的字典，其值为 part 字典列表。
                                           或者包含 "messages" 键，其值为 OpenAI 格式的消息列表。
                                           例如: {"messages": [{"role": "user", "content": "你好"}]}
                                           或: {"parts": [{"text": "你好"}, {"inline_data": {"mime_type": "image/png", "data": "base64..."}}]}

        Returns:
            List[Dict[str, Any]]: 转换后的 Gemini 内容字典列表。如果转换失败或无有效 parts/messages，则返回空列表。

        Raises:
            TypeError: 如果输入的 content_dict 不是字典类型。
        """

        processed_gemini_contents = []  # 初始化处理后的 Gemini 内容字典列表

        # 优先处理 OpenAI 格式的 messages (更常见)
        if "messages" in content_dict and isinstance(content_dict["messages"], list):
            # 通过 converter.convert_messages 将 OpenAI 风格的消息转换为 Gemini contents
            try:
                from gap.api.models import Message
                from gap.core.context.converter import (  # 延迟导入避免循环
                    convert_messages,
                )

                # 将输入的字典列表安全地构造成 Message 模型列表
                messages_input = []
                for m in content_dict["messages"]:
                    if isinstance(m, Message):
                        messages_input.append(m)
                    elif isinstance(m, dict):
                        try:
                            messages_input.append(Message(**m))
                        except Exception as parse_err:
                            logger.error(
                                f"解析消息字典为 Message 失败: {parse_err}; 原始: {m}"
                            )
                    else:
                        logger.warning(f"跳过非字典/模型的消息项: {type(m)}")

                # 使用 system prompt 提取逻辑；如无需提取，可将 use_system_prompt 设为 False
                convert_result = convert_messages(
                    messages_input, use_system_prompt=True
                )

                # 转换可能返回错误列表或 (contents, system_instruction)
                if isinstance(convert_result, list):
                    # 错误列表
                    logger.error(
                        f"从 messages 转换 Gemini 内容字典失败: {'; '.join(convert_result)}"
                    )
                    return []

                gemini_dicts, _system_instruction = convert_result
                # 校验并追加
                for gemini_dict in gemini_dicts:
                    if isinstance(gemini_dict, dict) and (
                        "role" in gemini_dict and "parts" in gemini_dict
                    ):
                        # 校正 inline_data 的 data: 若为 bytes 则进行 base64 编码
                        for part in gemini_dict.get("parts", []):
                            if "inline_data" in part and isinstance(
                                part["inline_data"], dict
                            ):
                                data_val = part["inline_data"].get("data")
                                if isinstance(data_val, bytes):
                                    logger.warning(
                                        "inline_data 的 data 字段是 bytes，期望是 base64 字符串。将尝试编码。"
                                    )
                                    import base64

                                    try:
                                        part["inline_data"]["data"] = base64.b64encode(
                                            data_val
                                        ).decode("utf-8")
                                    except Exception as enc_err:
                                        logger.error(
                                            f"Base64 编码 inline_data 时出错: {enc_err}"
                                        )
                                        # 若编码失败，跳过该 part
                        processed_gemini_contents.append(gemini_dict)
                    else:
                        logger.warning(
                            f"从 messages 转换的条目缺少 role/parts 或不是字典: {gemini_dict}"
                        )

                if processed_gemini_contents:
                    return processed_gemini_contents
            except Exception as e:
                logger.error(
                    f"从 messages 转换 Gemini 内容字典时出错: {e}", exc_info=True
                )
                return []  # 转换出错返回空列表

        # 如果没有 messages 或转换失败，尝试处理 parts 格式 (兼容旧逻辑)
        # 这种情况下，content_dict 本身可能就是一个 Gemini Content 字典，或者只包含 parts
        # 我们需要确保它符合 {"role": "...", "parts": [...]} 的结构

        raw_parts_data = content_dict.get("parts")
        current_role = content_dict.get(
            "role", "model"
        )  # 如果没有 role，默认为 'model'

        if raw_parts_data and isinstance(raw_parts_data, list):
            processed_parts = []
            for part_data in raw_parts_data:
                if not isinstance(part_data, dict):
                    logger.warning(f"Part 数据不是字典格式，已跳过: {part_data}")
                    continue

                if "text" in part_data and part_data["text"] is not None:
                    processed_parts.append({"text": part_data["text"]})
                elif "inline_data" in part_data and isinstance(
                    part_data["inline_data"], dict
                ):
                    inline_data_dict = part_data["inline_data"]
                    if "mime_type" in inline_data_dict and "data" in inline_data_dict:
                        # 假设 data 已经是 base64 编码的字符串
                        # 如果 data 是 bytes，需要先 base64 encode
                        data_value = inline_data_dict["data"]
                        if isinstance(data_value, bytes):
                            logger.warning(
                                "inline_data 的 data 字段是 bytes，期望是 base64 字符串。将尝试编码。"
                            )
                            import base64

                            try:
                                data_value = base64.b64encode(data_value).decode(
                                    "utf-8"
                                )
                            except Exception as enc_err:
                                logger.error(
                                    f"Base64 编码 inline_data 时出错: {enc_err}"
                                )
                                continue  # 跳过这个 part

                        processed_parts.append(
                            {
                                "inline_data": {
                                    "mime_type": inline_data_dict["mime_type"],
                                    "data": data_value,
                                }
                            }
                        )
                    else:
                        logger.warning(
                            f"inline_data 缺少 mime_type 或 data: {part_data}"
                        )
                # TODO: 支持其他 part 类型如 functionCall, functionResponse, fileData (如果需要)

            if processed_parts:
                processed_gemini_contents.append(
                    {"role": current_role, "parts": processed_parts}
                )
                return processed_gemini_contents

        logger.warning(
            f"无法从字典内容转换出有效的 Gemini 内容字典列表: {content_dict}"
        )
        return []  # 如果没有有效的 parts 或 messages，返回空列表

    # 注意：以下方法的 db 参数类型提示与实际使用的数据库操作库可能不一致。
    # create_cache, get_cache, find_cache 使用了同步 Session 的方法 (db.query, db.commit)
    # cleanup_expired_caches, cleanup_invalid_caches 使用了 aiosqlite 的异步连接和游标
    # 建议统一使用 AsyncSession。

    async def create_cache(
        self, db: AsyncSession, user_id: str, api_key_id: int, content: dict, ttl: int
    ) -> Optional[int]:
        """异步创建缓存条目。

        流程：
        1. 计算内容哈希并检查数据库中是否已有未过期缓存；如有则直接返回其 ID。
        2. 无缓存则调用 Gemini API 创建缓存。
        3. 将返回的缓存元数据写入数据库。如数据库写入失败，则尝试删除刚创建的远端缓存。
        """
        # 1) 计算内容哈希
        try:
            content_hash = self._calculate_hash(content)
            logger.info(
                "尝试为内容哈希 %s 创建缓存 (用户: %s, Key ID: %s)",
                content_hash[:8] + "...",
                user_id,
                api_key_id,
            )
        except Exception as hash_err:  # pragma: no cover - 极端异常路径
            logger.error("创建缓存时计算哈希失败: %s", hash_err, exc_info=True)
            return None

        # 2) 检查数据库中是否已有未过期缓存
        try:
            # 使用 timezone-aware 的 UTC 时间戳，避免 datetime.utcnow() 弃用警告
            now_ts = datetime.now(timezone.utc).timestamp()
            stmt_check = (
                select(CachedContent)
                .where(
                    CachedContent.content_id == content_hash,
                    CachedContent.expiration_timestamp > now_ts,
                )
                .limit(1)
            )
            result_check = await db.execute(stmt_check)
            existing_cache = result_check.scalar_one_or_none()

            if existing_cache is not None:
                logger.info(
                    "数据库中已存在有效缓存 (ID: %s)，跳过 Gemini API 创建。",
                    existing_cache.id,
                )
                existing_id = existing_cache.id
                # 运行时这里应为 int，但在类型检查时可能被视为 Column[int] | None
                return int(existing_id) if existing_id is not None else None
        except Exception as db_check_err:  # pragma: no cover - 配置/环境异常
            logger.error("检查数据库现有缓存时出错: %s", db_check_err, exc_info=True)
            return None

        # 3) 数据库中不存在有效缓存，调用 Gemini API 创建
        gemini_cached_content = None
        try:
            # 3.1 将内容字典转换为 Gemini API 需要的格式
            gemini_content_list = self._convert_dict_to_gemini_content(content)
            if not gemini_content_list:
                logger.warning(
                    "转换内容为 Gemini Content 失败，无法创建 Gemini API 缓存。内容: %s",
                    content,
                )
                return None

            # 3.2 调用 Gemini SDK 创建缓存
            logger.debug(
                "调用 Gemini API 创建缓存，内容: %s, TTL: %s", gemini_content_list, ttl
            )
            gemini_cached_content = await genai.create_cached_content(  # type: ignore[attr-defined]
                contents=gemini_content_list,
                ttl=timedelta(seconds=ttl),
            )
            logger.info(
                "成功创建 Gemini API 缓存: %s (过期时间: %s)",
                getattr(gemini_cached_content, "name", "<unknown>"),
                getattr(gemini_cached_content, "expire_time", "<unknown>"),
            )

            # 3.3 写入数据库
            try:
                expire_time_dt = getattr(gemini_cached_content, "expire_time", None)
                if not isinstance(expire_time_dt, datetime):
                    try:
                        expire_time_dt = expire_time_dt.replace(tzinfo=timezone.utc)  # type: ignore[union-attr]
                    except Exception:
                        logger.error(
                            "无法处理 Gemini API 返回的过期时间类型: %s",
                            type(expire_time_dt),
                        )
                        expire_time_dt = datetime.now(timezone.utc) + timedelta(seconds=ttl)

                # 使用 timezone-aware UTC 时间戳
                now_ts = datetime.now(timezone.utc).timestamp()
                expire_ts = now_ts + ttl

                cached_content_db = CachedContent(
                    gemini_cache_id=getattr(gemini_cached_content, "name", None),
                    content_id=content_hash,
                    user_id=user_id,
                    key_id=api_key_id,
                    expiration_timestamp=expire_ts,
                    content=json.dumps(content),
                    creation_timestamp=now_ts,
                )
                db.add(cached_content_db)
                await db.commit()
                await db.refresh(cached_content_db)

                logger.info("成功创建数据库缓存条目 (ID: %s)", cached_content_db.id)
                cached_id = cached_content_db.id
                return int(cached_id) if cached_id is not None else None
            except Exception as db_save_err:  # pragma: no cover - 罕见持久化错误
                logger.error(
                    "将 Gemini 缓存信息存入数据库时出错: %s", db_save_err, exc_info=True
                )
                await db.rollback()

                # 尝试删除刚刚在 Gemini API 创建的缓存，避免产生孤立远端缓存
                try:
                    cache_name = getattr(gemini_cached_content, "name", None)
                    if cache_name:
                        logger.warning(
                            "因数据库保存失败，尝试删除 Gemini API 缓存: %s",
                            cache_name,
                        )
                        await genai.delete_cached_content(  # type: ignore[attr-defined]
                            name=cache_name
                        )
                        logger.info(
                            "已删除因数据库保存失败而创建的 Gemini API 缓存: %s",
                            cache_name,
                        )
                except Exception as delete_err:
                    logger.error(
                        "尝试删除 Gemini API 缓存失败: %s", delete_err, exc_info=True
                    )

                return None

        except google_exceptions.AlreadyExists as e:
            logger.warning(
                "尝试创建 Gemini API 缓存时发现已存在 (哈希: %s): %s",
                content_hash[:8] + "...",
                e,
            )
            try:
                stmt_find = (
                    select(CachedContent)
                    .where(CachedContent.content_id == content_hash)
                    .limit(1)
                )
                result_find = await db.execute(stmt_find)
                existing_db_cache = result_find.scalar_one_or_none()
                if existing_db_cache is not None:
                    logger.info(
                        "从数据库中找到了与已存在 Gemini 缓存对应的记录 (ID: %s)",
                        existing_db_cache.id,
                    )
                    existing_db_id = existing_db_cache.id
                    return int(existing_db_id) if existing_db_id is not None else None
                logger.error(
                    "Gemini API 报告缓存已存在，但在数据库中未找到对应记录 (哈希: %s)...",
                    content_hash[:8] + "...",
                )
                return None
            except Exception as db_find_err:  # pragma: no cover - 罕见错误路径
                logger.error(
                    "尝试查找已存在的 Gemini 缓存对应数据库记录时出错: %s",
                    db_find_err,
                    exc_info=True,
                )
                return None
        except google_exceptions.GoogleAPIError as e:
            logger.error("调用 Gemini API 创建缓存失败: %s", e, exc_info=True)
            return None
        except Exception as e:  # pragma: no cover - 兜底保护
            logger.error("创建缓存过程中发生意外错误: %s", e, exc_info=True)
            return None

    async def get_cache(
        self, db: AsyncSession, content_hash: str
    ) -> Optional[Dict[str, Any]]:
        """
        (异步方法) 根据内容哈希值从数据库获取缓存信息。
        """
        logger.info(f"尝试获取内容哈希 {content_hash[:8]}... 的缓存 (异步)")
        try:
            # 构建异步查询语句
            stmt = (
                select(CachedContent)
                .where(CachedContent.content_id == content_hash)
                .limit(1)
            )
            result = await db.execute(stmt)
            cached_content = result.scalar_one_or_none()

            if cached_content:
                # 使用 timezone-aware UTC 时间戳
                now_ts = datetime.now(timezone.utc).timestamp()
                expiration_ts = float(cached_content.expiration_timestamp)
                if now_ts < expiration_ts:
                    logger.info(
                        "找到有效缓存 (ID: %s, Gemini ID: %s...) (异步)",
                        cached_content.id,
                        str(cached_content.gemini_cache_id)[:8],
                    )

                    try:
                        original_content = json.loads(str(cached_content.content))
                    except json.JSONDecodeError:
                        logger.error(
                            f"无法解析数据库中缓存 ID {cached_content.id} 的 content 字段。"
                        )
                        original_content = None

                    return {
                        "gemini_cache_id": cached_content.gemini_cache_id,
                        "content": original_content,
                    }
                else:
                    logger.info(
                        f"找到过期缓存 (ID: {cached_content.id})，视为未命中 (异步)。"
                    )
                    return None
            else:
                logger.info(f"未找到内容哈希 {content_hash[:8]}... 的缓存 (异步)。")
                return None
        except Exception as e:
            logger.error(
                f"获取缓存 (哈希: {content_hash[:8]}...) 时出错 (异步): {e}",
                exc_info=True,
            )
            await db.rollback()  # 发生错误时回滚
            return None

    async def find_cache(
        self, db: AsyncSession, user_id: str, messages: List[Dict[str, Any]]
    ) -> Optional[str]:
        """
        (异步方法) 根据用户 ID 和消息内容异步查找有效的缓存。
        注意：此方法使用了异步 SQLAlchemy Session。

        Args:
            db (AsyncSession): SQLAlchemy 异步数据库会话。
            user_id (str): 要查找缓存的用户 ID。
            messages (List[Dict[str, Any]]): OpenAI 格式的消息列表，用于计算哈希。

        Returns:
            Optional[str]: 如果找到有效缓存，返回其 Gemini 缓存 ID (gemini_cache_id)；否则返回 None。
        """
        # 1. 构造用于计算哈希的内容字典 (与 create_cache 保持一致)
        # 假设缓存是基于消息列表。如果需要区分模型，应将模型名称加入 content_to_hash
        content_to_hash = {"messages": messages}
        try:
            content_hash = self._calculate_hash(content_to_hash)  # 计算哈希
        except TypeError as e:
            logger.error(f"查找缓存时计算哈希失败: {e}")  # 记录错误
            return None  # 计算哈希失败，无法查找

        logger.info(
            f"尝试为用户 {user_id} 查找内容哈希 {content_hash[:8]}... 的有效缓存"
        )  # 记录日志

        try:
            # 2. 构建异步查询语句
            # 使用 timezone-aware UTC 时间戳
            now_ts = datetime.now(timezone.utc).timestamp()
            stmt = (
                select(CachedContent)
                .where(
                    CachedContent.user_id == user_id,
                    CachedContent.content_id == content_hash,
                    CachedContent.expiration_timestamp > now_ts,
                )
                .limit(1)
            )
            result = await db.execute(stmt)
            cached_content = result.scalar_one_or_none()

            if cached_content:
                logger.info(
                    f"为用户 {user_id} 找到有效缓存 (ID: {cached_content.id}, Gemini ID: {str(cached_content.gemini_cache_id)[:8]}...)"
                )
                # 显式转换为 str，避免 SQLAlchemy Column 类型在类型检查中产生干扰
                return str(cached_content.gemini_cache_id)
            else:  # 未找到匹配的有效缓存记录
                logger.info(
                    f"未找到用户 {user_id} 内容哈希 {content_hash[:8]}... 的有效缓存。"
                )  # 记录日志
                return None  # 返回 None
        except Exception as e:  # 捕获数据库查询或更新异常
            logger.error(
                f"查找缓存 (用户: {user_id}, 哈希: {content_hash[:8]}...) 时出错: {e}",
                exc_info=True,
            )  # 记录错误
            await db.rollback()  # 回滚可能的事务
            return None  # 返回 None

    async def delete_cache(self, db: AsyncSession, cache_id: int) -> bool:
        """
        (异步方法) 删除指定 ID 的缓存条目（包括数据库记录和 Gemini API 端的缓存）。
        注意：此方法使用了异步 SQLAlchemy Session。

        Args:
            db (AsyncSession): SQLAlchemy 异步数据库会话。
            cache_id (int): 要删除的数据库缓存条目的 ID。

        Returns:
            bool: 如果成功删除数据库条目（无论 Gemini API 删除是否成功或缓存是否存在），返回 True；
                  如果数据库条目未找到或删除过程中发生数据库错误，返回 False。
        """
        logger.info(f"尝试删除数据库缓存条目 (ID: {cache_id})")  # 记录日志
        try:
            # 1. 根据数据库 ID 查询缓存条目
            stmt_select = select(CachedContent).where(CachedContent.id == cache_id)
            result_select = await db.execute(stmt_select)
            cached_content = result_select.scalar_one_or_none()

            if cached_content:  # 如果找到了数据库记录
                gemini_cache_id = (
                    cached_content.gemini_cache_id
                )  # 获取对应的 Gemini 缓存 ID
                logger.info(
                    f"找到数据库缓存条目 (ID: {cache_id}, Gemini ID: {gemini_cache_id[:8]}...)，准备删除。"
                )  # 记录日志

                # 2. 尝试删除 Gemini API 端的缓存
                try:
                    # 调用 Gemini SDK 的异步删除方法
                    logger.debug(f"尝试删除 Gemini API 缓存: {gemini_cache_id}")
                    await genai.delete_cached_content(name=gemini_cache_id)  # type: ignore[attr-defined]
                    logger.info(
                        f"成功删除 Gemini API 缓存: {gemini_cache_id}"
                    )  # 记录成功日志
                except google_exceptions.NotFound:  # 如果 Gemini API 报告未找到
                    logger.warning(
                        f"尝试删除 Gemini API 缓存 {gemini_cache_id} 时发现不存在。"
                    )  # 记录警告，可能已被删除
                except (
                    google_exceptions.GoogleAPIError
                ) as e:  # 捕获其他 Google API 错误
                    logger.error(
                        f"调用 Gemini API 删除缓存 {gemini_cache_id} 失败: {e}",
                        exc_info=True,
                    )  # 记录错误
                    # 即使 Gemini API 删除失败，仍然继续删除数据库记录
                except Exception as e:  # 捕获其他意外错误
                    logger.error(
                        f"删除 Gemini API 缓存 {gemini_cache_id} 过程中发生意外错误: {e}",
                        exc_info=True,
                    )  # 记录错误
                    # 仍然继续删除数据库记录

                # 3. 删除数据库中的缓存条目
                stmt_delete = delete(CachedContent).where(CachedContent.id == cache_id)
                await db.execute(stmt_delete)  # 执行删除
                await db.commit()  # 提交事务
                logger.info(f"成功删除数据库缓存条目 (ID: {cache_id})")  # 记录成功日志
                return True  # 返回 True 表示数据库删除成功
            else:  # 如果未找到数据库记录
                logger.warning(
                    f"未找到数据库缓存条目 (ID: {cache_id})，无需删除。"
                )  # 记录警告
                return False  # 返回 False 表示未找到记录
        except Exception as e:  # 捕获数据库操作异常
            logger.error(
                f"删除缓存 (ID: {cache_id}) 时发生数据库错误: {e}", exc_info=True
            )  # 记录错误
            await db.rollback()  # 回滚事务
            return False  # 返回 False 表示删除失败

    async def cleanup_expired_caches(self, db: AsyncSession):
        """
        (异步方法) 清理数据库中所有已过期的缓存条目。
        注意：此方法目前仅删除数据库记录，未主动删除对应的 Gemini API 缓存。
              Gemini API 的缓存有自己的 TTL，会自动过期。如果需要强制删除，应调用 delete_cache。
        此方法使用了异步 SQLAlchemy Session。

        Args:
            db (AsyncSession): SQLAlchemy 异步数据库会话。
        """
        logger.info("开始清理数据库中过期的缓存条目...")  # 记录开始日志
        cleaned_count = 0  # 初始化清理计数器
        try:
            # 获取当前 UTC 时间戳（timezone-aware）
            now_ts = datetime.now(timezone.utc).timestamp()
            # 查找所有过期记录
            stmt_select = select(CachedContent.id, CachedContent.gemini_cache_id).where(
                CachedContent.expiration_timestamp <= now_ts
            )
            result_select = await db.execute(stmt_select)
            expired_caches = result_select.all()

            if expired_caches:
                expired_ids = [cache.id for cache in expired_caches]
                logger.info(
                    f"发现 {len(expired_ids)} 个过期的数据库缓存条目，准备删除..."
                )
                stmt_delete = delete(CachedContent).where(
                    CachedContent.id.in_(expired_ids)
                )
                result_delete = await db.execute(stmt_delete)
                await db.commit()
                cleaned_count = result_delete.rowcount
                logger.info(f"成功清理了 {cleaned_count} 个过期的数据库缓存条目。")
                # 记录被删除的 Gemini ID (可选，用于调试)
                # for cache in expired_caches:
                #     logger.debug(f"  - 已删除数据库记录，对应的 Gemini ID: {cache.gemini_cache_id[:8]}...")
            else:  # 如果没有找到过期缓存
                logger.info("未发现需要清理的过期数据库缓存条目。")  # 记录日志

        except Exception as e:  # 捕获数据库操作异常
            logger.error(f"清理过期缓存时出错: {e}", exc_info=True)  # 记录错误
            await db.rollback()  # 回滚事务

    async def cleanup_invalid_caches(self, db: AsyncSession):  # 添加 db 参数
        """
        (异步方法) 清理数据库中无效的缓存条目（即在 Gemini API 端已不存在的缓存）。
        遍历数据库中的所有缓存条目，尝试调用 Gemini API 获取对应的缓存对象。
        如果 Gemini API 返回 NotFound 错误，则从数据库中删除该条目。
        注意：此方法使用了异步 SQLAlchemy Session。

        Args:
            db (AsyncSession): SQLAlchemy 异步数据库会话。
        """
        logger.info(
            "开始清理无效的数据库缓存条目 (与 Gemini API 同步)..."
        )  # 记录开始日志
        cleaned_count = 0  # 初始化清理计数器
        invalid_ids_to_delete = []  # 存储需要删除的数据库 ID

        try:
            # 1. 获取数据库中所有的缓存记录 (ID 和 Gemini ID)
            stmt_select = select(CachedContent.id, CachedContent.gemini_cache_id)
            result_select = await db.execute(stmt_select)
            all_db_caches = result_select.all()
            logger.debug(
                f"从数据库获取了 {len(all_db_caches)} 条缓存记录进行检查。"
            )  # 记录日志

            # 2. 遍历数据库记录，检查对应的 Gemini API 缓存是否存在
            for db_cache in all_db_caches:
                db_id = db_cache.id
                gemini_cache_id = db_cache.gemini_cache_id
                if not gemini_cache_id:  # 跳过没有 Gemini ID 的记录
                    logger.debug(
                        f"数据库缓存条目 (ID: {db_id}) 没有 Gemini Cache ID，跳过检查。"
                    )
                    continue
                logger.debug(
                    f"检查数据库缓存条目 (ID: {db_id}, Gemini ID: {gemini_cache_id[:8]}...)"
                )  # 记录日志
                try:
                    # 尝试调用 Gemini API 获取缓存对象
                    await genai.get_cached_content(name=gemini_cache_id)  # type: ignore[attr-defined]
                    # 如果没有抛出异常，说明 Gemini API 缓存存在
                    logger.debug(f"Gemini API 缓存 {gemini_cache_id[:8]}... 存在。")
                except google_exceptions.NotFound:
                    # 如果 Gemini API 返回 NotFound，说明数据库中的记录是无效的
                    logger.warning(
                        f"Gemini API 缓存 {gemini_cache_id[:8]}... 不存在，标记数据库条目 (ID: {db_id}) 为待删除。"
                    )  # 记录警告
                    invalid_ids_to_delete.append(
                        db_id
                    )  # 将无效记录的 ID 加入待删除列表
                except google_exceptions.GoogleAPIError as e:
                    # 捕获其他 Google API 错误，记录错误但不删除，避免误删
                    logger.error(
                        f"检查 Gemini API 缓存 {gemini_cache_id[:8]}... 时发生 Google API 错误: {e}",
                        exc_info=True,
                    )  # 记录错误
                except Exception as e:
                    # 捕获其他意外异常
                    logger.error(
                        f"检查 Gemini API 缓存 {gemini_cache_id[:8]}... 时发生意外错误: {e}",
                        exc_info=True,
                    )  # 记录错误

            # 3. 如果找到无效记录，执行批量删除
            if invalid_ids_to_delete:
                logger.info(
                    f"准备从数据库删除 {len(invalid_ids_to_delete)} 个无效缓存条目..."
                )  # 记录日志
                stmt_delete = delete(CachedContent).where(
                    CachedContent.id.in_(invalid_ids_to_delete)
                )  # 构建批量删除语句
                result_delete = await db.execute(stmt_delete)  # 执行删除
                await db.commit()  # 提交事务
                cleaned_count = result_delete.rowcount  # 获取实际删除的行数
                logger.info(
                    f"成功清理了 {cleaned_count} 个无效的数据库缓存条目。"
                )  # 记录成功日志
            else:
                logger.info("未发现需要清理的无效数据库缓存条目。")  # 记录日志

        except Exception as e:  # 捕获数据库操作或循环中的异常
            logger.error(f"清理无效缓存时出错: {e}", exc_info=True)  # 记录错误
            await db.rollback()  # 回滚事务
