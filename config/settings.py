"""LedgerNest 账巢 - Django 配置。

所有环境相关配置通过环境变量覆盖，.env.example 提供完整清单。
本地开发默认 SQLite；Docker/生产环境通过 DB_* 环境变量使用 PostgreSQL。
"""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def env_list(name: str, default: str = "") -> list[str]:
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    secrets.token_urlsafe(50),
)

DEBUG = env_bool("DJANGO_DEBUG", False)

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    "http://localhost,http://127.0.0.1,http://100.64.0.0,http://[::1]",
)

# ---------------------------------------------------------------------------
# 应用
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # 领域模块
    "core",
    "accounts",
    "audit",
    "ledgers",
    "transactions",
    "reports",
    "imports_exports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.ledger_context_middleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.ledger_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ---------------------------------------------------------------------------
# 数据库：默认 SQLite（轻量开发），设置 DB_ENGINE=postgres 时使用 PostgreSQL。
# 业务逻辑保持数据库无关，不得依赖 SQLite 私有特性。
# ---------------------------------------------------------------------------
if os.environ.get("DB_ENGINE", "").lower() == "postgres":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DB_NAME", "ledgernest"),
            "USER": os.environ.get("DB_USER", "ledgernest"),
            "PASSWORD": os.environ.get("DB_PASSWORD", ""),
            "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
            "PORT": os.environ.get("DB_PORT", "5432"),
            "CONN_MAX_AGE": 60,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.environ.get("SQLITE_PATH", BASE_DIR / "db.sqlite3"),
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 6}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

AUTH_USER_MODEL = "accounts.User"

# ---------------------------------------------------------------------------
# 国际化：页面文案默认简体中文，保留 Django i18n 扩展空间
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "zh-hans"


def _valid_timezone(name: str) -> str:
    """校验时区标识符；非法值（如 Asia/Beijing 这类非标准别名）回退默认。"""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    if not name:
        return "Asia/Taipei"
    try:
        ZoneInfo(name)
        return name
    except (ZoneInfoNotFoundError, ValueError):
        import warnings

        warnings.warn(f"无效的 DJANGO_TIME_ZONE: {name!r}，已回退为 Asia/Taipei", stacklevel=2)
        return "Asia/Taipei"


TIME_ZONE = _valid_timezone(os.environ.get("DJANGO_TIME_ZONE", "Asia/Taipei"))
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# 静态与媒体
# ---------------------------------------------------------------------------
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# ---------------------------------------------------------------------------
# 登录与会话
# ---------------------------------------------------------------------------
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "ledgers:index"
LOGOUT_REDIRECT_URL = "accounts:login"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14  # 14 天
SESSION_SAVE_EVERY_REQUEST = True

# ---------------------------------------------------------------------------
# 安全基础（即使仅 Tailnet 内部访问也保留基本防护）
# ---------------------------------------------------------------------------
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
CSRF_COOKIE_HTTPONLY = False  # 模板使用 CSRF token 需要可读 cookie（默认）
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ---------------------------------------------------------------------------
# 业务配置（可通过环境变量覆盖）
# ---------------------------------------------------------------------------
# 注册模式：open=任何人可注册；admin=仅管理员创建用户；closed=关闭注册
REGISTRATION_MODE = os.environ.get("REGISTRATION_MODE", "closed")
DEFAULT_CURRENCY = os.environ.get("DEFAULT_CURRENCY", "CNY")
DEFAULT_FISCAL_YEAR_START = int(os.environ.get("DEFAULT_FISCAL_YEAR_START", "1"))
# 导出/导入单次行数上限，防止内存暴涨
EXPORT_ROW_LIMIT = int(os.environ.get("EXPORT_ROW_LIMIT", "50000"))
# 首次启动自动创建管理员（幂等，不重复创建/重置）
INITIAL_ADMIN_USERNAME = os.environ.get("INITIAL_ADMIN_USERNAME", "")
INITIAL_ADMIN_PASSWORD = os.environ.get("INITIAL_ADMIN_PASSWORD", "")
INITIAL_ADMIN_EMAIL = os.environ.get("INITIAL_ADMIN_EMAIL", "")
# 演示数据密码（仅开发环境）
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "ledgernest123")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024  # 上传限制 20MB
