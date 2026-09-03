"""幂等创建初始管理员：从环境变量读取，已存在则不重复创建/重置密码。"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "根据环境变量 INITIAL_ADMIN_* 幂等创建初始管理员"

    def handle(self, *args, **options):
        username = settings.INITIAL_ADMIN_USERNAME
        password = settings.INITIAL_ADMIN_PASSWORD
        email = settings.INITIAL_ADMIN_EMAIL
        if not username or not password:
            self.stdout.write("未设置 INITIAL_ADMIN_USERNAME/PASSWORD，跳过。")
            return
        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=username,
            defaults={"email": email or "", "is_staff": True, "is_superuser": True},
        )
        if created:
            user.set_password(password)
            user.is_staff = True
            user.is_superuser = True
            user.save()
            self.stdout.write(self.style.SUCCESS(f"初始管理员 {username} 已创建。"))
        else:
            self.stdout.write(f"用户 {username} 已存在，跳过（不会重置密码）。")
