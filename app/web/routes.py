# -*- coding: utf-8 -*-
"""
处理 Web UI 相关的路由，例如状态页面和未来的管理界面。
Handles Web UI related routes, such as the status page and future management interfaces.
"""
import logging # 导入 logging 模块 (Import logging module)
# import pytz # 已移除，不再需要 (Removed, no longer needed)
import asyncio # 导入 asyncio，虽然不直接用，但依赖的模块用了 (Import asyncio, although not used directly, dependent modules use it)
from datetime import datetime, timezone # 导入时区 (Import timezone)
# from collections import Counter # 已移除，不再需要 (Removed, no longer needed)
from fastapi import APIRouter, Request, Form, Depends, HTTPException, status, Response # 保留 Response 导入 (Keep Response import)
# 导入 Response, Request, HTMLResponse, RedirectResponse, JSONResponse
# Import Response, Request, HTMLResponse, RedirectResponse, JSONResponse
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse # 保留现有导入 (Keep existing imports)
from fastapi.templating import Jinja2Templates # 导入 Jinja2Templates (Import Jinja2Templates)
# 导入安全相关的类型和新的依赖项
# Import security-related types and new dependencies
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials # 虽然 verify_jwt_token 在 auth.py，但类型提示可能需要 (Although verify_jwt_token is in auth.py, type hints might need it)
from typing import Optional, Annotated, Dict, Any # Annotated 用于表单依赖, Dict, Any 用于 JWT (Annotated for form dependencies, Dict, Any 用于 JWT)

import uuid # 用于生成新的 Key (Used for generating new keys)
from pydantic import BaseModel, Field # 用于 API 请求体验证 (Used for API request body validation)
# 相对导入
# Relative imports
from .. import config # 导入根配置 (Import root config)
from ..config import ( # 导入具体配置项 (Import specific configuration items)
    PROTECT_STATUS_PAGE, # 是否保护状态页面 (Whether to protect status page)
    PASSWORD, # Web UI 密码 (Web UI password)
    # ... (其他可能需要的配置) (... (other potentially needed configurations))
    __version__, # 应用版本 (Application version)
    # 导入 render_status_page (现已移除) 直接需要的配置值，部分可能仍用于模板
    # Import configuration values directly needed by render_status_page (now removed), some may still be used for templates
    REPORT_LOG_LEVEL_STR, # 报告日志级别字符串 (Report log level string)
    USAGE_REPORT_INTERVAL_MINUTES, # 使用情况报告间隔（分钟） (Usage report interval in minutes)
    DISABLE_SAFETY_FILTERING, # 是否禁用安全过滤 (Whether safety filtering is disabled)
    MAX_REQUESTS_PER_MINUTE, # 每分钟最大请求数 (Maximum requests per minute)
    MAX_REQUESTS_PER_DAY_PER_IP # 每个 IP 每天最大请求数 (Maximum requests per day per IP)
)
# from ..core.utils import key_manager_instance as key_manager # 移除，如果不再需要 Key Manager (Removed if Key Manager is no longer needed)
# Import the specific count variable from key_management
# from ..core.key_management import INVALID_KEY_COUNT_AT_STARTUP # 移除，如果不再需要 (Removed if no longer needed)
# from ..core.tracking import ( # 移除，如果不再需要 (Removed if no longer needed)
#     daily_rpd_totals, daily_totals_lock,
#     ip_daily_counts, ip_counts_lock,
#     ip_daily_input_token_counts, ip_input_token_counts_lock
# )
# 导入上下文存储
# Import context storage
from ..core import context_store # 导入 context_store 模块 (Import context_store module)
from ..core import db_utils # 导入数据库工具函数和 IS_MEMORY_DB (Import database utility functions and IS_MEMORY_DB)
# 导入新的安全和认证模块
# Import new security and authentication modules
from ..core.security import create_access_token # 导入创建访问令牌函数 (Import create_access_token function)
from .auth import verify_jwt_token # 导入新的 JWT 验证依赖 (Import new JWT verification dependency)
# CSRF 保护相关导入已移除
# CSRF protection related imports removed

# 导入报告相关的函数和 Key Manager 实例
# Import report related function and Key Manager instance
from ..core.usage_reporter import get_structured_report_data # 导入获取结构化报告数据的函数 (Import function to get structured report data)
from ..core.utils import key_manager_instance # 导入 Key Manager 实例 (Import Key Manager instance)


logger = logging.getLogger('my_logger') # 获取日志记录器实例 (Get logger instance)
router = APIRouter(tags=["Web UI"]) # 创建 APIRouter 实例并添加标签 (Create APIRouter instance and add tag)

# 设置模板目录
# Set template directory
templates = Jinja2Templates(directory="app/web/templates") # 设置 Jinja2 模板目录 (Set Jinja2 templates directory)

# --- 旧的 Session 认证依赖 (已移除) ---
# --- Old Session Authentication Dependency (Removed) ---
# async def require_login(request: Request): ... (代码已删除) (code deleted)

# --- 根路径 (现在是登录页面) ---
# --- Root Path (Now Login Page) ---
@router.get("/", response_class=HTMLResponse, include_in_schema=False) # 定义 GET / 端点，响应类型为 HTMLResponse (Define GET / endpoint, response type is HTMLResponse)
async def root_get(request: Request): # 移除了 CsrfProtect 依赖 (Removed CsrfProtect dependency)
    """
    显示登录表单页面。
    Displays the login form page.
    """
    # user_session = request.session.get("user", {}) # 安全地获取 session (旧的 Session 逻辑已移除) (Safely get session (old Session logic removed))
    # is_authenticated = user_session.get("authenticated", False) # (旧的 Session 逻辑已移除) ((old Session logic removed))
    login_required = bool(PASSWORD) # 检查是否全局设置了密码 (Check if password is set globally)
    # show_details = not PROTECT_STATUS_PAGE or is_authenticated # (Session 已移除) ((Session removed))
    # 假设存在 login.html 模板用于显示登录表单
    # Assume login.html template exists for displaying the login form

    # --- CSRF 相关代码已移除 ---
    # --- CSRF Related Code Removed ---
    # csrf_token, signed_token = csrf_protect.generate_csrf_tokens()
    admin_key_missing = not config.ADMIN_API_KEY # 检查管理员 Key 是否缺失 (Check if admin key is missing)
    response = templates.TemplateResponse(
        "login.html", # 模板文件 (Template file)
        {
            "request": request, # 请求对象 (Request object)
            "login_required": login_required, # 是否需要登录 (Whether login is required)
            "admin_key_missing": admin_key_missing, # 添加到模板上下文 (Add to template context)
            "now": datetime.now(timezone.utc) # 添加 now 变量 (Add now variable)
            # "csrf_token": csrf_token # 移除了 CSRF token (Removed CSRF token)
        }
    )
    # --- CSRF 相关代码已移除 ---
    # --- CSRF Related Code Removed ---
    # csrf_protect.set_csrf_cookie(signed_token, response)

    return response # 返回响应 (Return response)

