# 导入必要的库
import random  # 用于生成随机数和随机选择
from fastapi import HTTPException, Request  # FastAPI 框架的异常和请求对象
import time      # 用于时间相关操作 (例如速率限制)
import re        # 用于正则表达式 (提取 API 密钥)
from datetime import datetime, timedelta  # 用于日期和时间计算 (黑名单持续时间)
from apscheduler.schedulers.background import BackgroundScheduler # 用于后台定时任务 (移除黑名单)
import os        # 用于访问环境变量
import requests  # 用于发送同步 HTTP 请求 (处理错误)
import httpx     # 用于发送异步 HTTP 请求 (测试密钥)
from threading import Lock # 用于线程锁 (保护速率限制数据)
import logging   # 用于日志记录
import sys       # 用于系统相关操作
from .log_config import format_log_message # 从本地 log_config 模块导入日志格式化函数

# 获取名为 'my_logger' 的日志记录器实例
logger = logging.getLogger("my_logger")


# 定义 API 密钥管理器类
class APIKeyManager:
    """
    管理 Gemini API 密钥，包括轮询、随机化和无效密钥处理。
    """
    def __init__(self):
        """初始化 APIKeyManager"""
        # 从环境变量 GEMINI_API_KEYS 中提取所有符合 Gemini API 密钥格式的字符串
        self.api_keys = re.findall(
            r"AIzaSy[a-zA-Z0-9_-]{33}", os.environ.get('GEMINI_API_KEYS', ""))
        self.key_stack = [] # 初始化用于轮询的密钥栈
        self._reset_key_stack() # 初始化时创建并随机化密钥栈
        # self.api_key_blacklist = set() # 黑名单集合 (当前未使用)
        # self.api_key_blacklist_duration = 60 # 黑名单持续时间 (秒) (当前未使用)
        self.scheduler = BackgroundScheduler() # 创建后台调度器 (用于黑名单移除，当前未使用)
        self.scheduler.start() # 启动调度器
        self.tried_keys_for_request = set()  # 用于跟踪当前单个请求处理过程中已尝试过的密钥

    def _reset_key_stack(self):
        """
        重置并随机化密钥栈。
        当栈为空或需要重新排序时调用。
        """
        shuffled_keys = self.api_keys[:]  # 创建 api_keys 的副本以避免直接修改原列表
        random.shuffle(shuffled_keys)     # 随机打乱副本列表
        self.key_stack = shuffled_keys      # 将打乱后的列表设置为新的密钥栈

    def get_available_key(self, force_check=False): # 添加 force_check 参数
        """
        从栈顶获取一个可用的 API 密钥。
        如果栈为空，则重置栈并再次尝试。
        会跳过在当前请求中已尝试过的密钥。

        Args:
            force_check (bool): 是否强制重新检查密钥有效性 (暂未使用，但保留接口)

        Returns:
            str or None: 返回一个可用的 API 密钥字符串，如果无可用密钥则返回 None。
        """
        # 只要栈不为空，就尝试从中获取密钥
        while self.key_stack:
            key = self.key_stack.pop() # 从栈顶弹出一个密钥
            # 检查此密钥是否已在当前请求中尝试过
            if key not in self.tried_keys_for_request:
                self.tried_keys_for_request.add(key) # 将此密钥标记为已尝试
                return key # 返回此可用密钥

        # 如果栈为空，检查是否配置了任何 API 密钥
        if not self.api_keys:
            log_msg = format_log_message('ERROR', "没有配置任何 API 密钥！")
            logger.error(log_msg)
            return None # 没有配置密钥，返回 None

        # 如果栈为空但有配置密钥，说明一轮尝试已完成，重置密钥栈
        logger.info("所有密钥已尝试一轮，重置密钥栈...")
        self._reset_key_stack() # 重新生成并随机化密钥栈

        # 再次尝试从新生成的栈中获取密钥 (只迭代一次，避免无限循环)
        while self.key_stack:
            key = self.key_stack.pop()
            # 检查此密钥是否已在当前请求中尝试过 (理论上在新栈中不会)
            if key not in self.tried_keys_for_request:
                self.tried_keys_for_request.add(key)
                return key

        # 如果重置栈后仍然找不到未尝试过的密钥 (理论上不应发生，除非所有密钥都被移除)
        logger.error("重置密钥栈后仍无法获取可用密钥！")
        return None

    def show_all_keys(self):
        """记录日志，显示当前配置的所有有效 API 密钥 (部分隐藏)"""
        log_msg = format_log_message('INFO', f"当前可用API key个数: {len(self.api_keys)} ")
        logger.info(log_msg)
        for i, api_key in enumerate(self.api_keys):
            # 只显示密钥的前 8 位和后 3 位
            log_msg = format_log_message('INFO', f"API Key{i}: {api_key[:8]}...{api_key[-3:]}")
            logger.info(log_msg)

    # --- 黑名单逻辑 (当前未使用，保持注释) ---
    # def blacklist_key(self, key):
    #     """将指定密钥加入黑名单一段时间"""
    #     log_msg = format_log_message('WARNING', f"{key[:8]} → 暂时禁用 {self.api_key_blacklist_duration} 秒")
    #     logger.warning(log_msg)
    #     self.api_key_blacklist.add(key)
    #     # 添加一个一次性任务，在指定时间后从黑名单中移除该密钥
    #     self.scheduler.add_job(lambda: self.api_key_blacklist.discard(key), 'date',
    #                            run_date=datetime.now() + timedelta(seconds=self.api_key_blacklist_duration))

    def reset_tried_keys_for_request(self):
        """
        重置用于跟踪单个请求中已尝试密钥的集合。
        应在每次处理新请求开始时调用。
        """
        self.tried_keys_for_request = set()


