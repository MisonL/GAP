import random
from fastapi import HTTPException, Request
import time
import re
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
import os
import requests
import httpx
from threading import Lock
import logging
import sys
from .log_config import format_log_message

# 获取logger实例
logger = logging.getLogger("my_logger")


class APIKeyManager:
    def __init__(self):
        self.api_keys = re.findall(
            r"AIzaSy[a-zA-Z0-9_-]{33}", os.environ.get('GEMINI_API_KEYS', ""))
        self.key_stack = [] # 初始化密钥栈
        self._reset_key_stack() # 初始化时创建随机密钥栈
        # self.api_key_blacklist = set()
        # self.api_key_blacklist_duration = 60
        self.scheduler = BackgroundScheduler()
        self.scheduler.start()
        self.tried_keys_for_request = set()  # 用于跟踪当前请求尝试中已试过的 key

    def _reset_key_stack(self):
        """创建并随机化密钥栈"""
        shuffled_keys = self.api_keys[:]  # 创建 api_keys 的副本以避免直接修改原列表
        random.shuffle(shuffled_keys)
        self.key_stack = shuffled_keys


    def get_available_key(self):
        """从栈顶获取密钥，栈空时重新生成 (修改后)"""
        while self.key_stack:
            key = self.key_stack.pop()
            # if key not in self.api_key_blacklist and key not in self.tried_keys_for_request:
            if key not in self.tried_keys_for_request:
                self.tried_keys_for_request.add(key)
                return key

        if not self.api_keys:
            log_msg = format_log_message('ERROR', "没有配置任何 API 密钥！")
            logger.error(log_msg)
            return None

        self._reset_key_stack() # 重新生成密钥栈

        # 再次尝试从新栈中获取密钥 (迭代一次)
        while self.key_stack:
            key = self.key_stack.pop()
            # if key not in self.api_key_blacklist and key not in self.tried_keys_for_request:
            if key not in self.tried_keys_for_request:
                self.tried_keys_for_request.add(key)
                return key

        return None


    def show_all_keys(self):
        log_msg = format_log_message('INFO', f"当前可用API key个数: {len(self.api_keys)} ")
        logger.info(log_msg)
        for i, api_key in enumerate(self.api_keys):
            log_msg = format_log_message('INFO', f"API Key{i}: {api_key[:8]}...{api_key[-3:]}")
            logger.info(log_msg)

    # def blacklist_key(self, key):
    #     log_msg = format_log_message('WARNING', f"{key[:8]} → 暂时禁用 {self.api_key_blacklist_duration} 秒")
    #     logger.warning(log_msg)
    #     self.api_key_blacklist.add(key)
    #     self.scheduler.add_job(lambda: self.api_key_blacklist.discard(key), 'date',
    #                            run_date=datetime.now() + timedelta(seconds=self.api_key_blacklist_duration))

    def reset_tried_keys_for_request(self):
        """在新的请求尝试时重置已尝试的 key 集合"""
        self.tried_keys_for_request = set()


def handle_gemini_error(error, current_api_key, key_manager) -> str:
    if isinstance(error, requests.exceptions.HTTPError):
        status_code = error.response.status_code
        if status_code == 400:
            try:
                error_data = error.response.json()
                if 'error' in error_data:
                    if error_data['error'].get('code') == "invalid_argument":
                        error_message = "无效的 API 密钥"
                        extra_log_invalid_key = {'key': current_api_key[:8], 'status_code': status_code, 'error_message': error_message}
                        log_msg = format_log_message('ERROR', f"{current_api_key[:8]} ... {current_api_key[-3:]} → 无效，可能已过期或被删除。将从列表中移除。", extra=extra_log_invalid_key)
                        logger.error(log_msg)
                        # key_manager.blacklist_key(current_api_key) # 保持注释掉黑名单逻辑
                        if current_api_key in key_manager.api_keys:
                            key_manager.api_keys.remove(current_api_key)
                            key_manager._reset_key_stack() # 移除后重置栈
                        return error_message
                    error_message = error_data['error'].get(
                        'message', 'Bad Request')
                    extra_log_400 = {'key': current_api_key[:8], 'status_code': status_code, 'error_message': error_message}
                    log_msg = format_log_message('WARNING', f"400 错误请求: {error_message}", extra=extra_log_400)
                    logger.warning(log_msg)
                    return f"400 错误请求: {error_message}"
            except ValueError:
                error_message = "400 错误请求：响应不是有效的JSON格式"
                extra_log_400_json = {'key': current_api_key[:8], 'status_code': status_code, 'error_message': error_message}
                log_msg = format_log_message('WARNING', error_message, extra=extra_log_400_json)
                logger.warning(log_msg)
                return error_message

        elif status_code == 429:
            error_message = "API 密钥配额已用尽或其他原因"
            extra_log_429 = {'key': current_api_key[:8], 'status_code': status_code, 'error_message': error_message}
            log_msg = format_log_message('WARNING', f"{current_api_key[:8]} ... {current_api_key[-3:]} → 429 官方资源耗尽或其他原因", extra=extra_log_429)
            logger.warning(log_msg)
            # key_manager.blacklist_key(current_api_key)
             
            return error_message

        elif status_code == 403:
            error_message = "权限被拒绝"
            extra_log_403 = {'key': current_api_key[:8], 'status_code': status_code, 'error_message': error_message}
            log_msg = format_log_message('ERROR', f"{current_api_key[:8]} ... {current_api_key[-3:]} → 403 权限被拒绝。将从列表中移除。", extra=extra_log_403)
            logger.error(log_msg)
            # key_manager.blacklist_key(current_api_key) # 保持注释掉黑名单逻辑
            if current_api_key in key_manager.api_keys:
                key_manager.api_keys.remove(current_api_key)
                key_manager._reset_key_stack() # 移除后重置栈
            return error_message
        elif status_code == 500:
            error_message = "服务器内部错误"
            extra_log_500 = {'key': current_api_key[:8], 'status_code': status_code, 'error_message': error_message}
            log_msg = format_log_message('WARNING', f"{current_api_key[:8]} ... {current_api_key[-3:]} → 500 服务器内部错误", extra=extra_log_500)
            logger.warning(log_msg)
            
            return "Gemini API 内部错误"

        elif status_code == 503:
            error_message = "服务不可用"
            extra_log_503 = {'key': current_api_key[:8], 'status_code': status_code, 'error_message': error_message}
            log_msg = format_log_message('WARNING', f"{current_api_key[:8]} ... {current_api_key[-3:]} → 503 服务不可用", extra=extra_log_503)
            logger.warning(log_msg)
            
            return "Gemini API 服务不可用"
        else:
            error_message = f"未知错误: {status_code}"
            extra_log_other = {'key': current_api_key[:8], 'status_code': status_code, 'error_message': error_message}
            log_msg = format_log_message('WARNING', f"{current_api_key[:8]} ... {current_api_key[-3:]} → {status_code} 未知错误", extra=extra_log_other)
            logger.warning(log_msg)
            
            return f"未知错误/模型不可用: {status_code}"

    elif isinstance(error, requests.exceptions.ConnectionError):
        error_message = "连接错误"
        log_msg = format_log_message('WARNING', error_message, extra={'error_message': error_message})
        logger.warning(log_msg)
        return error_message

    elif isinstance(error, requests.exceptions.Timeout):
        error_message = "请求超时"
        log_msg = format_log_message('WARNING', error_message, extra={'error_message': error_message})
        logger.warning(log_msg)
        return error_message
    else:
        error_message = f"发生未知错误: {error}"
        log_msg = format_log_message('ERROR', error_message, extra={'error_message': error_message})
        logger.error(log_msg)
        return error_message


