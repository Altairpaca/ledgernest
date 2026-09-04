"""测试专用配置：继承主配置，仅调整测试环境需要的项。"""
from .settings import *  # noqa: F401,F403

# 测试环境不执行 collectstatic，使用非 manifest 静态存储
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Django's test client uses this host while preserving production-safe defaults.
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]

# 测试中密码校验从简，避免常见密码干扰
AUTH_PASSWORD_VALIDATORS = []

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        "TEST": {"NAME": ":memory:"},
    }
}