# --- Gemini API 错误处理函数 ---
def handle_gemini_error(error, current_api_key, key_manager) -> str:
    """
    处理调用 Gemini API 时可能发生的各种异常，并根据错误类型执行相应操作 (如移除无效密钥)。

    Args:
        error: 捕获到的异常对象。
        current_api_key: 当前正在使用的 API 密钥。
        key_manager: APIKeyManager 实例。

    Returns:
        str: 格式化或翻译后的错误消息字符串，用于向客户端返回。
    """
    # 检查是否为 requests 库的 HTTP 错误或 httpx 的 HTTP 状态错误
    if isinstance(error, requests.exceptions.HTTPError) or isinstance(error, httpx.HTTPStatusError):
        # 统一获取响应对象
        response = error.response if hasattr(error, 'response') else None
        if response is None:
             # 如果是 httpx 错误但没有 response 对象，可能是连接问题
             error_message = f"HTTP 请求错误，无响应对象: {error}"
             log_msg = format_log_message('ERROR', error_message, extra={'key': current_api_key[:8] if current_api_key else 'N/A', 'error_message': str(error)})
             logger.error(log_msg)
             key_manager.switch_api_key() # 发生未知 HTTP 错误也尝试切换
             return error_message

        status_code = response.status_code # 获取 HTTP 状态码

        # --- 根据状态码处理不同错误 ---
        if status_code == 400: # 错误请求
            try:
                error_data = response.json() # 尝试解析 JSON 错误响应体
                if 'error' in error_data:
                    error_info = error_data['error']
                    # 检查是否为无效 API 密钥错误
                    # 注意: Google API 可能使用不同的错误代码或消息表示无效密钥，这里基于常见情况判断
                    if error_info.get('status') == 'INVALID_ARGUMENT' or "API key not valid" in error_info.get('message', ''):
                        error_message = "无效的 API 密钥"
                        extra_log_invalid_key = {'key': current_api_key[:8], 'status_code': status_code, 'error_message': error_message}
                        log_msg = format_log_message('ERROR', f"{current_api_key[:8]} ... {current_api_key[-3:]} → 无效，可能已过期或被删除。将从列表中移除。", extra=extra_log_invalid_key)
                        logger.error(log_msg)
                        # 从密钥列表中移除无效密钥
                        if current_api_key in key_manager.api_keys:
                            key_manager.api_keys.remove(current_api_key)
                            key_manager._reset_key_stack() # 移除后重置栈
                        # 切换到下一个密钥 (如果还有)
                        key_manager.switch_api_key() # 调用切换逻辑
                        return error_message
                    # 其他 400 错误
                    error_message = error_info.get('message', 'Bad Request')
                    extra_log_400 = {'key': current_api_key[:8], 'status_code': status_code, 'error_message': error_message}
                    log_msg = format_log_message('WARNING', f"400 错误请求: {error_message}", extra=extra_log_400)
                    logger.warning(log_msg)
                    # 对于其他 400 错误，也尝试切换密钥
                    key_manager.switch_api_key()
                    return f"400 错误请求: {error_message}"
                else:
                    # 如果 JSON 中没有 'error' 字段
                    error_message = "400 错误请求：未知的错误结构"
                    extra_log_400_struct = {'key': current_api_key[:8], 'status_code': status_code, 'error_message': response.text} # 记录原始响应文本
                    log_msg = format_log_message('WARNING', error_message, extra=extra_log_400_struct)
                    logger.warning(log_msg)
                    key_manager.switch_api_key()
                    return error_message
            except ValueError: # JSON 解析失败
                error_message = "400 错误请求：响应不是有效的JSON格式"
                extra_log_400_json = {'key': current_api_key[:8], 'status_code': status_code, 'error_message': response.text} # 记录原始响应文本
                log_msg = format_log_message('WARNING', error_message, extra=extra_log_400_json)
                logger.warning(log_msg)
                key_manager.switch_api_key()
                return error_message

        elif status_code == 429: # 请求过多 (速率限制或配额耗尽)
            error_message = "API 密钥配额已用尽或达到速率限制"
            extra_log_429 = {'key': current_api_key[:8], 'status_code': status_code, 'error_message': error_message}
            log_msg = format_log_message('WARNING', f"{current_api_key[:8]} ... {current_api_key[-3:]} → 429 资源耗尽或速率限制", extra=extra_log_429)
            logger.warning(log_msg)
            # 切换到下一个密钥
            key_manager.switch_api_key()
            return error_message

        elif status_code == 403: # 禁止访问
            error_message = "权限被拒绝"
            extra_log_403 = {'key': current_api_key[:8], 'status_code': status_code, 'error_message': error_message}
            log_msg = format_log_message('ERROR', f"{current_api_key[:8]} ... {current_api_key[-3:]} → 403 权限被拒绝。将从列表中移除。", extra=extra_log_403)
            logger.error(log_msg)
            # 从密钥列表中移除无效密钥
            if current_api_key in key_manager.api_keys:
                key_manager.api_keys.remove(current_api_key)
                key_manager._reset_key_stack() # 移除后重置栈
            # 切换到下一个密钥
            key_manager.switch_api_key()
            return error_message

        elif status_code == 500: # 服务器内部错误
            error_message = "Gemini API 服务器内部错误"
            extra_log_500 = {'key': current_api_key[:8], 'status_code': status_code, 'error_message': error_message}
            log_msg = format_log_message('WARNING', f"{current_api_key[:8]} ... {current_api_key[-3:]} → 500 服务器内部错误", extra=extra_log_500)
            logger.warning(log_msg)
            # 切换到下一个密钥
            key_manager.switch_api_key()
            return error_message

        elif status_code == 503: # 服务不可用
            error_message = "Gemini API 服务不可用"
            extra_log_503 = {'key': current_api_key[:8], 'status_code': status_code, 'error_message': error_message}
            log_msg = format_log_message('WARNING', f"{current_api_key[:8]} ... {current_api_key[-3:]} → 503 服务不可用", extra=extra_log_503)
            logger.warning(log_msg)
            # 切换到下一个密钥
            key_manager.switch_api_key()
            return error_message
        else: # 其他 HTTP 错误状态码
            error_message = f"未知的 HTTP 错误: {status_code}"
            extra_log_other = {'key': current_api_key[:8], 'status_code': status_code, 'error_message': response.text} # 记录原始响应文本
            log_msg = format_log_message('WARNING', f"{current_api_key[:8]} ... {current_api_key[-3:]} → {status_code} 未知 HTTP 错误", extra=extra_log_other)
            logger.warning(log_msg)
            # 切换到下一个密钥
            key_manager.switch_api_key()
            return f"未知错误/模型不可用: {status_code}"

    # 检查是否为 requests 库的连接错误或 httpx 的连接错误
    elif isinstance(error, requests.exceptions.ConnectionError) or isinstance(error, httpx.ConnectError):
        error_message = "连接错误"
        log_msg = format_log_message('WARNING', error_message, extra={'key': current_api_key[:8] if current_api_key else 'N/A', 'error_message': str(error)})
        logger.warning(log_msg)
        # 切换到下一个密钥
        key_manager.switch_api_key()
        return error_message

    # 检查是否为 requests 库的超时错误或 httpx 的超时错误
    elif isinstance(error, requests.exceptions.Timeout) or isinstance(error, httpx.TimeoutException):
        error_message = "请求超时"
        log_msg = format_log_message('WARNING', error_message, extra={'key': current_api_key[:8] if current_api_key else 'N/A', 'error_message': str(error)})
        logger.warning(log_msg)
        # 切换到下一个密钥
        key_manager.switch_api_key()
        return error_message
    # 处理流式响应中因安全策略等原因抛出的 ValueError
    elif isinstance(error, ValueError) and "流式传输因安全问题而终止" in str(error):
         error_message = str(error) # 使用 ValueError 中的消息
         log_msg = format_log_message('WARNING', f"流式响应被阻止: {error_message}", extra={'key': current_api_key[:8] if current_api_key else 'N/A', 'error_message': error_message})
         logger.warning(log_msg)
         # 切换到下一个密钥
         key_manager.switch_api_key()
         return error_message # 返回具体的错误信息给客户端
    else: # 其他未知错误
        error_message = f"发生未知错误: {error}"
        log_msg = format_log_message('ERROR', error_message, extra={'key': current_api_key[:8] if current_api_key else 'N/A', 'error_message': str(error)})
        logger.error(log_msg)
        # 切换到下一个密钥
        key_manager.switch_api_key()
        return error_message


