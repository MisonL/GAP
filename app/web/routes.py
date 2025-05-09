# -*- coding: utf-8 -*-
"""
处理 Web UI 相关的路由，例如登录页面、状态/报告页面和管理界面（上下文、Key 管理）。
Handles Web UI related routes, such as the login page, status/report page, and management interfaces (context, key management).
"""
import logging # 导入日志模块
import asyncio # 导入异步 IO 库
from datetime import datetime, timezone, timedelta # 导入日期时间处理
from fastapi import APIRouter, Request, Form, Depends, HTTPException, status, Response, Body # 导入 FastAPI 相关组件
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse # 导入 FastAPI 响应类型
from fastapi.templating import Jinja2Templates # 导入 Jinja2 模板引擎
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials # 导入 HTTP Bearer 认证工具
from typing import Optional, Annotated, Dict, Any, List # 导入类型提示
import uuid # 导入 UUID 库 (可能用于生成 ID)
from pydantic import BaseModel, Field # 导入 Pydantic 模型和字段定义
from sqlalchemy import text, delete, select # 导入 SQLAlchemy text, delete, select 函数
from app import config # 导入应用配置
from app.config import ( # 导入具体的配置项
    PROTECT_STATUS_PAGE, # 是否保护状态页面 (可能已废弃)
    PASSWORD, # Web UI 登录密码 (可能已废弃，使用 WEB_UI_PASSWORDS)
    WEB_UI_PASSWORDS, # Web UI 登录密码列表
    ADMIN_API_KEY, # 管理员 API Key
    __version__, # 应用版本号
    REPORT_LOG_LEVEL_STR, # 报告日志级别字符串
    USAGE_REPORT_INTERVAL_MINUTES, # 使用情况报告间隔
    DISABLE_SAFETY_FILTERING, # 是否禁用安全过滤
    MAX_REQUESTS_PER_MINUTE, # 每分钟最大请求数 (可能用于 IP 限制)
    MAX_REQUESTS_PER_DAY_PER_IP, # 每日每 IP 最大请求数 (可能用于 IP 限制)
    KEY_STORAGE_MODE # Key 存储模式 ('memory' 或 'database')
)
from app.core.database import utils as db_utils # 导入数据库工具函数 (新路径)
from app.core.security.jwt import create_access_token # 导入 JWT 创建函数 (新路径)
from app.core.keys.utils import generate_random_key # 导入随机 Key 生成函数 (新路径)
from app.core.security.auth_dependencies import verify_jwt_token, verify_jwt_token_optional # 导入 JWT 验证依赖项 (新路径)
from app.core.reporting.reporter import report_usage # 导入报告生成函数 (新路径)
from app.core.dependencies import get_key_manager, get_db_session # 导入 Key 管理器和数据库会话依赖项 (路径不变)
from app.core.keys.manager import APIKeyManager # 导入 APIKeyManager 类型提示 (新路径)
# 导入 AsyncSession 用于类型提示
from sqlalchemy.ext.asyncio import AsyncSession
# 导入数据库模型，用于 delete_specific_context
from app.core.database.models import CachedContent, Setting, ApiKey # 导入 Setting 和 ApiKey 模型
import aiosqlite # 保留 aiosqlite 导入，以防其他地方用到

logger = logging.getLogger('my_logger') # 获取日志记录器实例
router = APIRouter(tags=["Web UI"]) # 创建 API 路由器实例，并打上 "Web UI" 标签

# 初始化 Jinja2 模板引擎，指定模板文件目录
templates = Jinja2Templates(directory="app/web/templates", autoescape=True) # autoescape=True 防止 XSS 攻击

# --- 登录和根路径 ---

# 根据 PROTECT_STATUS_PAGE 配置决定根路径是否需要认证
# dependencies_for_root = [] # 移除此逻辑，根路径（登录页）应始终可访问
# if config.PROTECT_STATUS_PAGE:
#     dependencies_for_root.append(Depends(verify_jwt_token))

@router.get("/", response_class=HTMLResponse, include_in_schema=False) # 移除了 dependencies=dependencies_for_root
async def root_get(request: Request):
    """
    处理根路径 GET 请求，显示登录页面 (`login.html`)。
    如果 PROTECT_STATUS_PAGE 为 True，则此路径需要认证。
    根据配置决定是否需要登录以及是否缺少管理员 Key。

    Args:
        request (Request): FastAPI 请求对象。

    Returns:
        HTMLResponse: 渲染后的登录页面。
    """
    # 检查是否配置了 Web UI 密码，以此判断是否需要登录
    login_required = bool(config.WEB_UI_PASSWORDS)
    # 检查是否配置了管理员 API Key
    admin_key_missing = not config.ADMIN_API_KEY
    # 渲染 login.html 模板，并传递必要的上下文变量
    response = templates.TemplateResponse(
        "login.html",
        {
            "request": request, # 必须传递 request 对象给模板上下文
            "login_required": login_required, # 是否需要显示密码输入框
            "admin_key_missing": admin_key_missing, # 是否提示管理员 Key 未设置
            "now": datetime.now(timezone.utc) # 传递当前时间 (UTC)
        }
    )
    return response