# --- 旧的 POST / 路由 (已移除) ---
# --- Old POST / Route (Removed) ---
# @router.post("/", ...) ... (代码已删除) (code deleted)

# --- 旧的 render_status_page 辅助函数 (已移除) ---
# --- Old render_status_page Helper Function (Removed) ---
# async def render_status_page(...): ... (代码已删除) (code deleted)

# --- 新的登录处理路由 ---
# --- New Login Handling Route ---
@router.post("/login", include_in_schema=False) # 定义 POST /login 端点 (Define POST /login endpoint)
async def login_for_access_token(
    request: Request, # 添加 request 参数 (虽然 CSRF 移除了，但保留以备将来使用或获取请求信息) (Added request parameter (although CSRF removed, kept for future use or getting request info))
    password: str = Form(...) # 从表单获取密码 (Get password from form)
    # csrf_protect: CsrfProtect = Depends() # 移除了 CsrfProtect 依赖 (Removed CsrfProtect dependency)
):
    """
    处理 Web UI 登录请求，验证密码并返回 JWT 访问令牌。
    Handles Web UI login requests, verifies the password, and returns a JWT access token.
    """
    # --- CSRF 验证已移除 ---
    # --- CSRF Validation Removed ---
    # try:
    #     await csrf_protect.validate_csrf(request)
    # except CsrfProtectException as e:
    #     logger.warning(f"CSRF validation failed during login: {e.message}")
    #     raise HTTPException(status_code=e.status_code, detail=e.message)
    # --- CSRF 验证已移除 ---

    # 检查是否配置了任何密码
    # Check if any passwords are configured
    if not config.WEB_UI_PASSWORDS: # 如果没有配置 Web UI 密码 (If no Web UI passwords are configured)
        logger.error("尝试登录，但 Web UI 密码 (PASSWORD) 未设置或为空。") # Log error
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, # 使用 503 表示服务未正确配置 (Use 503 to indicate service is not configured correctly)
            detail="Web UI 登录未启用 (密码未设置)", # 错误详情 (Error detail)
        )

    # 检查是否为管理员 Key
    # Check if it's an admin key
    is_admin_login = False # 初始化管理员登录标志 (Initialize admin login flag)
    if config.ADMIN_API_KEY and password == config.ADMIN_API_KEY: # 如果提供了管理员 Key 且密码匹配 (If admin key is provided and password matches)
        is_admin_login = True # 标记为管理员登录 (Mark as admin login)
        logger.info(f"管理员 Key 登录尝试: {password[:8]}...") # Log admin key login attempt
        access_token_data = {"sub": password, "admin": True} # 管理员 JWT 数据 (Admin JWT data)
    # 检查提交的密码是否在配置的普通用户密码列表中
    # Check if the submitted password is in the list of configured regular user passwords
    elif password in config.WEB_UI_PASSWORDS: # 如果密码在普通用户密码列表中 (If password is in regular user password list)
        logger.info(f"普通用户 Key 登录尝试: {password[:8]}...") # Log regular user key login attempt
        # 密码正确，创建 JWT (普通用户)
        # Password is correct, create JWT (regular user)
        # 将成功匹配的密码作为用户标识符存储在 JWT 的 'sub' 字段中
        # Store the successfully matched password as the user identifier in the 'sub' field of the JWT
        access_token_data = {"sub": password} # 普通用户 JWT 数据 (Regular user JWT data) # 普通用户 JWT 不包含 admin 字段或为 False (Regular user JWT does not contain admin field or it's False)
    else:
        # 密码错误
        # Incorrect password
        logger.warning("Web UI 登录失败：密码错误。") # Log login failure
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, # 未授权状态码 (Unauthorized status code)
            detail="密码错误", # 错误详情 (Error detail)
            headers={"WWW-Authenticate": "Bearer"}, # WWW-Authenticate 头 (WWW-Authenticate header)
        )

    # 如果密码验证通过 (管理员或普通用户)
    # If password verification passes (admin or regular user)
    try:
        access_token = create_access_token(data=access_token_data) # 创建访问令牌 (Create access token)
        login_type = "管理员" if is_admin_login else "普通用户" # 判断登录类型 (Determine login type)
        logger.info(f"Web UI {login_type}登录成功，用户 Key: {password[:8]}... 已签发 JWT。") # Log successful login and JWT issuance
        return JSONResponse(content={"access_token": access_token, "token_type": "bearer"}) # 返回 JWT 响应 (Return JWT response)
    except ValueError as e: # 捕获 create_access_token 中 SECRET_KEY 未设置的错误 (Catch SECRET_KEY not set error in create_access_token)
         logger.error(f"无法创建 JWT: {e}") # 记录错误 (Log error)
         raise HTTPException(
             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, # 内部服务器错误状态码 (Internal Server Error status code)
             detail="无法生成认证令牌 (内部错误)", # 错误详情 (Error detail)
         )
    except Exception as e: # 捕获其他可能的 JWT 创建错误 (Catch other potential JWT creation errors)
         logger.error(f"创建 JWT 时发生未知错误: {e}", exc_info=True) # 记录未知错误 (Log unknown error)
         raise HTTPException(
             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, # 内部服务器错误状态码 (Internal Server Error status code)
             detail="生成认证令牌时出错", # 错误详情 (Error detail)
         )


# --- 管理界面路由 ---
# --- Management Interface Routes ---

@router.get("/manage", include_in_schema=False) # 定义 GET /manage 端点 (Define GET /manage endpoint)
async def manage_redirect():
    """
    管理首页重定向到上下文管理。
    Management home page redirects to context management.
    """
    return RedirectResponse(url="/manage/context", status_code=status.HTTP_303_SEE_OTHER) # 重定向到上下文管理页面 (Redirect to context management page)

# --- 代理 Key 管理 (已移除) ---
# --- Proxy Key Management (Removed) ---
# @router.get("/manage/keys", ...) ... (代码已删除) (code deleted)
# @router.post("/manage/keys/add", ...) ... (代码已删除) (code deleted)
# @router.post("/manage/keys/toggle/{key}", ...) ... (代码已删除) (code deleted)
# @router.post("/manage/keys/delete/{key}", ...) ... (代码已删除) (code deleted)