async def test_api_key(api_key: str) -> bool:
    """
    异步测试单个 API 密钥是否有效。
    通过尝试调用获取模型列表的端点来判断。

    Args:
        api_key: 要测试的 API 密钥。

    Returns:
        bool: 如果密钥有效则返回 True，否则返回 False。
    """
    if not api_key: # 处理空密钥的情况
        return False
    try:
        # 构建获取模型列表的 URL
        url = "https://generativelanguage.googleapis.com/v1beta/models?key={}".format(api_key)
        # 使用 httpx 发送异步 GET 请求
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10) # 添加超时设置
            # 如果响应状态码表示成功 (2xx)，则认为密钥有效
            response.raise_for_status() # 这会检查 2xx 状态码，否则抛出异常
            return True
    except httpx.HTTPStatusError as e:
        # 特别处理常见的无效密钥错误 (400, 403)
        if e.response.status_code in [400, 403]:
            logger.debug(f"测试密钥 {api_key[:8]}... 时返回状态码 {e.response.status_code}，判定为无效。")
            return False
        else:
            # 其他 HTTP 错误也视为无效或暂时不可用
            logger.warning(f"测试密钥 {api_key[:8]}... 时发生 HTTP 错误: {e}")
            return False
    except Exception as e:
        # 捕获其他所有异常 (例如网络连接问题、超时等)，均视为无效
        logger.warning(f"测试密钥 {api_key[:8]}... 时发生异常: {e}")
        return False


