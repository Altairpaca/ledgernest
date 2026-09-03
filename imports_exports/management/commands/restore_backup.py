"""从备份 zip 恢复账本：python manage.py restore_backup <file.zip> [--owner demo_owner]"""
import sys

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from imports_exports.services import restore_ledger


class Command(BaseCommand):
    help = "从 LedgerNest 备份 zip 恢复账本（创建新账本，不覆盖现有数据）"

    def add_arguments(self, parser):
        parser.add_argument("backup_file", help="备份 zip 文件路径")
        parser.add_argument("--owner", default="", help="账本所有者用户名（默认取第一个超管）")

    def handle(self, *args, **options):
        User = get_user_model()
        owner = None
        if options["owner"]:
            owner = User.objects.filter(username=options["owner"]).first()
        if owner is None:
            owner = User.objects.filter(is_superuser=True).first()
        if owner is None:
            self.stderr.write("找不到所有者用户，请先创建用户（如 manage.py create_initial_admin）。")
            sys.exit(1)
        try:
            with open(options["backup_file"], "rb") as f:
                result = restore_ledger(f.read(), owner)
        except FileNotFoundError:
            self.stderr.write(f"文件不存在：{options['backup_file']}")
            sys.exit(1)
        except ValueError as exc:
            self.stderr.write(f"备份解析失败：{exc}")
            sys.exit(1)
        self.stdout.write(
            self.style.SUCCESS(
                f"恢复完成：账本「{result['ledger'].name}」，流水 {result['transactions']} 笔，账户 {result['accounts']} 个。"
            )
        )