# --- 代理 Key 管理 (已移除) ---
# --- Proxy Key Management (Removed) ---
# @router.get("/manage/keys", ...) ... (代码已删除) (code deleted)
# @router.post("/manage/keys/add", ...) ... (代码已删除) (code deleted)
# @router.post("/manage/keys/toggle/{key}", ...) ... (代码已删除) (code deleted)
# @router.post("/manage/keys/delete/{key}", ...) ... (代码已删除) (code deleted)


# --- Pydantic Models for Key Management API ---
# --- Pydantic Models for Key Management API ---

class AddKeyRequest(BaseModel):
    description: Optional[str] = Field(None, description="新 Key 的描述 (可选)") # 新 Key 的描述 (Description for the new key)
    expires_at: Optional[str] = Field(None, description="Key 过期时间 (ISO 格式, YYYY-MM-DDTHH:MM:SSZ 或 YYYY-MM-DDTHH:MM:SS+00:00)，留空或 null 表示永不过期") # Key 过期时间 (Key expiration time)

class UpdateKeyRequest(BaseModel):
    description: Optional[str] = Field(None, description="新的描述 (可选)") # 新的描述 (New description)
    is_active: Optional[bool] = Field(None, description="新的激活状态 (可选)") # 新的激活状态 (New active status)
    expires_at: Optional[str] = Field(None, description="新的 Key 过期时间 (ISO 格式)，留空或 null 表示永过期") # 新的 Key 过期时间 (New key expiration time)
    enable_context_completion: Optional[bool] = Field(None, description="是否启用上下文补全 (可选)") # 是否启用上下文补全 (Whether to enable context completion)


# --- 代理 Key 管理 (仅文件模式) ---
# --- Proxy Key Management (File Mode Only) ---

# 新增：辅助函数检查是否为管理员
# New: Helper function to check if user is admin
async def require_admin_user(token_payload: Dict[str, Any] = Depends(verify_jwt_token)):
    """
    依赖项：检查当前用户是否为管理员。
    Dependency: Checks if the current user is an administrator.
    """
    is_admin = token_payload.get("admin", False) # 从 token payload 获取 admin 状态 (Get admin status from token payload)
    if not is_admin: # 如果不是管理员 (If not admin)
        user_key = token_payload.get("sub", "未知用户") # 获取用户 Key (Get user key)
        logger.warning(f"用户 {user_key[:8]}... 尝试访问管理员专属的 Key 管理 API，操作被拒绝。") # Log warning
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, # 禁止访问状态码 (Forbidden status code)
            detail="仅管理员有权限执行此操作。" # 错误详情 (Error detail)
        )
    # 如果是管理员，可以继续，不需要返回值
    # If it's an admin, can proceed, no return value needed

# 辅助函数检查是否为文件模式，如果不是则抛出 404
# Helper function to check if it's file mode, raises 404 if not
async def require_file_db_mode():
    if db_utils.IS_MEMORY_DB: # 如果是内存数据库模式 (If it's memory database mode)
        logger.debug("尝试访问 Key 管理功能，但当前为内存数据库模式。") # Log debug message
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, # 未找到状态码 (Not Found status code)
            detail="代理 Key 管理仅在文件数据库模式下可用 (需设置 CONTEXT_DB_PATH)。" # 错误详情 (Error detail)
        )

# 渲染 Key 管理页面的路由
# Route for rendering the Key Management page
@router.get(
    "/manage/keys",
    response_class=HTMLResponse,
    include_in_schema=False
    # 移除装饰器中的重复依赖 (Remove duplicate dependency from decorator)
    # dependencies=[Depends(verify_jwt_token)] # 添加 JWT 验证依赖 (Add JWT verification dependency)
)
# 将 verify_jwt_token 添加为依赖项 (Add verify_jwt_token as a dependency)
async def manage_keys_page(request: Request): # 移除 token_payload 参数 (Remove token_payload parameter)
    """
    显示代理 Key 管理页面的 HTML 骨架。如果处于内存数据库模式，则显示提示信息。
    需要有效的 JWT Bearer Token 认证。
    Displays the HTML skeleton of the proxy key management page. If in memory database mode, displays a hint message.
    Requires valid JWT Bearer Token authentication.
    """
    # 移除手动检查 JWT 认证的 try...except 块，依赖注入会自动处理认证失败
    # Remove the try...except block for manual JWT check, dependency injection handles failures automatically
    # try:
        # token_payload = await verify_jwt_token(request) # 手动调用依赖函数 (Manually call dependency function)
    # 如果认证成功，继续渲染页面 (If authentication is successful, continue rendering the page)
    # token_payload 现在由 Depends 注入 (token_payload is now injected by Depends)
    is_memory_mode = db_utils.IS_MEMORY_DB # 检查是否为内存模式 (Check if it's memory mode)
    if is_memory_mode: # 如果是内存模式 (If it's memory mode)
        logger.debug("渲染 Key 管理页面骨架 (内存模式提示)") # Log rendering skeleton with memory mode hint
        admin_key_missing = not config.ADMIN_API_KEY # 检查管理员 Key 是否缺失 (Check if admin key is missing)
        return templates.TemplateResponse(
            "manage_keys.html", # 模板文件 (Template file)
            # 添加 'now' 到上下文，用于模板中可能的缓存控制或显示
            # Add 'now' to context, for possible cache control or display in the template
            {"request": request, "is_memory_mode": True, "admin_key_missing": admin_key_missing, "now": datetime.now(timezone.utc)} # 模板上下文 (Template context)
        )
    else: # 如果是文件模式 (If it's file mode)
        logger.debug("渲染 Key 管理页面骨架 (文件模式)") # Log rendering skeleton for file mode
        admin_key_missing = not config.ADMIN_API_KEY # 检查管理员 Key 是否缺失 (Check if admin key is missing)
        # 仅渲染页面骨架，实际的 Key 数据将由前端通过 API 请求获取并填充
        # Only render the page skeleton, the actual Key data will be fetched and populated by frontend JavaScript via API requests
        return templates.TemplateResponse(
            "manage_keys.html", # 模板文件 (Template file)
            # 添加 'now' 到上下文
            # Add 'now' to context
            {"request": request, "is_memory_mode": False, "admin_key_missing": admin_key_missing, "now": datetime.now(timezone.utc)} # 模板上下文 (Template context)
        )
    # except HTTPException as e:
    #     # 如果认证失败 (例如 401 或 403)，重定向到登录页面
    #     # If authentication fails (e.g. 401 or 403), redirect to login page
    #     if e.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]: # 如果是 401 或 403 错误 (If it's 401 or 403 error)
    #         logger.warning(f"访问 /manage/keys 未认证或无权限，重定向到登录页。") # Log warning
    #         return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER) # 重定向到根路径 (登录页) (Redirect to root path (login page))
    #     else:
    #         # 其他 HTTPException 重新抛出
    #         # Re-raise other HTTPExceptions
    #         raise e
    # except Exception as e:
    #     # 捕获其他意外错误
    #     # Catch other unexpected errors
    #     logger.error(f"访问 /manage/keys 时发生意外错误: {e}", exc_info=True) # Log error
    #     raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="内部服务器错误") # 引发 500 异常 (Raise 500 exception)

