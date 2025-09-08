# -*- coding: utf-8 -*-
"""
处理数据库中 'settings' 表的交互，用于存储和检索应用程序的配置项。
主要用于管理上下文 TTL (Time-To-Live) 等设置。
"""
import logging # 导入日志模块
import asyncio # 导入 asyncio 库
from typing import Optional # 导入 Optional 类型提示
from sqlalchemy.ext.asyncio import AsyncSession # 导入 SQLAlchemy 异步会话
from sqlalchemy import text, select, update, insert # 导入 SQLAlchemy 相关函数和类
from sqlalchemy.exc import SQLAlchemyError # 导入 SQLAlchemy 异常
import sqlalchemy # 导入 sqlalchemy 以捕获 IntegrityError
from gap import config # 导入应用配置

from gap.core.database.models import Setting # 导入 Setting 模型

logger = logging.getLogger('my_logger') # 获取日志记录器实例

# --- 设置管理函数 ---
async def get_setting(db: AsyncSession, key: str, default: Optional[str] = None) -> Optional[str]:
    logger.info(f"get_setting: Received db type: {type(db)}, db repr: {repr(db)}") # 添加日志
    """
    从数据库的 'settings' 表中异步获取指定键 (key) 的设置值。
    使用传入的 SQLAlchemy AsyncSession。
    """
    try:
        stmt = select(Setting.value).where(Setting.key == key)
        result = await db.execute(stmt)
        value = result.scalar_one_or_none()
        return value if value is not None else default
    except SQLAlchemyError as e:
        logger.error(f"获取设置 '{key}' 失败: {e}", exc_info=True)
        return default
    except Exception as e:
        logger.error(f"获取设置 '{key}' 时发生意外错误: {e}", exc_info=True)
        return default

async def set_setting(db: AsyncSession, key: str, value: str):
    """
    在数据库的 'settings' 表中异步设置或更新指定键 (key) 的值。
    使用传入的 SQLAlchemy AsyncSession。
    """
    try:
        stmt_update = (
            update(Setting)
            .where(Setting.key == key)
            .values(value=value)
            .execution_options(synchronize_session=False)
        )
        result = await db.execute(stmt_update)

        if result.rowcount == 0:
            stmt_insert = insert(Setting).values(key=key, value=value)
            try:
                 await db.execute(stmt_insert)
                 logger.info(f"设置 '{key}' 不存在，已插入新值 '{value}'")
            except sqlalchemy.exc.IntegrityError:
                 logger.warning(f"尝试插入设置 '{key}' 时发生冲突，可能已被并发插入。")
                 pass 
        else:
            logger.info(f"设置 '{key}' 已更新为 '{value}'")

        await db.commit()
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(f"设置 '{key}' 失败: {e}", exc_info=True)
    except Exception as e:
        await db.rollback()
        logger.error(f"设置 '{key}' 时发生意外错误: {e}", exc_info=True)

async def get_ttl_days(db: AsyncSession) -> int:
    """
    从数据库异步获取上下文 TTL (Time-To-Live) 的天数设置。
    使用传入的 SQLAlchemy AsyncSession。
    """
    value_str = await get_setting(db, 'context_ttl_days', str(config.DEFAULT_CONTEXT_TTL_DAYS))
    try:
        val = int(value_str)
        return max(0, val) 
    except (ValueError, TypeError): 
        logger.warning(f"无效的 TTL 设置值 '{value_str}'，将使用默认值 {config.DEFAULT_CONTEXT_TTL_DAYS}")
        return config.DEFAULT_CONTEXT_TTL_DAYS

async def set_ttl_days(db: AsyncSession, days: int):
    """
    在数据库中异步设置上下文 TTL (Time-To-Live) 的天数。
    使用传入的 SQLAlchemy AsyncSession。
    """
    if not isinstance(days, int) or days < 0:
        logger.error(f"尝试设置无效的 TTL 天数: {days}")
        raise ValueError("TTL 天数必须是非负整数")
    await set_setting(db, 'context_ttl_days', str(days))