@router.post("/login", include_in_schema=False)
async def login_for_access_token(
    request: Request, # 注入 FastAPI 请求对象
    password: str = Form(...) # 从表单数据中获取 password 字段
):
    """
    处理登录表单的 POST 请求。
    验证提供的密码是否匹配环境变量 `PASSWORD` 或 `ADMIN_API_KEY`。
    如果验证成功，创建并返回包含 JWT 访问令牌的 JSON 响应。
    根据新的规则，不再设置 Cookie。

    Args:
        request (Request): FastAPI 请求对象。
        password (str): 从登录表单提交的密码/Key。

    Returns:
        JSONResponse: 包含 access_token 和 token_type 的 JSON 响应。

    Raises:
        HTTPException:
            - 503 Service Unavailable: 如果 Web UI 密码未配置。
            - 401 Unauthorized: 如果密码错误。
            - 500 Internal Server Error: 如果 JWT 创建失败。
    """
    # 检查 Web UI 密码是否已配置
    if not config.WEB_UI_PASSWORDS and not config.ADMIN_API_KEY: # 同时检查 ADMIN_API_KEY 是否也未设置
        logger.error("尝试登录，但 Web UI 密码 (PASSWORD/WEB_UI_PASSWORDS) 和 ADMIN_API_KEY 均未设置或为空。")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Web UI 登录未启用 (认证凭证未设置)",
        )

    is_admin_login = False
    password_value = password.strip()
    
    # 优先检查是否为 ADMIN_API_KEY 登录
    if config.ADMIN_API_KEY and password_value == config.ADMIN_API_KEY:
        is_admin_login = True
        logger.info(f"管理员 Key 登录尝试成功: {password_value[:8]}...")
        access_token_data = {"sub": password_value, "admin": True}
    # 然后检查是否为 WEB_UI_PASSWORDS 中的一个
    elif password_value in config.WEB_UI_PASSWORDS:
        logger.info(f"普通用户 Key 登录尝试成功: {password_value[:8]}...")
        access_token_data = {"sub": password_value}
    else:
        logger.warning(f"Web UI 登录失败：密码/Key {password_value[:8]}... 错误。")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="密码或Key错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        access_token = create_access_token(data=access_token_data)
        login_type = "管理员" if is_admin_login else "普通用户"
        logger.info(f"Web UI {login_type}登录成功，用户 Key: {password_value[:8]}... 已签发 JWT。")
        response = JSONResponse(content={"access_token": access_token, "token_type": "bearer"})
        return response
    except ValueError as e:
        logger.error(f"无法创建 JWT: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="无法生成认证令牌 (内部错误)")
    except Exception as e:
        logger.error(f"创建 JWT 时发生未知错误: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="生成认证令牌时出错")

# --- 辅助依赖函数，用于Web UI页面权限控制 ---
async def redirect_to_login_if_unauthorized(
    request: Request,
    token_payload: Optional[Dict[str, Any]] = Depends(verify_jwt_token_optional)
):
    """
    如果 PROTECT_STATUS_PAGE 为 True且用户未认证，则重定向到登录页。
    此依赖应用于渲染HTML页面的管理路由。
    """
    if config.PROTECT_STATUS_PAGE:
        # 检查是否是请求登录页本身或登录API，以避免重定向循环
        if request.url.path != router.url_path_for("root_get") and \
           request.url.path != router.url_path_for("login_for_access_token"):
            if not token_payload:
                logger.debug(f"用户未认证，且 PROTECT_STATUS_PAGE=True，从 {request.url.path} 重定向到登录页。")
                return RedirectResponse(url=router.url_path_for("root_get"), status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    return token_payload # 如果通过检查或不需要保护，则返回 token_payload 或 None

# --- 管理界面路由 ---

@router.get("/manage", include_in_schema=False)
async def manage_redirect():
    logger.debug("访问 /manage，重定向到 /manage/keys") # 默认重定向到 Key 管理页面
    return RedirectResponse(url="/manage/keys", status_code=status.HTTP_303_SEE_OTHER)

@router.get("/manage/context",response_class=HTMLResponse,include_in_schema=False, dependencies=[Depends(redirect_to_login_if_unauthorized)])
async def manage_context_page(request: Request):
    admin_key_missing = not config.ADMIN_API_KEY
    logger.debug("渲染上下文管理页面骨架")
    return templates.TemplateResponse(
        "manage_context.html",
        {
            "request": request,
            "admin_key_missing": admin_key_missing,
            "now": datetime.now(timezone.utc),
            "is_memory_db": db_utils.IS_MEMORY_DB
        }
    )

@router.get("/manage/report",response_class=HTMLResponse,include_in_schema=False, dependencies=[Depends(redirect_to_login_if_unauthorized)])
async def manage_report_page(request: Request):
    admin_key_missing = not config.ADMIN_API_KEY
    logger.debug("渲染报告页面骨架")
    return templates.TemplateResponse(
        "report.html",
        context={
            "request": request,
            "admin_key_missing": admin_key_missing,
            "now": datetime.now(timezone.utc),
            "report_log_level": REPORT_LOG_LEVEL_STR,
            "usage_report_interval": USAGE_REPORT_INTERVAL_MINUTES,
            "disable_safety_filtering": DISABLE_SAFETY_FILTERING,
            "max_requests_per_minute": MAX_REQUESTS_PER_MINUTE,
            "max_requests_per_day_per_ip": MAX_REQUESTS_PER_DAY_PER_IP,
            "app_version": __version__,
            "is_memory_db": db_utils.IS_MEMORY_DB,
            "key_selection_tracking": None
        }
    )

# --- Key 管理 API 的请求体模型 ---
class AddKeyRequest(BaseModel):
    description: Optional[str] = Field(None, description="新 Key 的描述 (可选)")
    expires_at: Optional[str] = Field(None, description="Key 过期时间 (ISO 格式, YYYY-MM-DDTHH:MM:SSZ 或 YYYY-MM-DDTHH:MM:SS+00:00)，留空或 null 表示永不过期")

class UpdateKeyRequest(BaseModel):
    description: Optional[str] = Field(None, description="新的描述 (可选)")
    is_active: Optional[bool] = Field(None, description="新的激活状态 (可选)")
    expires_at: Optional[str] = Field(None, description="新的 Key 过期时间 (ISO 格式)，留空或 null 表示永不过期")
    enable_context_completion: Optional[bool] = Field(None, description="是否启用上下文补全 (可选)")

class UpdateTTLRequest(BaseModel):
    ttl_seconds: int = Field(..., description="新的全局 TTL 秒数", ge=0)

# --- 管理员权限验证依赖项 ---
async def require_admin_user(token_payload: Dict[str, Any] = Depends(verify_jwt_token)):
    is_admin = token_payload.get("admin", False)
    if not is_admin:
        user_key = token_payload.get("sub", "未知用户")
        logger.warning(f"用户 {user_key[:8]}... 尝试访问管理员专属 API，操作被拒绝。")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅管理员有权限执行此操作。"
        )

# --- Key 管理页面路由 ---
@router.get("/manage/keys",response_class=HTMLResponse,include_in_schema=False, dependencies=[Depends(redirect_to_login_if_unauthorized)])
async def manage_keys_page(request: Request):
    key_storage_mode = config.KEY_STORAGE_MODE
    logger.debug(f"渲染 Key 管理页面骨架 (模式: {key_storage_mode})")
    admin_key_missing = not config.ADMIN_API_KEY
    return templates.TemplateResponse(
        "manage_keys.html",
        {
            "request": request,
            "key_storage_mode": key_storage_mode,
            "admin_key_missing": admin_key_missing,
            "now": datetime.now(timezone.utc),
            "admin_api_key_value": config.ADMIN_API_KEY # 将 ADMIN_API_KEY 的值传递给模板
        }
    )

# --- Key 管理 API 端点 ---
@router.get("/api/manage/keys/data", dependencies=[Depends(verify_jwt_token), Depends(require_admin_user)])
async def get_manage_keys_data(
    token_payload: Dict[str, Any] = Depends(verify_jwt_token),
    key_manager: APIKeyManager = Depends(get_key_manager),
    db: AsyncSession = Depends(get_db_session)
):
    user_key = token_payload.get('sub', '未知管理员')
    is_admin_status = token_payload.get("admin", False)
    logger.warning(f"当前 KEY_STORAGE_MODE 的运行时值为: {config.KEY_STORAGE_MODE}") # 添加 WARNING 级别日志
    logger.debug(f"管理员 {user_key[:8]}... 请求 Key 管理数据 (模式: {config.KEY_STORAGE_MODE})")
    result_keys = []
    try:
        if config.KEY_STORAGE_MODE == 'database':
            logger.debug("数据库模式：从数据库获取 Key 数据...")
            api_key_objects = await db_utils.get_all_api_keys_from_db(db)
            for key_obj in api_key_objects:
                result_keys.append({
                    "key": key_obj.key_string,
                    "description": key_obj.description,
                    "created_at": key_obj.created_at.strftime('%Y-%m-%d %H:%M:%S UTC') if key_obj.created_at else None,
                    "expires_at": key_obj.expires_at.isoformat() if key_obj.expires_at else None,
                    "is_active": key_obj.is_active,
                    "enable_context_completion": key_obj.enable_context_completion,
                    "user_id": key_obj.user_id,
                    "is_protected": key_obj.key_string == config.ADMIN_API_KEY # 添加保护标记
                })
            logger.info(f"数据库模式：成功获取 {len(result_keys)} 个 Key 数据。")
        elif config.KEY_STORAGE_MODE == 'memory':
            logger.debug("内存模式：构建代理凭证列表 (ADMIN_API_KEY, WEB_UI_PASSWORDS, 及临时添加的)")
            # 临时添加的 Key 应该优先显示
            temp_added_keys_list = []
            env_keys_list = []
            processed_keys_set = set() # 用于跟踪已处理的 Key，避免重复

            # 1. 处理通过 UI 临时添加的 Key (来自 key_manager.key_configs)
            # 将整个处理过程移到锁内，以确保数据一致性
            with key_manager.keys_lock:
                current_key_configs = key_manager.key_configs.copy() # 仍然拷贝以避免直接修改原始数据影响其他可能的并发读
                
                logger.debug(f"内存模式 - current_key_configs 内容 (锁内): {current_key_configs}")

                for key_string, key_config_data in current_key_configs.items():
                    logger.debug(f"内存模式 - 检查 Key (锁内): {key_string[:8]}..., Config: {key_config_data}, _ui_generated: {key_config_data.get('_ui_generated')}")
                    if key_config_data.get('_ui_generated') is True:
                        temp_added_keys_list.append({
                            "key": key_string,
                            "description": key_config_data.get('description', "临时添加 (UI)"),
                            "created_at": key_config_data.get('created_at'),
                            "expires_at": key_config_data.get('expires_at'),
                            "is_active": key_config_data.get('is_active', True),
                            "enable_context_completion": key_config_data.get('enable_context_completion', True),
                            "user_id": key_config_data.get('user_id'),
                            "is_protected": False
                        })
                        processed_keys_set.add(key_string)
                    # else:
                        # logger.debug(f"内存模式：Key {key_string[:8]}... 不是 UI 生成的，或者缺少标记。Config: {key_config_data}")

            # 2. 处理来自环境变量的 ADMIN_API_KEY (这部分不需要在 key_manager.keys_lock 内，因为它读取的是 config)
            if config.ADMIN_API_KEY and config.ADMIN_API_KEY not in processed_keys_set:
                env_keys_list.append({
                    "key": config.ADMIN_API_KEY,
                    "description": "管理员 Key (来自环境变量 ADMIN_API_KEY)",
                    "created_at": "N/A (环境变量)",
                    "expires_at": None, # 管理员 Key 永不过期
                    "is_active": True,  # 管理员 Key 总是激活
                    "enable_context_completion": True, # 管理员 Key 默认启用上下文
                    "user_id": "admin",
                    "is_protected": True # 标记为受保护
                })
                processed_keys_set.add(config.ADMIN_API_KEY)

            # 3. 处理来自环境变量的 WEB_UI_PASSWORDS
            for pwd in config.WEB_UI_PASSWORDS:
                if pwd not in processed_keys_set: # 避免重复添加 (例如，如果密码与 ADMIN_API_KEY 相同)
                    env_keys_list.append({
                        "key": pwd,
                        "description": "用户密码/代理凭证 (来自环境变量 WEB_UI_PASSWORDS)",
                        "created_at": "N/A (环境变量)",
                        "expires_at": None,
                        "is_active": True,
                        "enable_context_completion": True, # 默认启用
                        "user_id": None, # 环境变量中的密码通常没有 user_id
                        "is_protected": False # 这些不是管理员 Key，但来自环境变量，删除时也应受保护
                    })
                    processed_keys_set.add(pwd)
            
            # 合并列表，临时添加的在前
            result_keys = temp_added_keys_list + env_keys_list
            
            # 按创建时间排序，确保 UI 添加的 Key 在最前面，环境变量的在后面
            # N/A (环境变量) 会被排在后面
            try:
                result_keys.sort(
                    key=lambda x: (
                        x.get('created_at') == "N/A (环境变量)", # False (0) 在前, True (1) 在后
                        datetime.fromisoformat(x.get('created_at')) if x.get('created_at') and x.get('created_at') != "N/A (环境变量)" else datetime.min.replace(tzinfo=timezone.utc)
                    ),
                    reverse=True # 最新的在前
                )
            except Exception as sort_err:
                logger.warning(f"内存模式 Key 列表排序失败: {sort_err}")

            logger.info(f"内存模式：构建了 {len(result_keys)} 个代理凭证/临时Key列表。")
        else:
            logger.error(f"无效的 KEY_STORAGE_MODE 配置: {config.KEY_STORAGE_MODE}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="服务器配置错误：无效的 Key 存储模式")

        return {
            "keys": result_keys,
            "total_keys": len(result_keys),
            "is_admin": is_admin_status,
            "key_storage_mode": config.KEY_STORAGE_MODE
        }
    except Exception as e:
        logger.error(f"管理员 {user_key[:8]}... 获取 Key 管理数据时出错 (模式: {config.KEY_STORAGE_MODE}): {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取 Key 数据失败")

@router.post("/api/manage/keys/add",status_code=status.HTTP_201_CREATED,dependencies=[Depends(verify_jwt_token), Depends(require_admin_user)])
async def add_new_key(
    request_data: AddKeyRequest,
    token_payload: Dict[str, Any] = Depends(verify_jwt_token),
    key_manager: APIKeyManager = Depends(get_key_manager),
    db: AsyncSession = Depends(get_db_session)
):
    admin_user = token_payload.get('sub', '未知管理员')
    logger.info(f"管理员 {admin_user[:8]}... 尝试添加新 Key (模式: {config.KEY_STORAGE_MODE})")
    new_key_string = generate_random_key()
    expires_at_dt: Optional[datetime] = None
    if request_data.expires_at:
        try:
            expires_at_dt = datetime.fromisoformat(request_data.expires_at.replace('Z', '+00:00'))
            if expires_at_dt.tzinfo is None:
                expires_at_dt = expires_at_dt.replace(tzinfo=timezone.utc)
            else:
                expires_at_dt = expires_at_dt.astimezone(timezone.utc)
        except ValueError:
            logger.warning(f"添加 Key 时提供的过期时间格式无效: {request_data.expires_at}")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="过期时间格式无效，请使用 ISO 8601 格式 (例如 YYYY-MM-DDTHH:MM:SSZ)。")

    if config.KEY_STORAGE_MODE == 'database':
        added_key_obj = await db_utils.add_api_key(
            db=db, key_string=new_key_string, description=request_data.description,
            expires_at=expires_at_dt, is_active=True, enable_context_completion=True
        )
        if not added_key_obj:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="无法将 Key 添加到数据库。")
        await key_manager.reload_keys(db)
        logger.info(f"数据库模式：添加 Key {new_key_string[:8]}... 后已调用 reload_keys。")
        return {
            "message": "Key 添加成功。",
            "key": {
                "key": added_key_obj.key_string, "description": added_key_obj.description,
                "created_at": added_key_obj.created_at.strftime('%Y-%m-%d %H:%M:%S UTC') if added_key_obj.created_at else None,
                "expires_at": added_key_obj.expires_at.isoformat() if added_key_obj.expires_at else None,
                "is_active": added_key_obj.is_active,
                "enable_context_completion": added_key_obj.enable_context_completion,
                "user_id": added_key_obj.user_id
            }
        }
    elif config.KEY_STORAGE_MODE == 'memory':
        config_data = {
            'description': request_data.description or "内存模式添加 (UI)",
            'is_active': True,
            'expires_at': expires_at_dt.isoformat() if expires_at_dt else None,
            'enable_context_completion': True,
            'user_id': None, 
            'created_at': datetime.now(timezone.utc).isoformat() # 记录创建时间
        }
        # 在内存模式下，add_key_memory 是将 Key 添加到 key_manager.key_configs
        # 这个 key_configs 用于存储那些非环境变量的、临时的“代理凭证”
        success = key_manager.add_key_memory(new_key_string, config_data) # 使用 add_key_memory
        if not success:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="无法将 Key 添加到内存。")
        return {
            "message": "Key 已临时添加到内存 (重启后将丢失)。",
            "key": {
                "key": new_key_string, "description": config_data['description'],
                "created_at": config_data['created_at'], "expires_at": config_data['expires_at'],
                "is_active": config_data['is_active'],
                "enable_context_completion": config_data['enable_context_completion'],
                "user_id": config_data['user_id']
            }
        }
    else:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="服务器配置错误：无效的 Key 存储模式")