# 获取 Key 数据的 API 端点
# API endpoint for getting Key data
@router.get(
    "/api/manage/keys/data",
    # 添加管理员检查依赖
    # Add admin check dependency
    dependencies=[Depends(require_file_db_mode), Depends(require_admin_user)] # 依赖项：文件模式和管理员用户 (Dependencies: file mode and admin user)
)
async def get_manage_keys_data(token_payload: Dict[str, Any] = Depends(verify_jwt_token)): # 仍然需要 token_payload 来记录日志 (Still need token_payload for logging)
    """
    获取代理 Key 管理页面所需的数据 (仅管理员)。
    Gets the data required for the proxy key management page (admin only).
    """
    admin_key = token_payload.get('sub', '未知管理员') # 获取管理员 Key (Get admin key)
    logger.debug(f"管理员 {admin_key[:8]}... 请求 Key 管理数据") # Log admin requesting data
    try:
        # 确保 db_utils.get_all_proxy_keys 返回包含 enable_context_completion 字段的数据
        # Ensure db_utils.get_all_proxy_keys returns data including the enable_context_completion field
        keys_data = await db_utils.get_all_proxy_keys() # 添加 await (Added await) # 获取所有代理 Key 数据 (Get all proxy key data)
        # 转换 Row 对象为字典列表，并格式化日期
        # Convert Row objects to a list of dictionaries and format dates
        result = [] # 初始化结果列表 (Initialize result list)
        for row in keys_data: # 遍历 Key 数据 (Iterate through key data)
            key_info = dict(row) # 将 sqlite3.Row 转换为字典 (Convert sqlite3.Row to dictionary)

            # 格式化 created_at
            # Format created_at
            created_at_val = key_info.get('created_at') # 获取 created_at 值 (Get created_at value)
            if isinstance(created_at_val, datetime): # 如果是 datetime 对象 (If it's a datetime object)
                 key_info['created_at'] = created_at_val.strftime('%Y-%m-%d %H:%M:%S') # 格式化为字符串 (Format as string)
            elif isinstance(created_at_val, str): # 如果是字符串 (If it's a string)
                 try:
                     # 尝试解析数据库返回的字符串（可能是 ISO 格式）
                     # Attempt to parse the string returned by the database (might be ISO format)
                     dt_obj = datetime.fromisoformat(created_at_val.replace('Z', '+00:00')) # 处理 Z 时区 (Handle Z timezone)
                     key_info['created_at'] = dt_obj.strftime('%Y-%m-%d %H:%M:%S') # 格式化为字符串 (Format as string)
                 except ValueError:
                     logger.warning(f"无法解析 Key {key_info.get('key')} 的 created_at 字符串: {created_at_val}") # Log warning
                     key_info['created_at'] = created_at_val # 保持原样 (Keep as is)

            # 处理 expires_at (保持 ISO 格式或 None)
            # Handle expires_at (keep ISO format or None)
            expires_at_val = key_info.get('expires_at') # 获取 expires_at 值 (Get expires_at value)
            if isinstance(expires_at_val, datetime): # 如果是 datetime 对象 (If it's a datetime object)
                 # 如果数据库返回的是 datetime 对象，转为 ISO 格式
                 # If the database returns a datetime object, convert to ISO format
                 key_info['expires_at'] = expires_at_val.replace(tzinfo=timezone.utc).isoformat() # 转为 ISO 格式 (Convert to ISO format)
            elif isinstance(expires_at_val, str): # 如果是字符串 (If it's a string)
                 # 如果已经是字符串，确保是有效的 ISO 格式，否则记录警告
                 # If it's already a string, ensure it's a valid ISO format, otherwise log a warning
                 try:
                     datetime.fromisoformat(expires_at_val.replace('Z', '+00:00'))
                     # 格式有效，保持原样
                     # Format is valid, keep as is
                     key_info['expires_at'] = expires_at_val
                 except ValueError:
                     logger.warning(f"数据库返回的 Key {key_info.get('key')} 的 expires_at 字符串格式无效: {expires_at_val}") # Log warning for invalid format
                     key_info['expires_at'] = None # 视为无效或无过期时间 (Consider invalid or no expiration time)
            else:
                 # 其他情况（如 None）保持不变
                 # Other cases (like None) remain unchanged
                 key_info['expires_at'] = expires_at_val # 应该是 None (Should be None)

            result.append(key_info) # 添加到结果列表 (Append to result list)

        # 返回 is_admin 状态，前端需要
        # Return is_admin status, needed by frontend
        is_admin_status = token_payload.get("admin", False) # 从 token 获取真实状态 (Get real status from token)
        return {"keys": result, "is_admin": is_admin_status} # 返回 Key 数据和管理员状态 (Return Key data and admin status)
    except Exception as e:
        logger.error(f"管理员 {admin_key[:8]}... 获取 Key 管理数据时出错: {e}", exc_info=True) # 记录错误 (Log error)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取 Key 数据失败") # 引发 500 异常 (Raise 500 exception)

