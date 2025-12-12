# -*- coding: utf-8 -*-
"""
配置验证模块。
提供配置参数的验证和错误报告功能。
"""
import logging
from typing import List, Tuple
from urllib.parse import urlparse

from gap import config

logger = logging.getLogger("my_logger")


class ConfigValidationError(Exception):
    """配置验证错误"""

    pass


class ConfigValidator:
    """配置验证器"""

    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def validate_all(self) -> Tuple[bool, List[str], List[str]]:
        """验证所有配置项"""
        self.errors.clear()
        self.warnings.clear()

        # 验证基础配置
        self._validate_auth_config()
        self._validate_database_config()
        self._validate_cache_config()
        self._validate_timeout_config()
        self._validate_model_config()
        self._validate_api_config()
        self._validate_security_config()
        self._validate_logging_config()
        self._validate_service_config()

        is_valid = len(self.errors) == 0

        # 记录验证结果
        if not is_valid:
            logger.error("配置验证失败:")
            for error in self.errors:
                logger.error(f"  - {error}")

        if self.warnings:
            logger.warning("配置验证警告:")
            for warning in self.warnings:
                logger.warning(f"  - {warning}")

        if is_valid and not self.warnings:
            logger.info("配置验证通过，所有设置正确")

        return is_valid, self.errors, self.warnings

    def _validate_auth_config(self) -> None:
        """验证认证相关配置"""
        # SECRET_KEY 验证
        if hasattr(config, "AUTH_ENABLED") and not config.AUTH_ENABLED:
            self.warnings.append("AUTH_ENABLED 为 False，认证功能已禁用")

        # JWT 配置验证
        if not hasattr(config, "JWT_ALGORITHM") or not config.JWT_ALGORITHM:
            self.errors.append("JWT_ALGORITHM 必须设置")
        elif config.JWT_ALGORITHM not in [
            "HS256",
            "HS384",
            "HS512",
            "RS256",
            "RS384",
            "RS512",
        ]:
            self.warnings.append(
                f"JWT算法 {config.JWT_ALGORITHM} 可能不被支持，建议使用 HS256"
            )

        if (
            not hasattr(config, "ACCESS_TOKEN_EXPIRE_MINUTES")
            or config.ACCESS_TOKEN_EXPIRE_MINUTES <= 0
        ):
            self.errors.append("ACCESS_TOKEN_EXPIRE_MINUTES 必须为正整数")
        elif config.ACCESS_TOKEN_EXPIRE_MINUTES > 1440:  # 24小时
            self.warnings.append("访问令牌过期时间过长，建议不超过24小时")

        # Web UI 密码验证
        if hasattr(config, "WEB_UI_PASSWORDS") and config.WEB_UI_PASSWORDS:
            for password in config.WEB_UI_PASSWORDS:
                if len(password) < 8:
                    self.warnings.append(
                        "Web UI 密码长度短于8个字符，建议使用更强的密码"
                    )
                elif password in ["password", "admin", "123456", "test"]:
                    self.errors.append(
                        f"Web UI 密码 '{password}' 过于常见，存在安全风险"
                    )

    def _validate_database_config(self) -> None:
        """验证数据库配置"""
        if not hasattr(config, "DATABASE_URL"):
            self.errors.append("DATABASE_URL 必须设置")
            return

        db_url = config.DATABASE_URL
        if not isinstance(db_url, str) or not db_url.strip():
            self.errors.append("DATABASE_URL 必须为有效的字符串")
            return

        try:
            parsed = urlparse(db_url)
            if parsed.scheme not in ["postgresql", "postgresql+asyncpg"]:
                self.warnings.append(
                    f"数据库类型 '{parsed.scheme}' 可能不被支持，建议使用 PostgreSQL"
                )

            if not parsed.hostname:
                self.errors.append("数据库 URL 中缺少主机地址")

            if parsed.port and (parsed.port < 1 or parsed.port > 65535):
                self.errors.append("数据库端口号必须在 1-65535 范围内")

        except Exception as e:
            self.errors.append(f"DATABASE_URL 格式无效: {e}")

    def _validate_cache_config(self) -> None:
        """验证缓存配置"""
        # 缓存刷新间隔验证
        if hasattr(config, "CACHE_REFRESH_INTERVAL_SECONDS"):
            interval = config.CACHE_REFRESH_INTERVAL_SECONDS
            if interval <= 0:
                self.errors.append("CACHE_REFRESH_INTERVAL_SECONDS 必须为正整数")
            elif interval < 60:  # 小于1分钟
                self.warnings.append("缓存刷新间隔时间过短，可能影响性能")
            elif interval > 3600:  # 大于1小时
                self.warnings.append("缓存刷新间隔时间过长，可能导致数据不及时")

        # 上下文存储模式验证
        if hasattr(config, "CONTEXT_STORAGE_MODE"):
            mode = config.CONTEXT_STORAGE_MODE
            if mode not in ["memory", "database"]:
                self.errors.append("CONTEXT_STORAGE_MODE 必须为 'memory' 或 'database'")

            if mode == "database" and not hasattr(config, "CONTEXT_DB_PATH"):
                self.warnings.append(
                    "CONTEXT_STORAGE_MODE 为 'database' 但 CONTEXT_DB_PATH 未设置，将使用内存模式"
                )

        # 上下文TTL验证
        if hasattr(config, "DEFAULT_CONTEXT_TTL_DAYS"):
            ttl = config.DEFAULT_CONTEXT_TTL_DAYS
            if ttl <= 0:
                self.errors.append("DEFAULT_CONTEXT_TTL_DAYS 必须为正整数")
            elif ttl > 365:  # 大于1年
                self.warnings.append("上下文TTL时间过长，建议不超过1年")

    def _validate_timeout_config(self) -> None:
        """验证超时配置"""
        timeout_configs = [
            ("HTTP_TIMEOUT_CONNECT", config.HTTP_TIMEOUT_CONNECT, 1, 60),
            ("HTTP_TIMEOUT_READ", config.HTTP_TIMEOUT_READ, 5, 300),
            ("HTTP_TIMEOUT_WRITE", config.HTTP_TIMEOUT_WRITE, 5, 300),
            ("HTTP_TIMEOUT_POOL", config.HTTP_TIMEOUT_POOL, 5, 300),
            ("API_TIMEOUT_MODELS_LIST", config.API_TIMEOUT_MODELS_LIST, 10, 600),
            ("API_TIMEOUT_KEY_TEST", config.API_TIMEOUT_KEY_TEST, 1, 60),
        ]

        for name, value, min_val, max_val in timeout_configs:
            if not hasattr(config, name):
                continue

            if value <= 0:
                self.errors.append(f"{name} 必须为正数")
            elif value < min_val:
                self.warnings.append(f"{name} 值过小 ({value}s)，建议至少 {min_val}s")
            elif value > max_val:
                self.warnings.append(f"{name} 值过大 ({value}s)，建议不超过 {max_val}s")

    def _validate_model_config(self) -> None:
        """验证模型配置"""
        if not hasattr(config, "MODEL_LIMITS") or not config.MODEL_LIMITS:
            self.warnings.append("MODEL_LIMITS 为空，模型限制可能无法正常工作")
            return

        # 使用增强的模型限制验证函数
        try:
            from gap.config import validate_model_limits

            is_valid, errors, warnings = validate_model_limits(config.MODEL_LIMITS)

            # 将验证结果添加到错误和警告列表
            self.errors.extend(errors)
            self.warnings.extend(warnings)

            if not is_valid:
                self.errors.append(
                    "模型限制配置验证失败，请检查model_limits.json文件格式和内容"
                )
            elif errors:
                self.warnings.append("模型限制配置验证通过，但发现一些问题，建议检查")
            else:
                logger.info(
                    f"模型限制配置验证通过，共加载 {len(config.MODEL_LIMITS)} 个模型"
                )

        except ImportError:
            # 如果无法导入验证函数，使用基础验证
            logger.warning("无法导入模型限制验证函数，使用基础验证")
            self._basic_model_config_validation()
        except Exception as e:
            logger.error(f"模型限制验证过程中发生错误: {e}", exc_info=True)
            self.errors.append(f"模型限制验证错误: {e}")

    def _basic_model_config_validation(self) -> None:
        """基础模型配置验证（fallback方法）"""
        required_fields = [
            "rpm",
            "rpd",
            "tpm_input",
            "tpd_input",
            "input_token_limit",
            "output_token_limit",
        ]
        for model_name, limits in config.MODEL_LIMITS.items():
            if not isinstance(limits, dict):
                self.errors.append(f"模型 '{model_name}' 的配置必须为字典类型")
                continue

            for field in required_fields:
                if field not in limits:
                    self.errors.append(f"模型 '{model_name}' 缺少必需字段 '{field}'")
                elif not isinstance(limits[field], (int, float)) or limits[field] <= 0:
                    self.errors.append(
                        f"模型 '{model_name}' 的字段 '{field}' 必须为正数"
                    )

            # 检查token限制合理性
            if "input_token_limit" in limits:
                limit = limits["input_token_limit"]
                if limit < 1000:
                    self.warnings.append(
                        f"模型 '{model_name}' 的输入token限制过低 ({limit})"
                    )
                elif limit > 2000000:  # 2M tokens
                    self.warnings.append(
                        f"模型 '{model_name}' 的输入token限制过高 ({limit})，请确认是否正确"
                    )

    def _validate_api_config(self) -> None:
        """验证API配置"""
        # API密钥存储模式验证
        if hasattr(config, "KEY_STORAGE_MODE"):
            mode = config.KEY_STORAGE_MODE
            if mode not in ["memory", "database"]:
                self.errors.append("KEY_STORAGE_MODE 必须为 'memory' 或 'database'")

        if config.KEY_STORAGE_MODE == "memory" and not hasattr(
            config, "GEMINI_API_KEYS"
        ):
            self.warnings.append(
                "KEY_STORAGE_MODE 为 'memory' 但 GEMINI_API_KEYS 未设置"
            )

        # 速率限制验证
        rate_limits = [
            ("MAX_REQUESTS_PER_MINUTE", config.MAX_REQUESTS_PER_MINUTE, 1, 10000),
            (
                "MAX_REQUESTS_PER_DAY_PER_IP",
                config.MAX_REQUESTS_PER_DAY_PER_IP,
                1,
                100000,
            ),
        ]

        for name, value, min_val, max_val in rate_limits:
            if not hasattr(config, name):
                continue

            if value < min_val:
                self.warnings.append(f"{name} 值过小，建议至少 {min_val}")
            elif value > max_val:
                self.warnings.append(f"{name} 值过大 ({value})，可能无法有效防止滥用")

        # ADMIN_API_KEY 验证
        if hasattr(config, "ADMIN_API_KEY") and config.ADMIN_API_KEY:
            admin_key = config.ADMIN_API_KEY
            if len(admin_key) < 20:
                self.warnings.append("管理员API密钥长度较短，建议使用更强的密钥")
            elif admin_key in ["admin", "test", "key"]:
                self.errors.append("管理员API密钥过于简单，存在安全风险")

    def _validate_security_config(self) -> None:
        """验证安全配置"""
        # 安全过滤配置
        if (
            hasattr(config, "DISABLE_SAFETY_FILTERING")
            and config.DISABLE_SAFETY_FILTERING
        ):
            self.warnings.append("安全过滤已禁用，请确保这是有意的配置")

        # 报告页面保护
        if hasattr(config, "PROTECT_STATUS_PAGE") and config.PROTECT_STATUS_PAGE:
            if not hasattr(config, "WEB_UI_PASSWORDS") or not config.WEB_UI_PASSWORDS:
                self.warnings.append("状态页面已启用密码保护，但未设置Web UI密码")

    def _validate_logging_config(self) -> None:
        """验证日志配置"""
        # 报告日志级别验证
        if hasattr(config, "REPORT_LOG_LEVEL_STR"):
            valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
            level = config.REPORT_LOG_LEVEL_STR
            if level not in valid_levels:
                self.errors.append(
                    f"REPORT_LOG_LEVEL '{level}' 无效，必须为: {', '.join(valid_levels)}"
                )

        # 报告间隔验证
        if hasattr(config, "USAGE_REPORT_INTERVAL_MINUTES"):
            interval = config.USAGE_REPORT_INTERVAL_MINUTES
            if interval <= 0:
                self.errors.append("USAGE_REPORT_INTERVAL_MINUTES 必须为正整数")
            elif interval < 5:
                self.warnings.append("报告生成间隔过短，可能影响性能")
            elif interval > 1440:  # 大于24小时
                self.warnings.append("报告生成间隔过长，可能导致数据延迟")

    def _validate_service_config(self) -> None:
        """验证服务配置"""
        # 文档启用状态
        if hasattr(config, "ENABLE_DOCS") and not config.ENABLE_DOCS:
            self.warnings.append("API文档已禁用，开发体验可能受影响")

        # 原生缓存配置
        if hasattr(config, "ENABLE_NATIVE_CACHING") and config.ENABLE_NATIVE_CACHING:
            if (
                hasattr(config, "ENABLE_CONTEXT_COMPLETION")
                and config.ENABLE_CONTEXT_COMPLETION
            ):
                self.warnings.append("原生缓存已启用，传统上下文补全将被禁用")

        # 粘性会话
        if hasattr(config, "ENABLE_STICKY_SESSION") and config.ENABLE_STICKY_SESSION:
            self.warnings.append("粘性会话已启用，可能影响负载均衡")


# 全局配置验证器实例
config_validator = ConfigValidator()


def validate_config() -> Tuple[bool, List[str], List[str]]:
    """验证配置的便捷函数"""
    return config_validator.validate_all()


def ensure_config_valid():
    """确保配置有效的便捷函数，失败时抛出异常"""
    is_valid, errors, warnings = validate_config()

    if not is_valid:
        raise ConfigValidationError(f"配置验证失败: {'; '.join(errors)}")

    return is_valid, errors, warnings
