#!/bin/sh
# LedgerNest 容器入口：迁移 → 收集静态文件 → 幂等创建管理员 → 启动应用
set -e

echo "==> 执行数据库迁移"
python manage.py migrate --noinput

echo "==> 收集静态文件（与代码版本保持一致）"
python manage.py collectstatic --noinput

echo "==> 创建初始管理员（若配置了 INITIAL_ADMIN_*）"
python manage.py create_initial_admin

echo "==> 启动服务"
exec "$@"