@router.put("/api/manage/keys/update/{key_string}",dependencies=[Depends(verify_jwt_token), Depends(require_admin_user)])
async def update_existing_key(
    key_string: str, request_data: UpdateKeyRequest,
    token_payload: Dict[str, Any] = Depends(verify_jwt_token),
    key_manager: APIKeyManager = Depends(get_key_manager),
    db: AsyncSession = Depends(get_db_session)
):
    admin_user = token_payload.get('sub', '未知管理员')
    logger.info(f"管理员 {admin_user[:8]}... 尝试更新 Key {key_string[:8]}... (模式: {config.KEY_STORAGE_MODE})")

    updates_to_apply = {}
    # 检查是否尝试修改受保护的 ADMIN_API_KEY 的敏感字段
    if key_string == config.ADMIN_API_KEY:
        # 检查是否有对 is_active 或 expires_at 的修改请求
        attempted_sensitive_update = False
        if 'is_active' in request_data.model_fields_set and request_data.is_active is False: # 尝试禁用
            attempted_sensitive_update = True
        if 'expires_at' in request_data.model_fields_set: # 任何对 expires_at 的尝试都算
            attempted_sensitive_update = True
        
        if attempted_sensitive_update:
            logger.warning(f"管理员 {admin_user[:8]}... 尝试修改 ADMIN_API_KEY 的受保护字段 (is_active 或 expires_at)。")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="管理员 Key 的激活状态不能被禁用，过期时间不能被设置。")
        
        # 管理员 Key 只允许修改 description 和 enable_context_completion
        if 'description' in request_data.model_fields_set:
            updates_to_apply['description'] = request_data.description
        if 'enable_context_completion' in request_data.model_fields_set:
            updates_to_apply['enable_context_completion'] = request_data.enable_context_completion
        
        if not updates_to_apply: # 如果没有允许的字段被更新
             logger.info(f"管理员 {admin_user[:8]}... 对 ADMIN_API_KEY 的更新请求未包含允许修改的字段。")
             return {"message": "管理员 Key 只能修改描述或上下文补全设置，未提供相关更新。"}
    else: # 非 ADMIN_API_KEY
        updates_to_apply = request_data.model_dump(exclude_unset=True)
        # 解析和验证过期时间
        if 'expires_at' in updates_to_apply:
            expires_at_str = updates_to_apply['expires_at']
            if expires_at_str is None:
                updates_to_apply['expires_at'] = None # 明确设置为 None
            elif isinstance(expires_at_str, str):
                try:
                    expires_at_dt = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
                    updates_to_apply['expires_at'] = expires_at_dt.astimezone(timezone.utc) if expires_at_dt.tzinfo else expires_at_dt.replace(tzinfo=timezone.utc)
                except ValueError:
                    logger.warning(f"更新 Key 时提供的过期时间格式无效: {expires_at_str}")
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="过期时间格式无效，请使用 ISO 8601 格式或 null。")
            else: # 如果 expires_at 不是字符串也不是 None，则忽略此字段的更新
                 logger.warning(f"更新 Key 时提供的 expires_at 类型无效: {type(expires_at_str)}，已忽略。")
                 del updates_to_apply['expires_at']

    if not updates_to_apply:
        logger.info(f"管理员 {admin_user[:8]}... 对 Key {key_string[:8]}... 的更新请求未包含有效或允许更新的字段。")
        return {"message": "没有提供有效或允许更新的字段。"}

    if config.KEY_STORAGE_MODE == 'database':
        updated_key_obj = await db_utils.update_api_key(db, key_string, updates_to_apply)
        if not updated_key_obj:
            existing_key = await db_utils.get_api_key_by_string(db, key_string)
            if not existing_key:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"未找到 Key: {key_string[:8]}...")
            else: # Key 存在但更新失败
                logger.error(f"数据库模式：更新 Key {key_string[:8]}... 失败，但 Key 存在。Updates: {updates_to_apply}")
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="更新数据库中的 Key 失败。")
        await key_manager.reload_keys(db)
        logger.info(f"数据库模式：更新 Key {key_string[:8]}... 后已调用 reload_keys。")
        return {"message": "Key 更新成功。", "key": updated_key_obj}
    elif config.KEY_STORAGE_MODE == 'memory':
        # 对于内存模式，ADMIN_API_KEY 和 WEB_UI_PASSWORDS 的配置是只读的，不能通过此接口修改
        # 除了 description 和 enable_context_completion (对于 ADMIN_API_KEY)
        if key_string == config.ADMIN_API_KEY:
            # 之前已经处理了只允许 description 和 enable_context_completion
            pass # updates_to_apply 已经只包含允许的字段
        elif key_string in config.WEB_UI_PASSWORDS:
            logger.warning(f"管理员 {admin_user[:8]}... 尝试修改来自环境变量 WEB_UI_PASSWORDS 的内存 Key {key_string[:8]}...，操作被拒绝。")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="来自环境变量 WEB_UI_PASSWORDS 的 Key 配置不能通过此接口修改。")

        success = key_manager.update_key_memory(key_string, updates_to_apply)
        if not success:
            # 检查 Key 是否存在于 key_configs (UI 添加的) 或环境变量中
            if key_string not in key_manager.key_configs and key_string != config.ADMIN_API_KEY and key_string not in config.WEB_UI_PASSWORDS:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"未找到要更新的内存 Key: {key_string[:8]}...")
            else: # Key 存在但更新失败 (例如，尝试修改环境变量中密码的敏感字段)
                logger.error(f"内存模式：更新 Key {key_string[:8]}... 失败。Updates: {updates_to_apply}")
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="更新内存中的 Key 配置失败。")

        updated_config = key_manager.get_key_config(key_string) # 获取更新后的配置
        if not updated_config: # 如果更新后获取不到，说明可能被删除了或出错了
             raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"更新后无法找到内存 Key: {key_string[:8]}...")

        response_key_info = {
            "key": key_string,
            "description": updated_config.get('description'), "created_at": updated_config.get('created_at'),
            "expires_at": updated_config.get('expires_at'), "is_active": updated_config.get('is_active'),
            "enable_context_completion": updated_config.get('enable_context_completion'),
            "user_id": updated_config.get('user_id'),
            "is_protected": key_string == config.ADMIN_API_KEY
        }
        return {"message": "内存 Key 配置已临时更新 (重启后将丢失)。", "key": response_key_info}
    else:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="服务器配置错误：无效的 Key 存储模式")