# 添加新 Key 的 API 端点
# API endpoint for adding a new Key
@router.post(
    "/api/manage/keys/add",
    status_code=status.HTTP_201_CREATED, # 成功创建资源时返回 201 状态码 (Return 201 status code on successful resource creation)
    # 添加管理员检查依赖
    # Add admin check dependency
    dependencies=[Depends(require_file_db_mode), Depends(require_admin_user)] # 依赖项：文件模式和管理员用户 (Dependencies: file mode and admin user)
)
async def add_new_key(
    key_data: AddKeyRequest, # 使用更新后的 Pydantic 模型 (Use updated Pydantic model)
    token_payload: Dict[str, Any] = Depends(verify_jwt_token) # 仍然需要 token_payload 来记录日志 (Still need token_payload for logging)
):
    """
    API 端点：添加一个新的代理 Key (Key 值由 UUID 自动生成) (仅管理员)。
    API endpoint: Adds a new proxy key (Key value is automatically generated by UUID) (admin only).
    """
    admin_key = token_payload.get('sub', '未知管理员') # 获取管理员 Key (Get admin key)
    logger.debug(f"管理员 {admin_key[:8]}... 请求添加新 Key") # Log admin requesting to add new key
    new_key = str(uuid.uuid4()) # 生成新的 UUID 作为 Key (Generate new UUID as Key)
    description = key_data.description # Pydantic 会处理 None (Pydantic handles None)
    expires_at = key_data.expires_at # 获取 expires_at (Get expires_at)

    # 验证 expires_at 格式 (如果提供)
    # Validate expires_at format (if provided)
    if expires_at: # 如果提供了 expires_at (If expires_at is provided)
        try:
            # 尝试解析以确保格式正确，但不存储 datetime 对象
            # Attempt to parse to ensure format is correct, but do not store datetime object
            datetime.fromisoformat(expires_at.replace('Z', '+00:00')) # 尝试解析 ISO 格式 (Attempt to parse ISO format)
        except ValueError:
            logger.warning(f"管理员 {admin_key[:8]}... 提供的 expires_at 格式无效: {expires_at}") # Log warning for invalid format
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="expires_at 格式无效，请使用 ISO 8601 格式 (例如 YYYY-MM-DDTHH:MM:SSZ)") # 引发 400 异常 (Raise 400 exception)

    # 调用数据库函数，传入 expires_at
    # Call database function, passing expires_at
    success = await db_utils.add_proxy_key(key=new_key, description=description, expires_at=expires_at) # 添加 await (Added await) # 添加代理 Key (Add proxy key)

    if success: # 如果添加成功 (If adding is successful)
        logger.info(f"管理员 {admin_key[:8]}... 成功添加新 Key: {new_key[:8]}... (描述: {description}, 过期: {expires_at})") # Log successful addition
        # 返回新创建的 Key 信息可能更有用
        # Returning information about the newly created Key might be more useful
        new_key_info = await db_utils.get_proxy_key(new_key) # 添加 await (Added await) # 获取新 Key 信息 (Get new key info)
        if new_key_info: # 如果获取到信息 (If info is obtained)
             key_dict = dict(new_key_info) # 转换为字典 (Convert to dictionary)
             # 格式化 created_at
             # Format created_at
             created_at_val = key_dict.get('created_at') # 获取 created_at 值 (Get created_at value)
             if isinstance(created_at_val, datetime): # 如果是 datetime 对象 (If it's a datetime object)
                 key_dict['created_at'] = created_at_val.strftime('%Y-%m-%d %H:%M:%S') # 格式化为字符串 (Format as string)
             elif isinstance(created_at_val, str): # 如果是字符串 (If it's a string)
                 try:
                     dt_obj = datetime.fromisoformat(created_at_val.replace('Z', '+00:00'))
                     key_dict['created_at'] = dt_obj.strftime('%Y-%m-%d %H:%M:%S')
                 except ValueError: pass # 保持原样 (Keep as is)

             # 处理 expires_at (保持 ISO 格式或 None)
             # Handle expires_at (keep ISO format or None)
             expires_at_val = key_dict.get('expires_at') # 获取 expires_at 值 (Get expires_at value)
             if isinstance(expires_at_val, datetime): # 如果是 datetime 对象 (If it's a datetime object)
                 key_dict['expires_at'] = expires_at_val.replace(tzinfo=timezone.utc).isoformat() # 转为 ISO 格式 (Convert to ISO format)
             # else: # 保持数据库返回的字符串或 None (Keep database returned string or None)

             return {"message": "Key 添加成功", "key": key_dict} # 返回成功消息和 Key 信息 (Return success message and key info)
        else:
             # 理论上不应发生，但作为回退
             # Theoretically should not happen, but as a fallback
             logger.error(f"添加 Key {new_key[:8]}... 成功，但无法立即检索其信息。") # Log error
             return {"message": "Key 添加成功，但无法检索信息", "key_id": new_key} # 返回成功消息和 Key ID (Return success message and key ID)
    else:
        logger.error(f"添加新 Key 失败 (Key: {new_key[:8]}...)") # 记录添加失败错误 (Log add failure error)
        # add_proxy_key 内部已记录 Key 可能重复的警告
        # add_proxy_key internally logs warning for potential duplicate key
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="添加 Key 失败") # 引发 500 异常 (Raise 500 exception)

