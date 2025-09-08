# -*- coding: utf-8 -*-
"""
数据库模型定义。
使用 SQLAlchemy 定义与数据库表对应的 Python 类。
"""
from sqlalchemy.ext.declarative import declarative_base # 导入声明性基类
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Boolean, func # 导入列类型和函数
from sqlalchemy.orm import sessionmaker # 导入会话创建器
from datetime import datetime, timezone # 导入日期时间处理
import pytz # 导入时区库
import logging # 导入日志模块

# 获取日志记录器实例
logger = logging.getLogger('my_logger')

# 创建所有模型类的基类
Base = declarative_base()

class ApiKey(Base):
    """
    API 密钥模型，用于在数据库中存储 API Key 的信息。
    对应数据库中的 'api_keys' 表。
    """
    __tablename__ = 'api_keys' # 定义数据库表名

    id = Column(Integer, primary_key=True, autoincrement=True) # 主键 ID，自增整数
    key_string = Column(String, nullable=False, unique=True, index=True) # API Key 字符串，不允许为空，必须唯一，并建立索引以加快查询
    description = Column(String, nullable=True) # Key 的描述信息，可以为空
    created_at = Column(DateTime(timezone=True), server_default=func.now()) # Key 的创建时间，带时区信息，数据库自动设置为当前时间
    expires_at = Column(DateTime(timezone=True), nullable=True) # Key 的过期时间，带时区信息，可以为空（表示永不过期）
    is_active = Column(Boolean, default=True, nullable=False) # Key 是否处于激活状态，默认为 True，不允许为空
    enable_context_completion = Column(Boolean, default=True, nullable=False) # 此 Key 是否启用上下文补全功能，默认为 True，不允许为空
    user_id = Column(String, nullable=True, index=True) # 与此 Key 关联的用户 ID (可选)，可以为空，建立索引

    def __repr__(self):
        """
        定义对象的字符串表示形式，方便调试。
        隐藏完整的 Key 字符串，只显示前缀。
        """
        # 优化 repr 输出，避免显示完整 Key
        key_preview = f"{self.key_string[:8]}..." if self.key_string else "None" # 获取 Key 的前 8 位作为预览
        return f'<ApiKey(id={self.id}, key_preview={key_preview}, description={self.description}, is_active={self.is_active})>' # 返回格式化的字符串


class UserKeyAssociation(Base):
    """
    用户与 API 密钥关联模型。
    用于记录哪个用户最后使用了哪个 Key，支持粘性会话功能。
    对应数据库中的 'user_key_associations' 表。
    """
    __tablename__ = 'user_key_associations' # 定义数据库表名
    id = Column(Integer, primary_key=True, autoincrement=True) # 主键 ID
    user_id = Column(String, nullable=False, index=True) # 用户 ID，不允许为空，建立索引
    key_id = Column(Integer, nullable=False, index=True) # 关联的 ApiKey 表的 ID，不允许为空，建立索引
    last_used_timestamp = Column(Float, nullable=False) # 最后使用该 Key 的时间戳 (Unix timestamp)

    def __repr__(self):
        """
        定义对象的字符串表示形式。
        """
        return f'<UserKeyAssociation(user_id={self.user_id}, key_id={self.key_id}, last_used={self.last_used_timestamp})>'


class KeyScore(Base):
    """
    API 密钥分数模型 (目前可能未使用)。
    设计用于存储每个 Key 对不同模型的评分或优先级。
    对应数据库中的 'key_scores' 表。
    """
    __tablename__ = 'key_scores' # 定义数据库表名
    id = Column(Integer, primary_key=True, autoincrement=True) # 主键 ID
    model_name = Column(String, nullable=False, index=True) # 模型名称，不允许为空，建立索引
    key_id = Column(Integer, nullable=False, index=True) # 关联的 ApiKey 表的 ID，不允许为空，建立索引
    score = Column(Float, nullable=False) # Key 对该模型的分数

    def __repr__(self):
        """
        定义对象的字符串表示形式。
        """
        return f'<KeyScore(model_name={self.model_name}, key_id={self.key_id}, score={self.score})>'