@router.delete("/api/manage/keys/delete/{key_string}",status_code=status.HTTP_204_NO_CONTENT,dependencies=[Depends(verify_jwt_token), Depends(require_admin_user)])
async def delete_existing_key(
    key_string: str,
    token_payload: Dict[str, Any] = Depends(verify_jwt_token),
    key_manager: APIKeyManager = Depends(get_key_manager),
    db: AsyncSession = Depends(get_db_session)
):
    admin_user = token_payload.get('sub', '未知管理员')
    logger.info(f"管理员 {admin_user[:8]}... 尝试删除 Key {key_string[:8]}... (模式: {config.KEY_STORAGE_MODE})")

    if key_string == config.ADMIN_API_KEY:
        logger.warning(f"管理员 {admin_user[:8]}... 尝试删除受保护的 ADMIN_API_KEY，操作被拒绝。")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="管理员 Key (ADMIN_API_KEY) 不能被删除。")

    if config.KEY_STORAGE_MODE == 'database':
        # 在数据库模式下，ADMIN_API_KEY 理论上不应该在 ApiKey 表中，除非手动添加
        # 但如果存在，上面的检查已经阻止了删除
        deleted_from_db = await db_utils.delete_api_key(db, key_string)
        if not deleted_from_db:
            existing_key = await db_utils.get_api_key_by_string(db, key_string)
            if not existing_key:
                 raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"未找到要删除的 Key: {key_string[:8]}...")
            else: # Key 存在但删除失败
                 logger.error(f"数据库模式：删除 Key {key_string[:8]}... 失败，但 Key 存在。")
                 raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="从数据库删除 Key 失败。")
        await key_manager.reload_keys(db)
        logger.info(f"数据库模式：删除 Key {key_string[:8]}... 后已调用 reload_keys。")
    elif config.KEY_STORAGE_MODE == 'memory':
        # 对于内存模式，需要确保删除的是 UI 临时添加的 Key，
        # 而不是环境变量中的 ADMIN_API_KEY 或 WEB_UI_PASSWORDS
        if key_string == config.ADMIN_API_KEY: # 双重检查，理论上已被上面的 if 捕获
            logger.warning(f"管理员 {admin_user[:8]}... 再次尝试删除受保护的 ADMIN_API_KEY (内存模式)，操作被拒绝。")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="管理员 Key (ADMIN_API_KEY) 不能通过此接口删除。")
        if key_string in config.WEB_UI_PASSWORDS:
            logger.warning(f"管理员 {admin_user[:8]}... 尝试删除来自环境变量 WEB_UI_PASSWORDS 的内存 Key {key_string[:8]}...，操作被拒绝。")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="来自环境变量 WEB_UI_PASSWORDS 的 Key 不能通过此接口删除。")
        
        # delete_key_memory 只会删除 key_manager.key_configs 中的 Key
        deleted_from_memory = key_manager.delete_key_memory(key_string)
        if not deleted_from_memory:
            # 检查是否是因为 Key 根本不存在于 key_configs 中
            if key_string not in key_manager.key_configs:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"未找到要删除的临时内存 Key: {key_string[:8]}...")
            else: # Key 存在于 key_configs 但删除失败
                logger.error(f"内存模式：删除临时 Key {key_string[:8]}... 失败，但 Key 存在于 key_configs。")
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="从内存删除临时 Key 失败。")
        logger.info(f"内存模式：临时 Key {key_string[:8]}... 已从 key_manager.key_configs 中删除。")
    else:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="服务器配置错误：无效的 Key 存储模式")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Context Management API Endpoints --- (上下文管理 API 端点)