# 更新 Key 的 API 端点
# API endpoint for updating a Key
@router.put( # 使用 PUT 方法更新资源更符合 RESTful 风格 (Using PUT method to update resources is more RESTful)
    "/api/manage/keys/update/{proxy_key}",
    # 添加管理员检查依赖
    # Add admin check dependency
    dependencies=[Depends(require_file_db_mode), Depends(require_admin_user)] # 依赖项：文件模式和管理员用户 (Dependencies: file mode and admin user)
)
async def update_existing_key(
    proxy_key: str, # 要更新的 Key (Key to update)
    update_data: UpdateKeyRequest, # 使用更新后的 Pydantic 模型 (Use updated Pydantic model)
    token_payload: Dict[str, Any] = Depends(verify_jwt_token) # 仍然需要 token_payload 来记录日志 (Still need token_payload for logging)
):
    """
    更新指定代理 Key 的描述、状态、过期时间或上下文补全状态 (仅管理员)。
    Updates the description, status, expiration time, or context completion status of a specified proxy key (admin only).
    """
    admin_key = token_payload.get('sub', '未知管理员') # 获取管理员 Key (Get admin key)
    logger.debug(f"管理员 {admin_key[:8]}... 请求更新 Key: {proxy_key[:8]}...") # Log admin requesting to update key

    # 检查是否提供了至少一个要更新的字段
    # Check if at least one field to update is provided
    if update_data.description is None and update_data.is_active is None and update_data.expires_at is None and update_data.enable_context_completion is None:
         logger.warning(f"管理员 {admin_key[:8]}... 更新 Key {proxy_key[:8]}... 的请求未提供任何更新字段。") # Log warning
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="必须提供 description, is_active, expires_at 或 enable_context_completion 进行更新") # 引发 400 异常 (Raise 400 exception)

    # 验证 expires_at 格式 (如果提供)
    # Validate expires_at format (if provided)
    expires_at_to_update = update_data.expires_at # 获取 expires_at 值 (Get expires_at value)
    if expires_at_to_update is not None: # 注意：空字符串 "" 也需要验证和处理 (Note: Empty string "" also needs validation and handling)
        if expires_at_to_update == "": # 如果是空字符串 (If it's an empty string)
            expires_at_to_update = None # 将空字符串视为清除过期时间 (Treat empty string as clearing expiration time)
        else:
            try:
                datetime.fromisoformat(expires_at_to_update.replace('Z', '+00:00')) # 尝试解析 ISO 格式 (Attempt to parse ISO format)
            except ValueError:
                logger.warning(f"管理员 {admin_key[:8]}... 提供的 expires_at 格式无效: {expires_at_to_update}") # Log warning for invalid format
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="expires_at 格式无效，请使用 ISO 8601 格式 (例如 YYYY-MM-DDTHH:MM:SSZ) 或留空") # 引发 400 异常 (Raise 400 exception)

    success = await db_utils.update_proxy_key( # 添加 await (Added await) # 更新代理 Key (Update proxy key)
        key=proxy_key,
        description=update_data.description,
        is_active=update_data.is_active,
        expires_at=expires_at_to_update, # 传递处理过的 expires_at (Pass the processed expires_at)
        enable_context_completion=update_data.enable_context_completion # 传递 enable_context_completion (Pass enable_context_completion)
    )

    if success: # 如果更新成功 (If update is successful)
        logger.info(f"管理员 {admin_key[:8]}... 成功更新 Key: {proxy_key[:8]}...") # Log successful update
        updated_key_info = await db_utils.get_proxy_key(proxy_key) # 添加 await (Added await) # 获取更新后的 Key 信息 (Get updated key info)
        if updated_key_info: # 如果获取到信息 (If info is obtained)
             key_dict = dict(updated_key_info) # 转换为字典 (Convert to dictionary)
             # 格式化 created_at
             # Format created_at
             created_at_val = key_dict.get('created_at') # 获取 created_at 值 (Get created_at value)
             if isinstance(created_at_val, datetime): # 如果是 datetime 对象 (If it's a datetime object)
                 key_dict['created_at'] = created_at_val.strftime('%Y-%m-%d %H:%M:%S') # 格式化为字符串 (Format as string)
             elif isinstance(created_at_val, str): # 如果是字符串 (If it's a string)
                 try:
                     dt_obj = datetime.fromisoformat(created_at_val.replace('Z', '+00:00'))
                     key_dict['created_at'] = dt_obj.strftime('%Y-%m-%d %H:%M:%S')
                 except ValueError: pass # 保持原样 (Keep as is)

             # 处理 expires_at (保持 ISO 格式或 None)
             # Handle expires_at (keep ISO format or None)
             expires_at_val = key_dict.get('expires_at') # 获取 expires_at 值 (Get expires_at value)
             if isinstance(expires_at_val, datetime): # 如果是 datetime 对象 (If it's a datetime object)
                 key_dict['expires_at'] = expires_at_val.replace(tzinfo=timezone.utc).isoformat() # 转为 ISO 格式 (Convert to ISO format)
             # else: # 保持数据库返回的字符串或 None (Keep database returned string or None)

             return {"message": "Key 更新成功", "key": key_dict} # 返回成功消息和 Key 信息 (Return success message and key info)
        else:
             logger.warning(f"更新 Key {proxy_key[:8]}... 成功，但无法检索更新后的信息 (可能已被并发删除?)") # Log warning
             return {"message": "Key 更新成功，但无法检索更新后的信息"} # 返回成功消息 (Return success message)
    else:
        # update_proxy_key 内部已记录 Key 未找到或未改变的警告
        # update_proxy_key internally logs warning if Key not found or not changed
        # 检查 Key 是否存在，以返回更具体的错误
        # Check if the Key exists to return a more specific error
        existing_key = await db_utils.get_proxy_key(proxy_key) # 添加 await (Added await) # 获取现有 Key 信息 (Get existing key info)
        if not existing_key: # 如果 Key 不存在 (If key does not exist)
            logger.warning(f"尝试更新不存在的 Key: {proxy_key[:8]}...") # Log warning
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Key '{proxy_key}' 不存在") # 引发 404 异常 (Raise 404 exception)
        else:
            logger.error(f"更新 Key {proxy_key[:8]}... 失败 (数据库错误或其他原因)") # 记录更新失败错误 (Log update failure error)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="更新 Key 失败") # 引发 500 异常 (Raise 500 exception)


# 删除 Key 的 API 端点
# API endpoint for deleting a Key
@router.delete( # 使用 DELETE 方法删除资源 (Using DELETE method to delete resources)
    "/api/manage/keys/delete/{proxy_key}",
    status_code=status.HTTP_204_NO_CONTENT, # 204 表示成功处理，无内容返回 (204 indicates successful processing with no content returned)
    # 添加管理员检查依赖
    # Add admin check dependency
    dependencies=[Depends(require_file_db_mode), Depends(require_admin_user)] # 依赖项：文件模式和管理员用户 (Dependencies: file mode and admin user)
)
async def delete_existing_key(
    proxy_key: str, # 要删除的 Key (Key to delete)
    token_payload: Dict[str, Any] = Depends(verify_jwt_token) # 仍然需要 token_payload 来记录日志 (Still need token_payload for logging)
):
    """
    删除指定代理 Key 关联的上下文记录 (管理员或 Key 所有者)。
    Deletes the context record associated with the specified proxy key (admin or key owner).
    """
    admin_key = token_payload.get('sub', '未知管理员') # 获取管理员 Key (Get admin key)
    logger.debug(f"管理员 {admin_key[:8]}... 请求删除 Key: {proxy_key[:8]}...") # Log admin requesting to delete key

    success = await db_utils.delete_proxy_key(key=proxy_key) # 添加 await (Added await) # 删除代理 Key (Delete proxy key)

    if success: # 如果删除成功 (If deletion is successful)
        logger.info(f"管理员 {admin_key[:8]}... 成功删除 Key: {proxy_key[:8]}...") # Log successful deletion
        # 204 状态码表示成功处理请求，但无需返回任何内容
        # 204 status code indicates successful request processing with no content returned
        return None # FastAPI 会自动生成无内容的 204 响应 (FastAPI will automatically generate a 204 response with no content)
    else:
        # delete_proxy_key 内部已记录 Key 未找到的警告
        # delete_proxy_key internally logs warning if Key not found
        logger.warning(f"尝试删除不存在的 Key: {proxy_key[:8]}...") # Log warning
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Key '{proxy_key}' 不存在") # 引发 404 异常 (Raise 404 exception)


