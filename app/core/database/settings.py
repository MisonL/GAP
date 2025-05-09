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
from app import config # 导入应用配置

# 导入共享的数据库连接函数、数据库路径和默认上下文 TTL 配置
# 注意：get_db_connection 和 DATABASE_PATH 可能不再需要直接在此处使用
# from app.core.database.utils import DEFAULT_CONTEXT_TTL_DAYS # 从 utils 模块导入默认 TTL (改为从 config 导入)
from app.core.database.models import Setting # 导入 Setting 模型

logger = logging.getLogger('my_logger') # 获取日志记录器实例

# --- 设置管理函数 ---
async def get_setting(db: AsyncSession, key: str, default: Optional[str] = None) -> Optional[str]:
    """
    从数据库的 'settings' 表中异步获取指定键 (key) 的设置值。
    使用传入的 SQLAlchemy AsyncSession。

    Args:
        db (AsyncSession): SQLAlchemy 异步数据库会话。
        key (str): 要获取的设置项的键名。
        default (Optional[str], optional): 如果在数据库中找不到对应的键，
                                           或者在获取过程中发生错误时，返回的默认值。
                                           默认为 None。

    Returns:
        Optional[str]: 如果找到设置项，则返回其字符串形式的值；否则返回指定的默认值。
    """
    try:
        # 使用 SQLAlchemy Core API 构建查询
        stmt = select(Setting.value).where(Setting.key == key)
        # 执行查询
        result = await db.execute(stmt)
        # 获取单个标量结果 (value 列的值)
        value = result.scalar_one_or_none()
        # 如果找到了值，返回它；否则返回默认值
        return value if value is not None else default
    except SQLAlchemyError as e: # 捕获 SQLAlchemy 可能抛出的数据库错误
        # 记录获取设置失败的错误日志
        logger.error(f"获取设置 '{key}' 失败: {e}", exc_info=True)
        return default # 发生错误时返回默认值
    except Exception as e: # 捕获其他可能的意外错误
        logger.error(f"获取设置 '{key}' 时发生意外错误: {e}", exc_info=True)
        return default

async def set_setting(db: AsyncSession, key: str, value: str):
    """
    在数据库的 'settings' 表中异步设置或更新指定键 (key) 的值。
    如果键已存在，则更新其值；如果不存在，则插入新行。
    使用传入的 SQLAlchemy AsyncSession。

    Args:
        db (AsyncSession): SQLAlchemy 异步数据库会话。
        key (str): 要设置或更新的设置项的键名。
        value (str): 要设置的值（将作为字符串存储）。
    """
    try:
        # 尝试更新现有记录
        stmt_update = (
            update(Setting)
            .where(Setting.key == key)
            .values(value=value)
            .execution_options(synchronize_session=False) # 通常在仅更新时不需要同步
        )
        result = await db.execute(stmt_update)

        # 如果没有行被更新 (说明 key 不存在)
        if result.rowcount == 0:
            # 尝试插入新记录
            # 使用 merge 可能更简洁，但这里显式处理插入
            stmt_insert = insert(Setting).values(key=key, value=value)
            # 添加 on_conflict_do_update (SQLite 特定) 以处理并发插入的可能性
            # 或者依赖于之前的更新尝试失败
            # 这里简化为直接插入，假设并发冲突概率低或由外层逻辑处理
            try:
                 await db.execute(stmt_insert)
                 logger.info(f"设置 '{key}' 不存在，已插入新值 '{value}'") # 记录插入日志
            except sqlalchemy.exc.IntegrityError:
                 # 如果插入时发生完整性错误（例如并发插入导致 key 已存在），
                 # 再次尝试更新可能更健壮，但这里简化处理，仅记录错误
                 logger.warning(f"尝试插入设置 '{key}' 时发生冲突，可能已被并发插入。")
                 # 可以选择再次尝试更新或忽略
                 pass # 忽略冲突，假设值已被其他进程设置

        else:
            logger.info(f"设置 '{key}' 已更新为 '{value}'") # 记录更新日志

        # 提交事务
        await db.commit()
    except SQLAlchemyError as e: # 捕获 SQLAlchemy 数据库错误
        await db.rollback() # 回滚事务
        logger.error(f"设置 '{key}' 失败: {e}", exc_info=True) # 记录错误日志
    except Exception as e: # 捕获其他可能的意外错误
        await db.rollback() # 回滚事务
        logger.error(f"设置 '{key}' 时发生意外错误: {e}", exc_info=True) # 记录错误日志


async def get_ttl_days(db: AsyncSession) -> int: # 修改参数类型为 AsyncSession
    """
    从数据库异步获取上下文 TTL (Time-To-Live) 的天数设置。
    此函数会处理从数据库获取的值（字符串）到整数的转换，
    并处理无效值或获取失败的情况，确保返回一个有效的非负整数。

    Args:
        db (AsyncSession): SQLAlchemy 异步数据库会话。

    Returns:
        int: 上下文的 TTL 天数。如果数据库中没有设置、设置无效或获取失败，
             则返回在 `app.config` 中定义的 `DEFAULT_CONTEXT_TTL_DAYS`。
             返回值保证是一个非负整数。
    """
    # 调用 get_setting 获取 'context_ttl_days' 的值，如果不存在则使用默认值的字符串形式
    # 注意：get_setting 现在需要 db 参数
    value_str = await get_setting(db, 'context_ttl_days', str(config.DEFAULT_CONTEXT_TTL_DAYS)) # 使用 config.
    try:
        # 尝试将从数据库获取的字符串值转换为整数
        val = int(value_str)
        # 确保返回的 TTL 值不小于 0
        return max(0, val) # 返回转换后的整数值，或者 0（如果转换结果为负数）
    except (ValueError, TypeError): # 捕获转换过程中可能发生的 ValueError 或 TypeError
        # 如果转换失败（例如，数据库中的值不是有效的数字字符串）
        # 记录警告日志，并返回默认的 TTL 天数
        logger.warning(f"无效的 TTL 设置值 '{value_str}'，将使用默认值 {config.DEFAULT_CONTEXT_TTL_DAYS}") # 使用 config.
        return config.DEFAULT_CONTEXT_TTL_DAYS # 返回在 config 中定义的默认 TTL 值


async def set_ttl_days(db: AsyncSession, days: int): # 修改参数类型为 AsyncSession
    """
    在数据库中异步设置上下文 TTL (Time-To-Live) 的天数。

    Args:
        db (AsyncSession): SQLAlchemy 异步数据库会话。
        days (int): 要设置的 TTL 天数。必须是一个非负整数。

    Raises:
        ValueError: 如果提供的 `days` 参数不是一个非负整数。
    """
    # 验证输入参数是否为非负整数
    if not isinstance(days, int) or days < 0:
        # 如果输入无效，记录错误并抛出 ValueError
        logger.error(f"尝试设置无效的 TTL 天数: {days}")
        raise ValueError("TTL 天数必须是非负整数") # 明确告知调用者错误原因
    # 调用 set_setting 将有效的 TTL 天数（转换为字符串）保存到数据库
    # 注意：set_setting 现在需要 db 参数
    await set_setting(db, 'context_ttl_days', str(days))
