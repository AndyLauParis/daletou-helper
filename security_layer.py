"""公网部署安全层（两个 FastAPI 应用共用）。

包含：
- 安全响应头（CSP / HSTS / X-Frame-Options 等）；
- 异常请求拦截（路径穿越、扫描器路径、危险方法、超长 URL、超大请求体）；
- 按客户端 IP 的滑动窗口限流（全局限流 + 登录注册 / 昂贵接口严格限流）；
- 受信反向代理下的真实客户端 IP 与 HTTPS 识别；
- HttpOnly Cookie 会话与 CSRF 防护（仅针对 Cookie 会话）。

所有配置均可用环境变量覆盖，见 ``SecuritySettings.from_env``。
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("security")

SESSION_COOKIE_NAME = "helper_session"

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
ALLOWED_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})

# 扫描器与探测工具 User-Agent 关键字（小写）
SCANNER_UA_MARKERS = (
    "sqlmap",
    "nikto",
    "nmap",
    "masscan",
    "zgrab",
    "acunetix",
    "nessus",
    "openvas",
    "dirbuster",
    "gobuster",
    "wfuzz",
    "nuclei",
    "wpscan",
    "hydra",
)

# 常见后台 / 配置 / 版本库探测路径关键字（小写）
BLOCKED_PATH_MARKERS = (
    "wp-admin",
    "wp-login",
    "wp-content",
    "phpmyadmin",
    "pma/",
    "actuator",
    "cgi-bin",
    "xmlrpc.php",
    "vendor/phpunit",
    "solr/",
    "jenkins",
    "hudson",
    "id_rsa",
    "config.php",
    ".env",
    ".git",
    ".svn",
    ".hg",
    ".aws",
    ".ssh",
    ".ds_store",
)

# 认证接口：登录 / 注册（严格限流）
AUTH_RATE_PATHS = frozenset({"/api/helper/auth/login", "/api/helper/auth/register"})

# 会触发上游抓取或重计算的接口（严格限流）
EXPENSIVE_RATE_PATHS = frozenset(
    {
        "/api/data/refresh",
        "/api/model1",
        "/api/model2",
        "/api/model3",
        "/api/history/test",
        "/api/helper/check",
        "/api/helper/lab/interpret",
    }
)

# 监控探针不参与限流，避免反向代理健康检查被误伤
RATE_LIMIT_EXEMPT_PATHS = frozenset({"/api/helper/health"})

# 反馈截图上传需要更大的请求体上限（业务层仍限制单图 5 MB）
LARGE_BODY_PATHS = {"/api/helper/feedback": 6 * 1024 * 1024}

# 强制 HTTPS 时放行的本机探针路径
HTTPS_REDIRECT_EXEMPT_PATHS = frozenset({"/api/helper/health"})

CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "manifest-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)

DEFAULT_ALLOWED_HOSTS = ("localhost", "127.0.0.1", "testserver", "[::1]")
DEFAULT_TRUSTED_PROXIES = ("127.0.0.1", "::1")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("环境变量 %s=%r 不是整数，使用默认值 %s", name, raw, default)
        return default
    return value if value >= minimum else default


def _env_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.environ.get(name)
    if raw is None:
        return default
    items = tuple(item.strip() for item in raw.split(",") if item.strip())
    # 空列表会让 TrustedHostMiddleware 放行所有 Host，退回安全默认值
    return items or default


@dataclass
class SecuritySettings:
    """安全层运行时配置；测试可直接修改字段。"""

    allowed_hosts: tuple[str, ...] = DEFAULT_ALLOWED_HOSTS
    trusted_proxies: tuple[str, ...] = DEFAULT_TRUSTED_PROXIES
    require_https: bool = False
    hsts_max_age: int = 15_552_000
    max_body_bytes: int = 256 * 1024
    max_url_length: int = 2048
    block_scanners: bool = True
    cookie_secure_mode: str = "auto"  # auto | always | never
    window_seconds: int = 60
    global_rate_limit: int = 600
    auth_rate_limit: int = 30
    expensive_rate_limit: int = 60

    @classmethod
    def from_env(cls) -> "SecuritySettings":
        return cls(
            allowed_hosts=_env_list("HELPER_ALLOWED_HOSTS", DEFAULT_ALLOWED_HOSTS),
            trusted_proxies=_env_list(
                "HELPER_TRUSTED_PROXIES", DEFAULT_TRUSTED_PROXIES
            ),
            require_https=_env_bool("HELPER_REQUIRE_HTTPS", False),
            hsts_max_age=_env_int(
                "HELPER_HSTS_MAX_AGE", 15_552_000, minimum=0
            ),
            max_body_bytes=_env_int(
                "HELPER_MAX_BODY_BYTES", 256 * 1024, minimum=1024
            ),
            max_url_length=_env_int("HELPER_MAX_URL_LENGTH", 2048, minimum=128),
            block_scanners=_env_bool("HELPER_BLOCK_SCANNERS", True),
            cookie_secure_mode=(
                os.environ.get("HELPER_SESSION_COOKIE_SECURE", "auto").strip().lower()
                or "auto"
            ),
            window_seconds=_env_int("HELPER_RATE_WINDOW_SECONDS", 60, minimum=1),
            global_rate_limit=_env_int(
                "HELPER_RATE_GLOBAL_PER_MINUTE", 600, minimum=1
            ),
            auth_rate_limit=_env_int("HELPER_RATE_AUTH_PER_MINUTE", 30, minimum=1),
            expensive_rate_limit=_env_int(
                "HELPER_RATE_EXPENSIVE_PER_MINUTE", 60, minimum=1
            ),
        )


SECURITY = SecuritySettings.from_env()


class SlidingWindowLimiter:
    """线程安全的滑动窗口限流器，key 数量有上界。"""

    def __init__(self, max_keys: int = 8192) -> None:
        self.max_keys = max_keys
        self._events: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window: float) -> tuple[bool, int]:
        now = time.monotonic()
        cutoff = now - window
        with self._lock:
            bucket = [ts for ts in self._events.get(key, ()) if ts > cutoff]
            if len(bucket) >= limit:
                retry_after = max(1, int(bucket[0] + window - now) + 1)
                self._events[key] = bucket
                return False, retry_after
            bucket.append(now)
            self._events[key] = bucket
            if len(self._events) > self.max_keys:
                self._prune_all(cutoff)
                if len(self._events) > self.max_keys:
                    oldest = min(self._events, key=lambda item: self._events[item][-1])
                    self._events.pop(oldest, None)
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._events.clear()

    def _prune_all(self, cutoff: float) -> None:
        for key in list(self._events):
            bucket = [ts for ts in self._events[key] if ts > cutoff]
            if bucket:
                self._events[key] = bucket
            else:
                del self._events[key]


LIMITER = SlidingWindowLimiter()


def reset_security_state() -> None:
    """清空限流状态（供测试使用）。"""
    LIMITER.reset()


def peer_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def client_ip(request: Request) -> str:
    """真实客户端 IP：仅当直连方是受信代理时才解析 X-Forwarded-For。"""
    peer = peer_ip(request)
    if peer not in SECURITY.trusted_proxies:
        return peer
    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return peer
    hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
    for hop in reversed(hops):
        if hop not in SECURITY.trusted_proxies:
            return hop
    return hops[0] if hops else peer


def request_is_secure(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    if peer_ip(request) not in SECURITY.trusted_proxies:
        return False
    proto = request.headers.get("x-forwarded-proto", "")
    return proto.split(",")[0].strip().lower() == "https"


def external_host(request: Request) -> str:
    """浏览器视角的 Host，仅在受信代理下采用 X-Forwarded-Host。"""
    if peer_ip(request) in SECURITY.trusted_proxies:
        forwarded = request.headers.get("x-forwarded-host")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.headers.get("host", "")


def _cookie_secure(request: Request) -> bool:
    mode = SECURITY.cookie_secure_mode
    if mode == "always":
        return True
    if mode == "never":
        return False
    return request_is_secure(request)


def set_session_cookie(response, token: str, request: Request, max_age: int) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=max_age,
        path="/",
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(request),
    )


def clear_session_cookie(response, request: Request) -> None:
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(request),
    )


def _path_is_blocked(path: str) -> bool:
    if "\x00" in path:
        return True
    lowered = unquote(path).lower()
    if ".." in lowered:
        return True
    if any(segment.startswith(".") for segment in lowered.split("/") if segment):
        return True
    return any(marker in lowered for marker in BLOCKED_PATH_MARKERS)


def _rate_bucket_and_limit(method: str, path: str, query: str) -> tuple[str, int]:
    if path in AUTH_RATE_PATHS:
        return "auth", SECURITY.auth_rate_limit
    if path in EXPENSIVE_RATE_PATHS:
        return "expensive", SECURITY.expensive_rate_limit
    if path.startswith("/api/helper/games/") and (
        path.endswith("/refresh") or "refresh=true" in query.lower()
    ):
        return "expensive", SECURITY.expensive_rate_limit
    return "global", SECURITY.global_rate_limit


async def _send_json(
    scope: Scope,
    send: Send,
    status: int,
    detail: str,
    extra: dict | None = None,
) -> None:
    response = JSONResponse({"detail": detail}, status_code=status, headers=extra)
    await response(scope, _empty_receive, send)


async def _send_plain(scope: Scope, send: Send, status: int, text: str) -> None:
    response = PlainTextResponse(text, status_code=status)
    await response(scope, _empty_receive, send)


async def _empty_receive() -> Message:
    return {"type": "http.request", "body": b"", "more_body": False}


async def _read_limited_body(receive: Receive, limit: int) -> bytes:
    body = bytearray()
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            raise ConnectionError("client disconnected")
        body.extend(message.get("body", b""))
        if len(body) > limit:
            raise ValueError("body too large")
        if not message.get("more_body", False):
            return bytes(body)


def _replay_receive(body: bytes) -> Receive:
    sent = False

    async def receive() -> Message:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


class RequestGuardMiddleware:
    """异常请求拦截 + 限流 + HTTPS 强制。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        path = scope.get("path", "/")
        query = (scope.get("query_string") or b"").decode("latin-1")
        ip = client_ip(request)
        method = request.method.upper()

        if method not in ALLOWED_METHODS:
            logger.warning("拦截危险方法 %s %s ip=%s", method, path, ip)
            await _send_json(scope, send, 405, "请求方法不被允许")
            return

        url_length = len(scope.get("raw_path") or b"") + len(
            scope.get("query_string") or b""
        )
        if url_length > SECURITY.max_url_length:
            logger.warning("拦截超长 URL ip=%s len=%s", ip, url_length)
            await _send_json(scope, send, 414, "请求地址过长")
            return

        # 先计数再拦截：扫描探测同样消耗配额，避免无成本刷日志
        if path not in RATE_LIMIT_EXEMPT_PATHS:
            bucket, limit = _rate_bucket_and_limit(method, path, query)
            allowed, retry_after = LIMITER.allow(
                f"{bucket}:{ip}", limit, SECURITY.window_seconds
            )
            if not allowed:
                logger.warning("限流触发 bucket=%s ip=%s path=%s", bucket, ip, path)
                await _send_json(
                    scope,
                    send,
                    429,
                    "请求过于频繁，请稍后再试",
                    {"Retry-After": str(retry_after)},
                )
                return

        if _path_is_blocked(path):
            logger.warning("拦截可疑路径 %s ip=%s", path[:200], ip)
            await _send_plain(scope, send, 404, "Not Found")
            return

        user_agent = request.headers.get("user-agent", "").lower()
        if SECURITY.block_scanners and any(
            marker in user_agent for marker in SCANNER_UA_MARKERS
        ):
            logger.warning("拦截扫描器 UA=%s ip=%s", user_agent[:120], ip)
            await _send_plain(scope, send, 403, "Forbidden")
            return

        if (
            SECURITY.require_https
            and path not in HTTPS_REDIRECT_EXEMPT_PATHS
            and not request_is_secure(request)
        ):
            target = f"https://{external_host(request)}{path}"
            if query:
                target = f"{target}?{query}"
            await RedirectResponse(target, status_code=308)(
                scope, _empty_receive, send
            )
            return

        if method not in SAFE_METHODS:
            body_limit = SECURITY.max_body_bytes
            path_limit = LARGE_BODY_PATHS.get(path.rstrip("/"))
            if path_limit is not None:
                body_limit = max(body_limit, path_limit)
            content_length = request.headers.get("content-length")
            if content_length is not None:
                try:
                    declared = int(content_length)
                except ValueError:
                    await _send_json(scope, send, 400, "Content-Length 无效")
                    return
                if declared > body_limit:
                    logger.warning(
                        "拦截超大请求体 ip=%s path=%s length=%s",
                        ip,
                        path,
                        declared,
                    )
                    await _send_json(scope, send, 413, "请求体过大")
                    return
            try:
                body = await _read_limited_body(receive, body_limit)
            except ValueError:
                logger.warning("拦截超大请求体 ip=%s path=%s", ip, path)
                await _send_json(scope, send, 413, "请求体过大")
                return
            except ConnectionError:
                return
            receive = _replay_receive(body)

        await self.app(scope, receive, send)