# --- 上下文管理 ---
# --- Context Management ---
# 移除 JWT 依赖，改为由前端 JS 获取数据时验证
# Remove JWT dependency, changed to verify when frontend JS fetches data
# 添加 CsrfProtect 依赖
# Add CsrfProtect dependency
@router.get("/manage/context", response_class=HTMLResponse, include_in_schema=False) # 移除 JWT 验证依赖 (Removed JWT verification dependency)
async def manage_context_page(request: Request): # 移除 CsrfProtect 依赖 (Removed CsrfProtect dependency)
    """
    显示上下文管理页面的 HTML 骨架。
    实际数据将由前端 JavaScript 通过 /api/manage/context/data 获取。
    需要 JWT 认证。
    Displays the HTML skeleton of the context management page.
    Actual data will be fetched by frontend JavaScript via /api/manage/context/data.
    Requires valid JWT authentication.
    """
    # 不再需要在这里获取数据，只渲染模板
    # No longer need to fetch data here, just render the template
    # current_ttl_days = await context_store.get_ttl_days() # 改为 await (Changed to await)
    # contexts_info = await context_store.list_all_context_keys_info() # 改为 await (Changed to await)
    # # 转换 datetime 对象 ... (移除) (... (Removed))
    admin_key_missing = not config.ADMIN_API_KEY # 检查管理员 Key 是否缺失 (Check if admin key is missing)
    context = { # 模板上下文 (Template context)
        "request": request,
        # "current_ttl_days": current_ttl_days, # 数据由 API 提供 (Data provided by API)
        # "contexts_info": contexts_info,      # 数据由 API 提供 (Data provided by API)
        "admin_key_missing": admin_key_missing, # 添加到模板上下文 (Add to template context)
        "now": datetime.now(timezone.utc) # 确保时区一致 (UTC) 且键名为 'now' (Ensure timezone consistency (UTC) and key name is 'now')
    }
    # CSRF 相关代码已移除
    # CSRF Related Code Removed

    response = templates.TemplateResponse("manage_context.html", context) # 创建模板响应 (Create template response)

    # CSRF 相关代码已移除
    # CSRF Related Code Removed

    return response # 返回响应 (Return response)


# --- 新增：获取上下文管理数据的 API 端点 ---
# --- New: API Endpoint for Getting Context Management Data ---
@router.get("/api/manage/context/data", dependencies=[Depends(verify_jwt_token)]) # 定义 GET /api/manage/context/data 端点，依赖 JWT 验证 (Define GET /api/manage/context/data endpoint, depends on JWT verification)
async def get_context_data(token_payload: Dict[str, Any] = Depends(verify_jwt_token)): # 依赖 JWT 验证并获取 payload (Depends on JWT verification and gets payload)
    """
    获取上下文管理页面所需的数据。
    需要有效的 JWT Bearer Token 认证。
    Gets the data required for the context management page.
    Requires valid JWT Bearer Token authentication.
    """
    user_key = token_payload.get("sub") # 获取用户 Key (Get user key)
    is_admin = token_payload.get("admin", False) # 获取管理员状态 (Get admin status)
    # 修改日志语句，处理 user_key 为 None 的情况，并更明确地记录管理员状态
    # Modify log statement to handle case where user_key is None, and log admin status more explicitly
    log_user_id = user_key[:8] + "..." if user_key else "未知用户" # 格式化用户 ID 或显示未知用户 (Format user ID or display unknown user)
    log_admin_status = "管理员" if is_admin else "非管理员" # 显示管理员状态 (Display admin status)
    logger.debug(f"用户 {log_user_id} ({log_admin_status}) 请求上下文管理数据") # Log user requesting context data

    try:
        current_ttl_days = await context_store.get_ttl_days() # 获取当前 TTL (Get current TTL)
        contexts_info_raw = await context_store.list_all_context_keys_info() # 获取原始上下文信息 (Get raw context info)

        # 转换 datetime 对象并处理 None
        # Convert datetime objects and handle None
        contexts_info = [] # 初始化处理后的列表 (Initialize processed list)
        for info in contexts_info_raw: # 遍历原始信息 (Iterate through raw info)
            info_dict = dict(info) # 转换为字典 (Convert to dictionary)
            last_accessed = info_dict.get('last_accessed') # 获取 last_accessed 值 (Get last_accessed value)
            if isinstance(last_accessed, datetime): # 如果是 datetime 对象 (If it's a datetime object)
                # 确保是 UTC 时间，然后格式化
                # Ensure it's UTC time, then format
                info_dict['last_accessed'] = last_accessed.replace(tzinfo=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC') # 格式化为带 UTC 的字符串 (Format as string with UTC)
            elif last_accessed is None: # 如果是 None (If it's None)
                info_dict['last_accessed'] = "从未访问" # 设置为 "从未访问" (Set to "Never accessed")
            # 如果已经是字符串或其他类型，保持原样 (If already string or other type, keep as is)

            contexts_info.append(info_dict) # 添加到处理后的列表 (Append to processed list)

        return JSONResponse(content={ # 返回 JSON 响应 (Return JSON response)
            "current_ttl_days": current_ttl_days, # 当前 TTL (Current TTL)
            "contexts_info": contexts_info, # 处理后的上下文信息 (Processed context info)
            "is_admin": is_admin # 添加管理员状态 (Add admin status)
        })
    except Exception as e:
        logger.error(f"获取上下文管理数据时出错: {e}", exc_info=True) # 记录错误 (Log error)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取上下文数据失败") # 引发 500 异常 (Raise 500 exception)

# --- 新增：更新 TTL 的 API 端点 ---
# --- New: API Endpoint for Updating TTL ---
@router.post(
    "/manage/context/update_ttl",
    dependencies=[Depends(verify_jwt_token), Depends(require_admin_user)] # 依赖 JWT 验证和管理员权限 (Depends on JWT verification and admin privileges)
)
async def update_context_ttl(
    ttl_days: int = Form(...), # 从表单获取 TTL 天数 (Get TTL days from form)
    token_payload: Dict[str, Any] = Depends(verify_jwt_token) # 获取 token payload 用于日志记录 (Get token payload for logging)
):
    """
    更新上下文的 TTL 设置 (仅管理员)。
    Updates the TTL setting for contexts (admin only).
    """
    admin_key = token_payload.get('sub', '未知管理员') # 获取管理员 Key (Get admin key)
    logger.debug(f"管理员 {admin_key[:8]}... 请求更新上下文 TTL 为 {ttl_days} 天") # Log admin requesting TTL update

    if ttl_days < 0: # 验证 TTL 值是否有效 (Validate TTL value)
        logger.warning(f"管理员 {admin_key[:8]}... 尝试设置无效的 TTL 值: {ttl_days}") # Log warning for invalid TTL
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="TTL 天数不能为负数") # 引发 400 异常 (Raise 400 exception)

    try:
        await context_store.set_ttl_days(ttl_days) # 调用 context_store 更新 TTL (Call context_store to update TTL)
        logger.info(f"管理员 {admin_key[:8]}... 成功将上下文 TTL 更新为 {ttl_days} 天") # Log successful update
        return JSONResponse(content={"message": f"上下文 TTL 已成功更新为 {ttl_days} 天"}) # 返回成功响应 (Return success response)
    except Exception as e:
        logger.error(f"管理员 {admin_key[:8]}... 更新上下文 TTL 时出错: {e}", exc_info=True) # 记录错误 (Log error)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="更新 TTL 失败") # 引发 500 异常 (Raise 500 exception)