# 注意：这些端点目前使用了 aiosqlite.Connection，可能需要调整以使用 AsyncSession

@router.get(
    "/api/manage/context/data", # API 端点路径
    dependencies=[Depends(verify_jwt_token), Depends(require_admin_user)]) # 需要管理员权限
async def get_manage_context_data(
    token_payload: Dict[str, Any] = Depends(verify_jwt_token), # 注入 JWT payload
    db: AsyncSession = Depends(get_db_session) # 修改类型提示为 AsyncSession
):
    """
    API 端点：获取用于上下文管理页面的数据。
    需要管理员权限。
    从数据库获取所有上下文记录（或管理员自己的记录）。
    """
    user_key = token_payload.get('sub', '未知管理员') # 获取管理员标识
    logger.debug(f"管理员 {user_key[:8]}... 请求上下文管理数据") # 记录日志
    try:
        # --- 获取全局 TTL ---
        from app.core.database.settings import get_setting # 导入 get_setting
        # 调用 get_setting 时需要传递 db 会话
        global_ttl_seconds_str = await get_setting(db, "global_context_ttl_seconds") # 传递 db 参数
        # 提供默认值（转换为秒）
        global_ttl_seconds = int(global_ttl_seconds_str) if global_ttl_seconds_str else config.DEFAULT_CONTEXT_TTL_DAYS * 86400

        # --- 获取上下文记录 (使用 SQLAlchemy Core API) ---
        # 构建 SQLAlchemy 查询语句 (使用 text() 包装)
        # 构建 SQLAlchemy 查询语句 (使用 text() 包装)
        # 注意：查询 cached_contents 表，并调整列名以匹配模型
        stmt = text("""
            SELECT
                id,                     -- 数据库 ID
                user_id,                -- 用户 ID
                content_id AS context_key, -- 使用 content_id 作为 context_key
                content AS context_value, -- 上下文内容
                creation_timestamp AS created_at, -- 创建时间
                creation_timestamp AS last_accessed_at, -- 使用创建时间作为最后访问时间（需要改进）
                (expiration_timestamp - creation_timestamp) AS ttl_seconds, -- 计算 TTL
                0 AS access_count        -- 访问次数 (模型中无此字段，设为 0)
            FROM
                cached_contents
            ORDER BY
                creation_timestamp DESC -- 按创建时间降序排序
        """)
        # 执行查询 (不再需要传递 ttl 参数，因为它已包含在 SELECT 中)
        result = await db.execute(stmt)
        contexts_raw = result.mappings().all() # 获取所有行作为字典列表
        contexts = [dict(row) for row in contexts_raw] # 转换为普通字典列表

        # 格式化时间戳 (从 Unix float 转换为字符串)
        for context in contexts:
            for field in ['created_at', 'last_accessed_at']:
                if context[field]:
                    try:
                        # 将 Unix 时间戳转换为 datetime 对象
                        dt_obj = datetime.fromtimestamp(context[field], tz=timezone.utc)
                        # 格式化为易读字符串
                        context[field] = dt_obj.strftime('%Y-%m-%d %H:%M:%S UTC')
                    except (ValueError, TypeError, OSError): # 添加 OSError 以处理无效时间戳
                        logger.warning(f"无法解析上下文 {context.get('context_key', 'N/A')} 的时间戳字段 {field}: {context[field]}")
                        context[field] = "解析错误" # 标记解析错误

        is_admin_status = token_payload.get("admin", False) # 获取管理员状态
        # 返回数据
        return {"contexts": contexts, "global_ttl": global_ttl_seconds, "is_admin": is_admin_status, "is_memory_db": db_utils.IS_MEMORY_DB}
    except Exception as e: # 捕获异常
        logger.error(f"管理员 {user_key[:8]}... 获取上下文管理数据时出错: {e}", exc_info=True) # 记录错误
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取上下文数据失败") # 抛出 500 错误

