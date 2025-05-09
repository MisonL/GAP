# -*- coding: utf-8 -*-
"""
缓存清理模块。
使用 APScheduler 设置后台定时任务，定期清理过期和无效的缓存。
"""

import logging # 导入日志模块
from apscheduler.schedulers.asyncio import AsyncIOScheduler # 导入异步调度器
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession # 导入 SQLAlchemy 异步引擎和会话
from sqlalchemy.orm import sessionmaker # 导入 sessionmaker

from app.core.database.utils import DATABASE_URL # 从 utils 导入数据库 URL
from app.core.cache.manager import CacheManager # (新路径)

logger = logging.getLogger(__name__) # 获取当前模块的日志记录器

# 在模块级别创建异步引擎和 sessionmaker
# 这样它们可以在多个任务调用之间复用，而不是每次都重新创建引擎
# 注意：echo=False 通常用于生产环境，以避免过多的 SQL 日志
async_engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionFactory = sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False # 避免在提交后 ORM 对象过期
)

async def cleanup_expired_cache(): # 函数不再接收 conn 参数
    """
    异步后台任务：清理数据库中过期的缓存元数据和可能存在的无效缓存条目。
    此函数由 APScheduler 定期调用。
    它会自行创建和管理 AsyncSession。
    """
    logger.info("开始执行缓存清理任务...") # 记录任务开始日志
    # 使用 sessionmaker 创建一个新的 AsyncSession
    async with AsyncSessionFactory() as session: # 类型: AsyncSession
        try:
            # 创建 CacheManager 实例
            cache_manager_instance = CacheManager()

            # 调用 CacheManager 实例的 cleanup_expired_caches 方法清理过期缓存
            logger.info("正在调用 cache_manager_instance.cleanup_expired_caches...")
            await cache_manager_instance.cleanup_expired_caches(session) # 传递 AsyncSession

            # 调用 CacheManager 实例的 cleanup_invalid_caches 方法清理无效缓存
            logger.info("正在调用 cache_manager_instance.cleanup_invalid_caches...")
            await cache_manager_instance.cleanup_invalid_caches(session) # 传递 AsyncSession

            await session.commit() # 提交会话中的任何更改 (如果 CacheManager 方法内部没有提交)
            logger.info(f"缓存清理任务成功完成。") # 记录任务完成日志

        except Exception as e: # 捕获任务执行过程中的任何异常
            await session.rollback() # 发生错误时回滚事务
            logger.error(f"缓存清理任务执行失败: {e}", exc_info=True) # 记录错误日志
        finally:
            # 记录任务执行结束的日志（无论成功或失败）
            logger.info("缓存清理任务执行结束。")
            # session 会在 async with 块结束时自动关闭

def start_cache_cleanup_scheduler(): # 函数不再接收 conn 参数
    """
    启动一个 APScheduler 调度器，用于定期执行缓存清理任务。
    清理任务将自行管理数据库会话。

    Returns:
        AsyncIOScheduler: 已启动的调度器实例。
    """
    scheduler = AsyncIOScheduler() # 创建异步调度器实例
    # 添加一个定时作业 (job)
    # cleanup_expired_cache: 要执行的异步函数
    # 'interval': 触发器类型，表示按固定时间间隔执行
    # hours=1: 时间间隔为 1 小时
    # args 不再需要，因为 cleanup_expired_cache 不再接收参数
    scheduler.add_job(cleanup_expired_cache, 'interval', hours=1)
    scheduler.start() # 启动调度器
    logger.info("缓存清理调度器已启动，每小时执行一次。") # 记录调度器启动日志
    return scheduler # 返回调度器实例

# --- 主程序入口 (用于独立测试) ---
if __name__ == "__main__":
    # 这是一个简单的示例，用于在直接运行此文件时测试调度器功能
    # 在实际应用中，调度器的启动通常集成在 FastAPI 应用的启动事件 (lifespan) 中
    import asyncio # 导入 asyncio
    # 在测试时，确保日志级别足够低以查看 INFO 和 DEBUG 消息
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


    async def main():
        """异步主函数，用于测试"""
        # 初始化数据库表 (如果尚未初始化)
        # 在实际应用中，这通常在应用启动时完成
        # from app.core.database.utils import initialize_db_tables
        # await initialize_db_tables() # 确保表存在

        # 启动调度器
        scheduler = start_cache_cleanup_scheduler()
        # 让主程序保持运行，以便调度器可以在后台执行任务
        try:
            while True:
                await asyncio.sleep(3600) # 每小时检查一次（或根据需要调整）
        except asyncio.CancelledError:
             logger.info("主任务被取消。")
        finally:
             # 应用关闭时应优雅地关闭调度器
             if scheduler and scheduler.running:
                  scheduler.shutdown()
                  logger.info("缓存清理调度器已关闭。")

    try:
        # 运行异步主函数
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit): # 捕获手动中断或系统退出信号
        logger.info("缓存清理测试程序退出。") # 记录退出日志