class CachedContent(Base):
    """
    缓存内容模型。
    用于存储原生缓存的数据。
    对应数据库中的 'cached_contents' 表。
    """
    __tablename__ = 'cached_contents' # 定义数据库表名
    id = Column(Integer, primary_key=True, autoincrement=True) # 主键 ID
    content_id = Column(String, nullable=False, unique=True, index=True) # 缓存内容的唯一 ID (通常是内容的哈希值)，不允许为空，唯一且索引
    content = Column(Text, nullable=False) # 缓存的实际内容 (JSON 字符串或其他格式)
    user_id = Column(String, nullable=True, index=True) # 创建此缓存的用户 ID (可选)，建立索引
    key_id = Column(Integer, nullable=True, index=True) # 创建此缓存时使用的 Key ID (可选)，建立索引
    creation_timestamp = Column(Float, nullable=False) # 缓存创建时的时间戳 (Unix timestamp)
    expiration_timestamp = Column(Float, nullable=False) # 缓存过期时的时间戳 (Unix timestamp)
    gemini_cache_id = Column(String, nullable=True, index=True) # Gemini API 返回的缓存 ID (可选)

    def __repr__(self):
        """
        定义对象的字符串表示形式。
        """
        return f'<CachedContent(content_id={self.content_id}, creation_timestamp={self.creation_timestamp}, expiration_timestamp={self.expiration_timestamp})>'

class Setting(Base):
    """
    设置模型，用于存储应用程序的键值对设置。
    例如，可以存储管理员密码或其他配置项。
    对应数据库中的 'settings' 表。
    """
    __tablename__ = 'settings' # 定义数据库表名
    key = Column(String, primary_key=True) # 设置项的键，作为主键
    value = Column(String) # 设置项的值

    def __repr__(self):
        """
        定义对象的字符串表示形式。
        """
        return f'<Setting(key={self.key}, value={self.value})>'

class DialogContext(Base):
    """
    传统对话上下文存储模型。
    对应数据库中的 'dialog_contexts' 表。
    """
    __tablename__ = 'dialog_contexts' # 定义数据库表名

    id = Column(Integer, primary_key=True, autoincrement=True) # 主键 ID
    # proxy_key 通常是 user_id，用于标识上下文属于哪个用户/代理密钥
    proxy_key = Column(String, nullable=False, index=True) 
    # contents 存储对话历史，通常是 JSON 字符串格式的 Gemini contents
    contents = Column(Text, nullable=False) 
    # last_used_at 记录此上下文最后被使用的时间，用于 TTL 判断和清理
    last_used_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    # created_at 记录此上下文创建的时间
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # ttl_seconds 允许为此特定上下文设置自定义的 TTL (秒)。如果为 NULL，则可能遵循全局 TTL。
    ttl_seconds = Column(Integer, nullable=True) 

    def __repr__(self):
        """
        定义对象的字符串表示形式，方便调试。
        """
        return f'<DialogContext(id={self.id}, proxy_key={self.proxy_key}, last_used_at={self.last_used_at})>'

# --- 数据库会话和引擎创建/关闭函数 (可能已移至 database/utils.py 或 dependencies.py) ---
# 这些函数通常不直接放在模型文件中，而是放在数据库工具或依赖注入模块中。
# 保留它们在这里可能只是历史原因，或者在某些特定场景下使用。

def create_session(engine):
    """
    (可能已废弃) 创建一个同步的 SQLAlchemy 数据库会话。
    注意：项目主要使用异步会话。
    """
    logger.warning("调用了可能已废弃的同步 create_session 函数。") # 记录警告
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine) # 创建会话工厂
    return SessionLocal() # 返回会话实例

async def create_db_engine():
    """
    (可能已废弃) 创建一个 aiosqlite 数据库连接（引擎）。
    注意：项目现在可能使用 SQLAlchemy 的异步引擎。
    """
    logger.warning("调用了可能已废弃的 create_db_engine 函数 (aiosqlite)。") # 记录警告
    import aiosqlite # 导入 aiosqlite
    # 连接到数据库文件
    engine = await aiosqlite.connect('app/data/context_store.db', uri=True) # 创建连接
    return engine # 返回连接对象

async def close_db_engine(engine):
    """
    (可能已废弃) 关闭一个 aiosqlite 数据库连接（引擎）。
    """
    logger.warning("调用了可能已废弃的 close_db_engine 函数 (aiosqlite)。") # 记录警告
    await engine.close() # 关闭连接