@router.post(
    "/api/manage/context/update_ttl", # API 端点路径
    dependencies=[Depends(verify_jwt_token), Depends(require_admin_user)] # 需要管理员权限
)
async def update_global_context_ttl(
    request_data: UpdateTTLRequest, # 请求体，包含新的 TTL 秒数
    token_payload: Dict[str, Any] = Depends(verify_jwt_token), # 注入 JWT payload
    db: AsyncSession = Depends(get_db_session) # 注入 AsyncSession
):
    """
    API 端点：更新全局上下文 TTL (生存时间) 设置。
    需要管理员权限。

    Args:
        request_data (UpdateTTLRequest): 请求体，包含 `ttl_seconds` 字段。
        token_payload (Dict[str, Any]): 已验证的管理员 JWT payload。
        db (AsyncSession): 注入的数据库会话。

    Returns:
        Dict[str, Any]: 包含成功消息和新 TTL 值的字典。

    Raises:
        HTTPException: 如果 TTL 值无效或更新失败。
    """
    user_key = token_payload.get('sub', '未知管理员') # 获取管理员标识
    new_ttl_seconds = request_data.ttl_seconds # 获取新的 TTL 秒数
    logger.info(f"管理员 {user_key[:8]}... 尝试将全局上下文 TTL 更新为 {new_ttl_seconds} 秒") # 记录日志

    # 验证 TTL 值是否为非负数
    if new_ttl_seconds < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="TTL 值不能为负数。") # 抛出 400 错误

    try:
        # --- 调用 settings 模块中的 set_setting 函数 ---
        from app.core.database.settings import set_setting # 导入正确的 set_setting 函数
        # 调用更新函数，传递 db, key, value
        await set_setting(db, "global_context_ttl_seconds", str(new_ttl_seconds))
        logger.info(f"全局上下文 TTL 已成功更新为 {new_ttl_seconds} 秒。") # 记录成功日志
        # 返回成功响应
        return {"message": f"全局上下文 TTL 已更新为 {new_ttl_seconds} 秒。", "new_ttl": new_ttl_seconds}
    except ValueError as ve: # 捕获可能的验证错误
        logger.warning(f"管理员 {user_key[:8]}... 更新全局上下文 TTL 时输入无效: {ve}") # 将 ERROR 修改为 WARNING
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e: # 捕获更新过程中的异常
        logger.error(f"管理员 {user_key[:8]}... 更新全局上下文 TTL 时出错: {e}", exc_info=True) # 记录错误
        # await db.rollback() # 假设 set_setting 内部处理回滚
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="更新 TTL 失败。") # 抛出 500 错误