async def test_api_key(api_key: str) -> bool:
    """
    测试 API 密钥是否有效。
    """
    try:
        url = "https://generativelanguage.googleapis.com/v1beta/models?key={}".format(api_key)
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
            return True
    except Exception:
        return False


rate_limit_data = {}
rate_limit_lock = Lock()


def protect_from_abuse(request: Request, max_requests_per_minute: int = 30, max_requests_per_day_per_ip: int = 600):
    now = int(time.time())
    minute = now // 60
    day = now // (60 * 60 * 24)

    minute_key = f"{request.url.path}:{minute}"
    day_key = f"{request.client.host}:{day}"

    with rate_limit_lock:
        # 清理过期的速率限制数据（每100次请求执行一次）
        if len(rate_limit_data) > 0 and random.random() < 0.01:  # 1%的概率执行清理
            current_minute = now // 60
            current_day = now // (60 * 60 * 24)
            keys_to_remove = []
            
            for key, value in list(rate_limit_data.items()):
                try:
                    if not isinstance(value, tuple) or len(value) != 2:
                        # 数据格式不正确，标记为删除
                        keys_to_remove.append(key)
                        continue
                        
                    count, timestamp = value
                    
                    if ':' in key:
                        prefix, time_value = key.split(':', 1)
                        if time_value.isdigit():
                            time_value = int(time_value)
                            if ':' in prefix:  # 日级别键（包含IP地址）
                                if time_value < current_day - 1:  # 保留最近2天的数据
                                    keys_to_remove.append(key)
                            else:  # 分钟级别键
                                if time_value < current_minute - 10:  # 保留最近10分钟的数据
                                    keys_to_remove.append(key)
                except Exception as e:
                    # 处理过程中出现任何异常，标记该键为删除
                    logger.warning(f"清理速率限制数据时出错: {e}，将删除键: {key}")
                    keys_to_remove.append(key)
            
            for key in keys_to_remove:
                try:
                    del rate_limit_data[key]
                except KeyError:
                    pass  # 键可能已被删除
            
            if keys_to_remove:
                logger.debug(f"已清理 {len(keys_to_remove)} 条过期的速率限制记录，当前记录数: {len(rate_limit_data)}")
        
        minute_count, minute_timestamp = rate_limit_data.get(
            minute_key, (0, now))
        if now - minute_timestamp >= 60:
            minute_count = 0
            minute_timestamp = now
        minute_count += 1
        rate_limit_data[minute_key] = (minute_count, minute_timestamp)

        day_count, day_timestamp = rate_limit_data.get(day_key, (0, now))
        if now - day_timestamp >= 86400:
            day_count = 0
            day_timestamp = now
        day_count += 1
        rate_limit_data[day_key] = (day_count, day_timestamp)

    if minute_count > max_requests_per_minute:
        raise HTTPException(status_code=429, detail={
            "message": "Too many requests per minute", "limit": max_requests_per_minute})
    if day_count > max_requests_per_day_per_ip:
        raise HTTPException(status_code=429, detail={"message": "Too many requests per day from this IP", "limit": max_requests_per_day_per_ip})