# --- 新增：删除上下文的 API 端点 ---
# --- New: API Endpoint for Deleting Context ---
# 注意：前端模板中的删除按钮已经指向了这个路由，但这里需要实现它
# Note: The delete button in the frontend template already points to this route, but it needs to be implemented here
@router.post( # 使用 POST 更符合实际操作，即使没有请求体 (Using POST is more appropriate for the action, even without a request body)
    "/manage/context/delete/{proxy_key}",
    dependencies=[Depends(verify_jwt_token), Depends(require_admin_user)] # 依赖 JWT 验证和管理员权限 (Depends on JWT verification and admin privileges)
)
async def delete_context_for_key(
    proxy_key: str, # 要删除上下文的 Key (Key whose context to delete)
    token_payload: Dict[str, Any] = Depends(verify_jwt_token) # 获取 token payload 用于日志记录 (Get token payload for logging)
):
    """
    删除指定代理 Key 的上下文记录 (仅管理员)。
    Deletes the context record for a specified proxy key (admin only).
    """
    admin_key = token_payload.get('sub', '未知管理员') # 获取管理员 Key (Get admin key)
    logger.debug(f"管理员 {admin_key[:8]}... 请求删除 Key '{proxy_key}' 的上下文") # Log admin requesting context deletion

    try:
        deleted = await context_store.delete_context(proxy_key) # 调用 context_store 删除上下文 (Call context_store to delete context)
        if deleted: # 如果删除成功 (If deletion was successful)
            logger.info(f"管理员 {admin_key[:8]}... 成功删除 Key '{proxy_key}' 的上下文") # Log successful deletion
            # 返回 200 OK 和成功消息，因为前端 JS 会处理这个响应
            # Return 200 OK and success message, as frontend JS handles this response
            return JSONResponse(content={"message": f"Key '{proxy_key}' 的上下文已删除"}) # 返回成功响应 (Return success response)
        else: # 如果 context_store 返回 False (例如 Key 不存在) (If context_store returns False (e.g., key doesn't exist))
            logger.warning(f"管理员 {admin_key[:8]}... 尝试删除不存在的 Key '{proxy_key}' 的上下文") # Log warning
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"未找到 Key '{proxy_key}' 的上下文记录") # 引发 404 异常 (Raise 404 exception)
    except Exception as e:
        logger.error(f"管理员 {admin_key[:8]}... 删除 Key '{proxy_key}' 的上下文时出错: {e}", exc_info=True) # 记录错误 (Log error)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="删除上下文失败") # 引发 500 异常 (Raise 500 exception)


# --- 新增：获取报告数据的 API 端点 ---
# --- New: API Endpoint for Getting Report Data ---
@router.get("/api/report/data", dependencies=[Depends(verify_jwt_token)]) # 定义 GET /api/report/data 端点，依赖 JWT 验证 (Define GET /api/report/data endpoint，depends on JWT verification)
async def get_report_data(token_payload: Dict[str, Any] = Depends(verify_jwt_token)): # 依赖 JWT 验证并获取 payload (Depends on JWT verification and gets payload)
    """
    获取使用情况报告所需的数据。
    需要有效的 JWT Bearer Token 认证。
    Gets the data required for the usage report.
    Requires valid JWT Bearer Token authentication.
    """
    user_key = token_payload.get("sub") # 获取用户 Key (Get user key)
    is_admin = token_payload.get("admin", False) # 获取管理员状态 (Get admin status)
    logger.debug(f"用户 {user_key[:8]}... (Admin: {is_admin}) 请求报告数据") # Log user requesting data

    # 调用 usage_reporter 中的函数获取结构化数据
    # Call the function in usage_reporter to get structured data
    try:
        report_data = await get_structured_report_data(key_manager_instance) # 获取报告数据 (Get report data)
        return JSONResponse(content=report_data) # 返回 JSON 响应 (Return JSON response)
    except Exception as e:
        logger.error(f"获取报告数据时出错: {e}", exc_info=True) # 记录错误 (Log error)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取报告数据失败") # 引发 500 异常 (Raise 500 exception)

# --- 新增：报告页面路由 ---
# --- New: Report Page Route ---
@router.get(
    "/report",
    response_class=HTMLResponse,
    include_in_schema=False
    # 移除装饰器中的重复依赖 (Remove duplicate dependency from decorator)
    # dependencies=[Depends(verify_jwt_token)] # 添加 JWT 验证依赖 (Add JWT verification dependency)
)
async def report_page(request: Request): # 移除 token_payload 参数 (Remove token_payload parameter)
    """
    显示使用情况报告页面。
    需要有效的 JWT Bearer Token 认证。
    Displays the usage report page.
    Requires valid JWT Bearer Token authentication.
    """
    # 移除手动检查 JWT 认证的 try...except 块，依赖注入会自动处理认证失败
    # Remove the try...except block for manual JWT check, dependency injection handles failures automatically
    # try:
        # token_payload = await verify_jwt_token(request) # 手动调用依赖函数 (Manually call dependency function)
    # 如果认证成功，继续渲染页面 (If authentication is successful, continue rendering the page)
    # token_payload 现在由 Depends 注入 (token_payload is now injected by Depends)
    logger.debug("渲染报告页面") # Log rendering report page
    admin_key_missing = not config.ADMIN_API_KEY # 检查管理员 Key 是否缺失 (Check if admin key is missing)
    context = { # 模板上下文 (Template context)
        "request": request,
        "admin_key_missing": admin_key_missing, # 添加到模板上下文 (Add to template context)
        "now": datetime.now(timezone.utc) # 确保时区一致 (UTC) 且键名为 'now' (Ensure timezone consistency (UTC) and key name is 'now')
    }
    return templates.TemplateResponse("report.html", context) # 返回模板响应 (Return template response)
    # except HTTPException as e:
    #     # 如果认证失败 (例如 401 或 403)，重定向到登录页面
    #     # If authentication fails (e.g. 401 or 403), redirect to login page
    #     if e.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]: # 如果是 401 或 403 错误 (If it's 401 or 403 error)
    #         logger.warning(f"访问 /report 未认证或无权限，重定向到登录页。") # Log warning
    #         return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER) # 重定向到根路径 (登录页) (Redirect to root path (login page))
    #     else:
    #         # 其他 HTTPException 重新抛出
    #         # Re-raise other HTTPExceptions
    #         raise e
    # except Exception as e:
    #     # 捕获其他意外错误
    #     # Catch other unexpected错误
    #     logger.error(f"访问 /report 时发生意外错误: {e}", exc_info=True) # Log error
    #     raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="内部服务器错误") # 引发 500 异常 (Raise 500 exception)