class DeleteContextRequest(BaseModel):
    """删除上下文请求的模型"""
    context_id: int # 要删除的上下文记录的数据库 ID

@router.post(
    "/api/manage/context/delete", # API 端点路径
    dependencies=[Depends(verify_jwt_token), Depends(require_admin_user)] # 需要管理员权限
)
async def delete_specific_context(
    request_data: DeleteContextRequest, # 请求体，包含要删除的 context_id
    token_payload: Dict[str, Any] = Depends(verify_jwt_token), # 注入 JWT payload
    db: AsyncSession = Depends(get_db_session) # 确认类型提示为 AsyncSession
):
    """
    API 端点：删除指定的上下文条目。
    需要管理员权限。
    使用 SQLAlchemy Core API 进行删除。

    Args:
        request_data (DeleteContextRequest): 请求体，包含 `context_id`。
        token_payload (Dict[str, Any]): 已验证的管理员 JWT payload。
        db (AsyncSession): 注入的数据库会话。

    Returns:
        Dict[str, str]: 包含成功消息的字典。

    Raises:
        HTTPException: 如果未找到条目或删除失败。
    """
    user_key = token_payload.get('sub', '未知管理员') # 获取管理员标识
    context_id_to_delete = request_data.context_id # 获取要删除的 ID
    logger.info(f"管理员 {user_key[:8]}... 尝试删除上下文条目 ID: {context_id_to_delete}") # 记录日志

    try:
        # --- 使用 SQLAlchemy Core API 删除 ---
        # 构建删除语句，根据 ID 删除 CachedContent 记录
        stmt = delete(CachedContent).where(CachedContent.id == context_id_to_delete)
        # 执行删除语句
        result = await db.execute(stmt)
        # 提交事务以保存更改
        await db.commit()

        # 检查是否有行被删除
        if result.rowcount > 0:
            logger.info(f"上下文条目 ID: {context_id_to_delete} 已成功删除。") # 记录成功日志
            return {"message": f"上下文条目 ID: {context_id_to_delete} 已成功删除。"} # 返回成功消息
        else:
            # 如果没有行被删除，说明该 ID 不存在
            logger.warning(f"尝试删除不存在的上下文条目 ID: {context_id_to_delete}") # 记录警告
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到指定的上下文条目。") # 抛出 404 错误

    except HTTPException: # 重新抛出已知的 HTTPException (例如 404)
        raise
    except Exception as e: # 捕获其他可能的数据库或未知异常
        logger.error(f"管理员 {user_key[:8]}... 删除上下文条目 ID {context_id_to_delete} 时出错: {e}", exc_info=True) # 记录错误
        await db.rollback() # 回滚事务
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="删除上下文条目失败。") # 抛出 500 错误