# --- 速率限制 ---
rate_limit_data = {} # 用于存储速率限制计数和时间戳的字典
rate_limit_lock = Lock() # 用于保护 rate_limit_data 访问的线程锁


def protect_from_abuse(request: Request, max_requests_per_minute: int = 30, max_requests_per_day_per_ip: int = 600):
    """
    基于内存的速率限制和防滥用检查。
    限制每个端点每分钟的请求数和每个 IP 每天的请求数。

    Args:
        request: FastAPI 的请求对象。
        max_requests_per_minute: 每分钟允许的最大请求数。
        max_requests_per_day_per_ip: 每个 IP 每天允许的最大请求数。

    Raises:
        HTTPException: 如果请求超过了速率限制 (状态码 429)。
    """
    now = int(time.time()) # 获取当前时间戳 (秒)
    minute = now // 60     # 计算当前所属的分钟数 (自 epoch 起)
    day = now // (60 * 60 * 24) # 计算当前所属的天数 (自 epoch 起)

    # 构建用于存储计数的键
    minute_key = f"{request.url.path}:{minute}" # 分钟限制键 (基于请求路径和分钟数)
    # 优先使用 X-Forwarded-For 头获取真实 IP (如果存在且有效)
    client_ip = request.headers.get("x-forwarded-for")
    if client_ip:
        client_ip = client_ip.split(',')[0].strip() # 取第一个 IP
    else:
        client_ip = request.client.host if request.client else "unknown_ip" # 备选方案
    day_key = f"{client_ip}:{day}"    # 天限制键 (基于客户端 IP 和天数)

    # 使用线程锁保护对共享字典 rate_limit_data 的访问
    with rate_limit_lock:
        # --- 清理过期数据 (概率性执行) ---
        # 为了避免每次请求都遍历字典，采用概率性清理策略
        # 仅在字典非空且随机数小于 0.01 (1% 概率) 时执行清理
        if len(rate_limit_data) > 0 and random.random() < 0.01:
            current_minute = now // 60
            current_day = now // (60 * 60 * 24)
            keys_to_remove = [] # 存储需要移除的过期键

            # 遍历字典中的所有项 (使用 list() 创建副本以允许在迭代中删除)
            for key, value in list(rate_limit_data.items()):
                try:
                    # 检查数据格式是否正确 (应为包含计数和时间戳的元组)
                    if not isinstance(value, tuple) or len(value) != 2:
                        keys_to_remove.append(key) # 格式不正确，标记删除
                        continue

                    count, timestamp = value # 解包计数和时间戳

                    # 解析键以判断是分钟级别还是天级别
                    if ':' in key:
                        prefix, time_value_str = key.split(':', 1)
                        if time_value_str.isdigit():
                            time_value = int(time_value_str)
                            # 判断键的类型并检查是否过期
                            if ':' in prefix:  # 天级别键 (例如 "127.0.0.1:19800")
                                # 保留最近 2 天的数据 (当前天和前一天)
                                if time_value < current_day - 1:
                                    keys_to_remove.append(key)
                            else:  # 分钟级别键 (例如 "/v1/chat/completions:33000000")
                                # 保留最近 10 分钟的数据
                                if time_value < current_minute - 10:
                                    keys_to_remove.append(key)
                        else: # time_value 不是数字，格式错误
                             keys_to_remove.append(key)
                    else: # 键格式不正确
                        keys_to_remove.append(key)
                except Exception as e:
                    # 如果处理过程中出现任何异常，记录警告并标记删除
                    logger.warning(f"清理速率限制数据时出错: {e}，将删除键: {key}")
                    keys_to_remove.append(key)

            # 执行删除操作
            for key in keys_to_remove:
                try:
                    del rate_limit_data[key]
                except KeyError:
                    pass  # 键可能已被其他线程删除，忽略

            # 如果执行了清理，记录日志 (DEBUG 级别)
            if keys_to_remove:
                logger.debug(f"已清理 {len(keys_to_remove)} 条过期的速率限制记录，当前记录数: {len(rate_limit_data)}")

        # --- 更新并检查分钟限制 ---
        # 获取当前分钟的计数和时间戳，如果键不存在则默认为 (0, now)
        minute_count, minute_timestamp = rate_limit_data.get(minute_key, (0, now))
        # 如果记录的时间戳已超过 1 分钟，则重置计数和时间戳
        if now - minute_timestamp >= 60:
            minute_count = 0
            minute_timestamp = now
        minute_count += 1 # 增加本次请求的计数
        # 更新字典中的记录
        rate_limit_data[minute_key] = (minute_count, minute_timestamp)

        # --- 更新并检查天限制 ---
        # 获取当前 IP 当天的计数和时间戳
        day_count, day_timestamp = rate_limit_data.get(day_key, (0, now))
        # 如果记录的时间戳已超过 1 天，则重置计数和时间戳
        if now - day_timestamp >= 86400:
            day_count = 0
            day_timestamp = now
        day_count += 1 # 增加本次请求的计数
        # 更新字典中的记录
        rate_limit_data[day_key] = (day_count, day_timestamp)

    # --- 检查是否超过限制 ---
    # 如果分钟计数超过限制，抛出 429 异常
    if minute_count > max_requests_per_minute:
        logger.warning(f"速率限制触发 (分钟): 路径={request.url.path}, 限制={max_requests_per_minute}")
        raise HTTPException(status_code=429, detail={
            "message": "Too many requests per minute", "limit": max_requests_per_minute})
    # 如果天计数超过限制，抛出 429 异常
    if day_count > max_requests_per_day_per_ip:
        logger.warning(f"速率限制触发 (天): IP={client_ip}, 限制={max_requests_per_day_per_ip}")
        raise HTTPException(status_code=429, detail={"message": "Too many requests per day from this IP", "limit": max_requests_per_day_per_ip})