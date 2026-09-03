"""导入导出与备份测试。"""
import io
from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from audit.models import AuditLog
from imports_exports.services import (
    backup_ledger,
    export_transactions_xlsx,
    import_rows,
    read_upload,
    restore_ledger,
    validate_rows,
)
from transactions.models import Transaction, TransactionType
from transactions.services import account_balance

from .conftest import make_txn


def _sample_rows():
    return [
        {"日期": "2026-08-05", "类型": "支出", "金额": "88.5", "账户": "现金", "分类": "餐饮", "描述": "导入测试", "标签": "家庭"},
        {"日期": "2026-08-06", "类型": "支出", "金额": "abc", "账户": "现金", "分类": "餐饮"},
        {"日期": "2026-08-06", "类型": "支出", "金额": "30", "账户": "不存在的账户", "分类": "餐饮"},
        {"日期": "2026-08-06", "类型": "转账", "金额": "500", "账户": "现金", "目标账户": "工资卡"},
        {"日期": "2026-08-07", "类型": "收入", "金额": "2000", "账户": "工资卡", "分类": "工资"},
    ]


def test_validate_rows_errors(db, ledger, account_cash, account_bank, category_food, category_salary):
    validated = validate_rows(ledger, _sample_rows())
    assert validated[0]["error"] is None
    assert "金额无法解析" in validated[1]["error"]
    assert "不存在" in validated[2]["error"]
    assert validated[3]["error"] is None
    assert validated[4]["error"] is None


def test_import_only_valid_rows(db, ledger, account_cash, account_bank, category_food, category_salary, user):
    validated = validate_rows(ledger, _sample_rows())
    result = import_rows(ledger, validated, actor=user)
    assert result["created"] == 3
    assert len(result["errors"]) == 2
    assert Transaction.objects.filter(ledger=ledger).count() == 3
    txn = Transaction.objects.get(description="导入测试")
    assert txn.tags.filter(name="家庭").exists()


def test_import_dedup(db, ledger, account_cash, account_bank, category_food, category_salary, user):
    validated = validate_rows(ledger, _sample_rows())
    import_rows(ledger, validated, actor=user)
    result2 = import_rows(ledger, validated, actor=user)
    assert result2["created"] == 0
    assert result2["skipped_duplicates"] == 3


def test_import_audit(db, ledger, user, account_cash):
    validated = validate_rows(ledger, [{"日期": "2026-08-05", "类型": "支出", "金额": "10", "账户": "现金"}])
    import_rows(ledger, validated, actor=user)
    assert AuditLog.objects.filter(ledger=ledger, action="import").exists()


def test_import_creates_balance_effect(db, ledger, account_cash, user):
    validated = validate_rows(ledger, [{"日期": "2026-08-05", "类型": "支出", "金额": "10", "账户": "现金"}])
    import_rows(ledger, validated, actor=user)
    assert account_balance(account_cash) == Decimal("-10.00")


def test_read_upload_csv(db, ledger):
    csv_text = "日期,类型,金额,账户,目标账户,分类,交易对象,描述,标签\n2026-08-05,支出,88.5,现金,,餐饮,,导入测试,家庭\n"
    from django.core.files.uploadedfile import SimpleUploadedFile

    f = SimpleUploadedFile("t.csv", csv_text.encode("utf-8"))
    rows = read_upload(f)
    assert rows[0]["金额"] == "88.5"
    assert rows[0]["日期"] == "2026-08-05"


def test_read_upload_xlsx(db, ledger):
    from openpyxl import Workbook
    from django.core.files.uploadedfile import SimpleUploadedFile

    wb = Workbook()
    ws = wb.active
    ws.append(["日期", "类型", "金额", "账户", "目标账户", "分类", "交易对象", "描述", "标签"])
    ws.append(["2026-08-05", "支出", 88.5, "现金", "", "餐饮", "", "导入测试", ""])
    buf = io.BytesIO()
    wb.save(buf)
    f = SimpleUploadedFile("t.xlsx", buf.getvalue())
    rows = read_upload(f)
    assert rows[0]["金额"] == 88.5


