"""生成演示数据：两个用户、共享账本+个人账本、账户/分类/标签、
最近六个月流水、转账、拆分、预算、报表定义。

仅用于开发环境。账号密码见 README（默认 ledgernest123）。
"""
import random
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand

from accounts.models import User
from core.models import ROLE_ADMIN, ROLE_EDITOR, ROLE_OWNER
from ledgers.models import Ledger, LedgerMembership
from reports.models import ReportDefinition
from transactions.models import (
    Account,
    Budget,
    BudgetType,
    Category,
    Tag,
    Transaction,
    TransactionSplit,
    TransactionType,
)

random.seed(20260801)


class Command(BaseCommand):
    help = "生成演示数据（幂等：已存在同名用户则跳过）"

    def handle(self, *args, **options):
        if User.objects.filter(username__in=["demo_owner", "demo_editor", "demo_viewer"]).exists():
            self.stdout.write(self.style.WARNING("演示用户已存在，跳过。如需重建请先清空数据库。"))
            return
        password = settings.DEMO_PASSWORD
        owner = User.objects.create_user("demo_owner", "owner@example.com", password, display_name="林小巢")
        editor = User.objects.create_user("demo_editor", "editor@example.com", password, display_name="陈小账")
        viewer = User.objects.create_user("demo_viewer", "viewer@example.com", password, display_name="王小观")

        # 共享账本
        shared = Ledger.objects.create(
            name="家庭账本", description="全家共同记账", owner=owner,
            base_currency="CNY", timezone="Asia/Shanghai",
        )
        LedgerMembership.objects.create(ledger=shared, user=owner, role=ROLE_OWNER, invited_by=owner)
        LedgerMembership.objects.create(ledger=shared, user=editor, role=ROLE_ADMIN, invited_by=owner)
        LedgerMembership.objects.create(ledger=shared, user=viewer, role=ROLE_EDITOR, invited_by=owner)

        # 个人账本
        personal = Ledger.objects.create(
            name="个人账本", description="自己的零花钱", owner=owner, base_currency="CNY",
        )
        LedgerMembership.objects.create(ledger=personal, user=owner, role=ROLE_OWNER, invited_by=owner)

        self._seed_ledger(shared, owner, editor, viewer, shared_mode=True)
        self._seed_ledger(personal, owner, None, None, shared_mode=False)

        self.stdout.write(self.style.SUCCESS("演示数据已生成。"))
        self.stdout.write(f"账号：demo_owner / demo_editor / demo_viewer，密码：{password}（仅开发环境）")


    def _seed_ledger(self, ledger, owner, editor, viewer, shared_mode):
        cash = Account.objects.create(ledger=ledger, name="现金", account_type="cash", sort_order=1, opening_balance=Decimal("500.00"))
        bank = Account.objects.create(ledger=ledger, name="工资卡", account_type="bank", sort_order=2, opening_balance=Decimal("12000.00"))
        credit = Account.objects.create(ledger=ledger, name="信用卡", account_type="credit", sort_order=3, opening_balance=Decimal("-1500.00"))
        wallet = Account.objects.create(ledger=ledger, name="支付宝", account_type="wallet", sort_order=4, opening_balance=Decimal("800.00"))

        cat_defs = [
            ("餐饮", "expense", "🍜", [("早餐", "🥐"), ("午餐", "🍚"), ("晚餐", "🍲"), ("夜宵", "🌙"), ("零食", "🍿"), ("饮品", "🧋")]),
            ("交通", "expense", "🚌", [("公交地铁", "🚇"), ("打车", "🚕"), ("加油", "⛽"), ("停车", "🅿️"), ("过路费", "🛣️")]),
            ("购物", "expense", "🛒", [("日用品", "🧻"), ("服饰", "👕"), ("数码", "📱"), ("美妆", "💄"), ("宠物", "🐾")]),
            ("居住", "expense", "🏠", [("房租", "🏢"), ("房贷", "🏦"), ("水电燃气", "💡"), ("物业", "🏘️"), ("维修", "🔧")]),
            ("娱乐", "expense", "🎬", [("电影", "🎥"), ("游戏", "🎮"), ("运动", "⚽"), ("旅行", "✈️"), ("KTV", "🎤")]),
            ("医疗", "expense", "💊", [("药品", "💊"), ("门诊", "🏥"), ("住院", "🛏️"), ("体检", "🩺")]),
            ("人情", "expense", "🧧", [("请客", "🍽️"), ("送礼", "🎁"), ("红包", "🧧"), ("随份子", "💌")]),
            ("教育", "expense", "📚", [("学费", "🎓"), ("培训", "📖"), ("书籍", "📕"), ("文具", "✏️")]),
            ("通讯", "expense", "📱", [("话费", "📞"), ("流量", "📶"), ("宽带", "🌐")]),
            ("育儿", "expense", "🍼", [("奶粉", "🍼"), ("玩具", "🧸"), ("母婴用品", "👶")]),
            ("其他", "expense", "📦", [("其他支出", "📦")]),
            ("工资", "income", "💰", []),
            ("奖金", "income", "🏆", []),
            ("兼职", "income", "💼", []),
            ("理财", "income", "📈", []),
            ("投资", "income", "📊", []),
            ("红包", "income", "🧧", []),
            ("礼金", "income", "💝", []),
            ("退款", "income", "↩️", []),
            ("报销", "income", "🧾", []),
            ("其他收入", "income", "🎁", []),
        ]
        top_cats = {}
        sub_cats = {}
        for name, kind, icon, subs in cat_defs:
            top = Category.objects.create(ledger=ledger, kind=kind, name=name, icon=icon, sort_order=len(top_cats))
            top_cats[(kind, name)] = top
            sub_cats[(kind, name)] = []
            for s_name, s_icon in subs:
                sub = Category.objects.create(
                    ledger=ledger, kind=kind, name=s_name, parent=top, icon=s_icon,
                    sort_order=len(sub_cats[(kind, name)]),
                )
                sub_cats[(kind, name)].append(sub)

        tag_house = Tag.objects.create(ledger=ledger, name="家庭", color="#eab308")
        tag_work = Tag.objects.create(ledger=ledger, name="工作", color="#3b82f6")
        tag_urgent = Tag.objects.create(ledger=ledger, name="重要", color="#ef4444")

        accounts = [cash, bank, credit, wallet]
        creators = [owner] + ([editor, viewer] if shared_mode else [])
        # 最近 6 个月示例流水
        today = date.today()
        for month_offset in range(5, -1, -1):
            # 每月 5 号发工资
            payday = (today.replace(day=1) - timedelta(days=month_offset * 31)).replace(day=5)
            if payday > today:
                continue
            if month_offset < 3 or random.random() < 0.8:
                Transaction.objects.create(
                    ledger=ledger, type=TransactionType.INCOME, date=payday,
                    amount=Decimal("12800.00"), currency="CNY", exchange_rate=Decimal("1"),
                    amount_base=Decimal("12800.00"), from_account=bank, category=top_cats[("income", "工资")],
                    counterparty="公司", description="月薪", created_by=owner, updated_by=owner,
                ).tags.add(tag_work)
            # 每天 1-4 笔日常支出
            for day in range(1, 29):
                d = (today.replace(day=1) - timedelta(days=month_offset * 31)).replace(day=day)
                if d > today:
                    break
                if random.random() > 0.7:
                    continue
                for _ in range(random.randint(1, 2)):
                    top_name = random.choice(["餐饮", "交通", "购物", "娱乐", "医疗", "居住"])
                    subs = sub_cats[("expense", top_name)]
                    cat = random.choice(subs) if subs and random.random() < 0.6 else top_cats[("expense", top_name)]
                    amount = Decimal(str(random.randint(5, 300) if top_name != "居住" else random.choice([1800, 2200, 2600])))
                    acc = random.choice(accounts)
                    creator = random.choice(creators)
                    txn = Transaction.objects.create(
                        ledger=ledger, type=TransactionType.EXPENSE, date=d, amount=amount,
                        currency="CNY", exchange_rate=Decimal("1"), amount_base=amount,
                        from_account=acc, category=cat,
                        counterparty=random.choice(["全家便利店", "滴滴出行", "美团外卖", "淘宝", "星巴克", "盒马鲜生", "物业", "医院"]),
                        description=random.choice(["", "日常开销", "周末采购", "聚餐"]),
                        created_by=creator, updated_by=creator,
                    )
                    if random.random() < 0.15:
                        txn.tags.add(tag_house)
                    if random.random() < 0.1:
                        txn.tags.add(tag_urgent)
            # 每月一次拆分流水（聚餐：餐饮+娱乐）
            if month_offset < 3:
                d = (today.replace(day=1) - timedelta(days=month_offset * 31)).replace(day=15)
                if d <= today:
                    txn = Transaction.objects.create(
                        ledger=ledger, type=TransactionType.EXPENSE, date=d,
                        amount=Decimal("600.00"), currency="CNY", exchange_rate=Decimal("1"),
                        amount_base=Decimal("600.00"), from_account=credit,
                        counterparty="朋友聚餐", description="拆分示例：餐饮 400 + 娱乐 200",
                        created_by=owner, updated_by=owner,
                    )
                    TransactionSplit.objects.create(transaction=txn, category=top_cats[("expense", "餐饮")], amount=Decimal("400.00"))
                    TransactionSplit.objects.create(transaction=txn, category=top_cats[("expense", "娱乐")], amount=Decimal("200.00"))
                    txn.tags.add(tag_house)
            # 每月一次退款（电商退货，归原支出分类）
            d = (today.replace(day=1) - timedelta(days=month_offset * 31)).replace(day=12)
            if d <= today and random.random() < 0.8:
                Transaction.objects.create(
                    ledger=ledger, type=TransactionType.REFUND, date=d,
                    amount=Decimal("129.00"), currency="CNY", exchange_rate=Decimal("1"),
                    amount_base=Decimal("129.00"), from_account=wallet,
                    category=top_cats[("expense", "购物")],
                    counterparty="淘宝", description="退货退款", created_by=owner, updated_by=owner,
                )
            # 每季度一次报销（出差垫付回收）
            d = (today.replace(day=1) - timedelta(days=month_offset * 31)).replace(day=8)
            if d <= today and month_offset % 3 == 1 and random.random() < 0.7:
                Transaction.objects.create(
                    ledger=ledger, type=TransactionType.REIMBURSEMENT, date=d,
                    amount=Decimal("580.00"), currency="CNY", exchange_rate=Decimal("1"),
                    amount_base=Decimal("580.00"), from_account=bank,
                    category=top_cats[("expense", "交通")],
                    counterparty="公司", description="出差报销", created_by=owner, updated_by=owner,
                )
            # 每月一次转账（工资卡 → 支付宝）
            d = (today.replace(day=1) - timedelta(days=month_offset * 31)).replace(day=20)
            if d <= today:
                Transaction.objects.create(
                    ledger=ledger, type=TransactionType.TRANSFER, date=d,
                    amount=Decimal("2000.00"), currency="CNY", exchange_rate=Decimal("1"),
                    amount_base=Decimal("2000.00"), from_account=bank, to_account=wallet,
                    description="日常周转", created_by=owner, updated_by=owner,
                )
            # 每月一次调整（信用卡还款后余额修正）
            d = (today.replace(day=1) - timedelta(days=month_offset * 31)).replace(day=25)
            if d <= today:
                Transaction.objects.create(
                    ledger=ledger, type=TransactionType.ADJUSTMENT, date=d,
                    amount=Decimal("150.00"), currency="CNY", exchange_rate=Decimal("1"),
                    amount_base=Decimal("150.00"), from_account=credit,
                    description="还款后修正", created_by=owner, updated_by=owner,
                )

        # 预算
        for month_offset in (0, 1):
            m = today.month - month_offset
            y = today.year
            if m <= 0:
                m += 12
                y -= 1
            Budget.objects.create(ledger=ledger, budget_type=BudgetType.TOTAL, year=y, month=m, amount=Decimal("8000.00"))
            Budget.objects.create(ledger=ledger, budget_type=BudgetType.TOP_CATEGORY, category=top_cats[("expense", "餐饮")], year=y, month=m, amount=Decimal("2000.00"))
            Budget.objects.create(ledger=ledger, budget_type=BudgetType.CATEGORY, category=top_cats[("expense", "购物")], year=y, month=m, amount=Decimal("1500.00"))

        # 报表定义
        ReportDefinition.objects.create(
            ledger=ledger, name="近 6 个月支出趋势", description="按月聚合的支出报表",
            created_by=owner,
            definition_json={
                "date_range": {"type": "relative", "unit": "month", "value": 6},
                "types": ["expense"], "account_ids": [], "category_ids": [], "tag_ids": [], "member_ids": [],
                "group_by": "month", "metric": "expense", "sort": "label_asc", "chart": "line", "limit": 12,
            },
        )
        ReportDefinition.objects.create(
            ledger=ledger, name="餐饮分类明细", description="按子分类聚合",
            created_by=owner,
            definition_json={
                "date_range": {"type": "relative", "unit": "month", "value": 3},
                "types": ["expense"], "account_ids": [],
                "category_ids": [top_cats[("expense", "餐饮")].id], "tag_ids": [], "member_ids": [],
                "group_by": "category", "metric": "amount", "sort": "metric_desc", "chart": "pie", "limit": 20,
            },
        )