@router.get(
    "/api/manage/report/data", # API 端点路径
    dependencies=[Depends(verify_jwt_token), Depends(require_admin_user)] # 需要管理员权限
)
async def get_report_data(
    token_payload: Dict[str, Any] = Depends(verify_jwt_token), # 注入 JWT payload
    key_manager: APIKeyManager = Depends(get_key_manager)  # 注入 KeyManager
):
    """
    API 端点：获取用于报告页面的统计数据。
    需要管理员权限。

    Args:
        token_payload (Dict[str, Any]): 已验证的管理员 JWT payload。
        key_manager (APIKeyManager): 注入的 KeyManager 实例。

    Returns:
        JSONResponse: 包含报告数据的 JSON 响应。

    Raises:
        HTTPException: 如果获取报告数据时发生错误。
    """
    user_key = token_payload.get('sub', '未知管理员') # 获取管理员标识
    logger.debug(f"管理员 {user_key[:8]}... 请求报告数据") # 记录日志
    try:
        # 调用 reporter 模块中的 report_usage 函数获取报告数据字典
        report_data = report_usage(key_manager)
        # 确保 report_data 是一个字典 (防御性编程)
        report_data = report_data if isinstance(report_data, dict) else {}

        logger.info(f"管理员 {user_key[:8]}... 成功获取报告数据。") # 记录成功日志
        return JSONResponse(content=report_data)  # 将报告数据字典作为 JSON 响应返回

    except Exception as e: # 捕获获取报告数据时可能发生的异常
        logger.error(f"管理员 {user_key[:8]}... 获取报告数据时出错: {e}", exc_info=True) # 记录错误
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取报告数据失败") # 抛出 500 错误