def test_export_xlsx(db, ledger, account_cash, user):
    make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=100, from_account=account_cash, created_by=user)
    data = export_transactions_xlsx(ledger, Transaction.objects.filter(ledger=ledger))
    assert data[:2] == b"PK"  # xlsx 是 zip


def test_backup_and_restore_roundtrip(db, ledger, account_cash, account_bank, category_food, user):
    make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=100, from_account=account_cash, category=category_food)
    make_txn(ledger, txn_type=TransactionType.TRANSFER, amount=50, from_account=account_cash, to_account=account_bank)
    data = backup_ledger(ledger)
    result = restore_ledger(data, user)
    assert result["transactions"] == 2
    assert result["accounts"] == 2
    new_ledger = result["ledger"]
    assert new_ledger.base_currency == "CNY"
    assert Transaction.objects.filter(ledger=new_ledger).count() == 2


def test_backup_does_not_contain_passwords(db, ledger):
    import zipfile

    data = backup_ledger(ledger)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        content = zf.read("ledger.json").decode("utf-8")
    assert "password" not in content.lower()
    assert "secret" not in content.lower()


def test_export_views(db, ledger, account_cash, client_user):
    make_txn(ledger, txn_type=TransactionType.EXPENSE, amount=100, from_account=account_cash)
    resp = client_user.get(reverse("imports:export_transactions", args=[ledger.pk]), {"format": "csv"})
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/csv")
    resp = client_user.get(reverse("imports:export_transactions", args=[ledger.pk]), {"format": "xlsx"})
    assert resp.status_code == 200
    resp = client_user.get(reverse("imports:backup", args=[ledger.pk]))
    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/zip"


def test_import_views_flow(db, ledger, account_cash, client_user):
    resp = client_user.get(reverse("imports:import", args=[ledger.pk]))
    assert resp.status_code == 200
    resp = client_user.get(reverse("imports:template", args=[ledger.pk]))
    assert resp.status_code == 200
    assert resp["Content-Disposition"].startswith("attachment")


def test_viewer_cannot_import(db, ledger, client_carol, viewer_membership):
    resp = client_carol.get(reverse("imports:import", args=[ledger.pk]))
    assert resp.status_code == 403


def test_import_refund_alias(db, ledger, account_cash, category_food, user):
    validated = validate_rows(ledger, [{"日期": "2026-08-05", "类型": "退款", "金额": "99", "账户": "现金", "分类": "餐饮"}])
    assert validated[0]["error"] is None
    result = import_rows(ledger, validated, actor=user)
    assert result["created"] == 1
    txn = Transaction.objects.get(type=TransactionType.REFUND)
    assert account_balance(account_cash) == Decimal("99.00")


def test_import_reimbursement_alias(db, ledger, account_cash, user):
    validated = validate_rows(ledger, [{"日期": "2026-08-05", "类型": "报销", "金额": "200", "账户": "现金"}])
    assert validated[0]["error"] is None
    result = import_rows(ledger, validated, actor=user)
    assert result["created"] == 1
    assert Transaction.objects.filter(type=TransactionType.REIMBURSEMENT).exists()


def test_import_refund_forbids_target_account(db, ledger, account_cash, account_bank, user):
    validated = validate_rows(
        ledger,
        [{"日期": "2026-08-05", "类型": "退款", "金额": "50", "账户": "现金", "目标账户": "工资卡"}],
    )
    assert "目标账户" in (validated[0]["error"] or "")


def test_backup_restore_roundtrip_refund(db, ledger, account_cash, category_food, user):
    from transactions.models import TransactionType as TT

    make_txn(ledger, txn_type=TT.REFUND, amount=66, from_account=account_cash, category=category_food)
    data = backup_ledger(ledger)
    result = restore_ledger(data, user)
    restored = Transaction.objects.get(ledger=result["ledger"], type=TT.REFUND)
    assert restored.amount == Decimal("66.00")
    assert restored.category.name == "餐饮"