class CSRFMiddleware:
    """Cookie 会话下的 CSRF 防护：校验 Origin / Sec-Fetch-Site。

    Bearer 令牌请求（无 Cookie）不经过此校验，脚本与 API 客户端不受影响。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        if (
            request.method.upper() in SAFE_METHODS
            or not scope.get("path", "").startswith("/api/")
            or SESSION_COOKIE_NAME not in request.cookies
        ):
            await self.app(scope, receive, send)
            return

        if not self._same_origin(request):
            logger.warning(
                "拦截跨站请求 path=%s ip=%s origin=%s",
                scope.get("path"),
                client_ip(request),
                request.headers.get("origin", "-")[:200],
            )
            await _send_json(scope, send, 403, "跨站请求被拒绝")
            return

        await self.app(scope, receive, send)

    @staticmethod
    def _same_origin(request: Request) -> bool:
        origin = request.headers.get("origin")
        if origin:
            parts = urlsplit(origin)
            if parts.scheme not in {"http", "https"} or not parts.netloc:
                return False
            return parts.netloc.lower() == external_host(request).lower()
        fetch_site = request.headers.get("sec-fetch-site")
        if fetch_site and fetch_site.lower() not in {"same-origin", "none"}:
            return False
        return True


def _safe_request_id(request: Request) -> str:
    provided = request.headers.get("x-request-id", "")
    if (
        provided
        and len(provided) <= 64
        and all(char.isalnum() or char in "-_." for char in provided)
    ):
        return provided
    return uuid.uuid4().hex


class SecurityHeadersMiddleware:
    """统一安全响应头。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        path = scope.get("path", "/")
        request_id = _safe_request_id(request)
        secure = request_is_secure(request)
        is_api = path.startswith("/api/")

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "no-referrer"
                headers["Content-Security-Policy"] = CSP_POLICY
                headers["Permissions-Policy"] = (
                    "geolocation=(), microphone=(), camera=(), payment=(), usb=()"
                )
                headers["Cross-Origin-Opener-Policy"] = "same-origin"
                headers["Cross-Origin-Resource-Policy"] = "same-origin"
                headers["X-Permitted-Cross-Domain-Policies"] = "none"
                headers["X-Request-ID"] = request_id
                if secure:
                    headers["Strict-Transport-Security"] = (
                        f"max-age={SECURITY.hsts_max_age}; includeSubDomains"
                    )
                content_type = headers.get("content-type", "")
                if is_api or "text/html" in content_type:
                    headers["Cache-Control"] = "no-store"
                if "server" in headers:
                    del headers["server"]
                if "x-powered-by" in headers:
                    del headers["x-powered-by"]
            await send(message)

        await self.app(scope, receive, send_wrapper)


def install_security(app, *, app_name: str = "app") -> None:
    """安装安全中间件（顺序：受信 Host → 安全头 → CSRF → 请求守卫）。"""
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    app.add_middleware(RequestGuardMiddleware)
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(SECURITY.allowed_hosts),
        www_redirect=False,
    )
    logger.info(
        "安全层已启用 app=%s hosts=%s https=%s",
        app_name,
        ",".join(SECURITY.allowed_hosts),
        SECURITY.require_https,
    )
