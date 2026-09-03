"""移动端响应式冒烟检查：360x800 / 390x844 / 412x915 视口。

验证：登录 → 账本首页（4 卡汇总）→ 快速记账（6 类型 tab + 九宫格键盘 data-key）
→ 流水列表（4 卡 + 标记）→ 日历 → 报表中心（10 项）→ 图表切换。
用法：python tests/mobile_smoke.py（需服务器运行在 127.0.0.1:8001，且已 seed_demo）
"""
import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8001"
VIEWPORTS = [(360, 800), (390, 844), (412, 915)]


def check_no_overflow(page, label):
    overflow = page.evaluate(
        "() => ({scrollW: document.documentElement.scrollWidth, clientW: document.documentElement.clientWidth})"
    )
    if overflow["scrollW"] > overflow["clientW"] + 2:
        print(f"  ✗ [{label}] 横向溢出: scrollWidth={overflow['scrollW']} clientWidth={overflow['clientW']}")
        return False
    return True


def main():
    failures = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for w, h in VIEWPORTS:
            print(f"\n=== 视口 {w}x{h} ===")
            page = browser.new_page(viewport={"width": w, "height": h})
            page.goto(f"{BASE}/login/", wait_until="domcontentloaded")
            page.fill('input[name="username"]', "demo_owner")
            page.fill('input[name="password"]', "ledgernest123")
            page.click('button[type="submit"]')
            page.wait_for_url(f"{BASE}/l/**", timeout=15000)
            page.wait_for_timeout(1200)
            if not check_no_overflow(page, "首页"):
                failures += 1
            content = page.content()
            if "退款报销" in content and "净额" in content:
                print("  ✓ 首页 4 卡汇总（含退款报销）")
            else:
                print("  ✗ 首页汇总卡异常")
                failures += 1

            page.goto(f"{BASE}/l/1/new/", wait_until="domcontentloaded")
            page.wait_for_timeout(800)
            tabs_ok = True
            for label in ["支出", "收入", "转账", "调整", "退款", "报销"]:
                if not page.locator(f'[role="tablist"] >> text={label}').count():
                    print(f"  ✗ 缺少类型 tab: {label}")
                    tabs_ok = False
            if tabs_ok:
                print("  ✓ 6 类型 tab 齐全")
            else:
                failures += 1
            if page.locator('[data-key="8"]').count():
                page.click('[data-key="8"]')
                page.click('[data-key="8"]')
                page.click('[data-key="."]')
                page.click('[data-key="5"]')
                got = page.locator("#amount-input").input_value()
                if got == "88.5":
                    print("  ✓ 九宫格键盘输入 88.5")
                else:
                    print(f"  ✗ 九宫格键盘异常: {got!r}")
                    failures += 1
                page.click('[data-key="clear"]')
                page.click('[data-key="1"]')
                page.click('[data-key="0"]')
            page.locator("#account-chips button").first.click()
            page.locator(".cat-grid button").first.click()
            page.click('button[type="submit"]')
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(800)
            if not check_no_overflow(page, "记账完成页"):
                failures += 1
            if "已记一笔" not in page.content():
                print("  ✗ 记账未成功")
                failures += 1
            else:
                print("  ✓ 快速记账成功")

            page.goto(f"{BASE}/l/1/transactions/", wait_until="domcontentloaded")
            page.wait_for_timeout(500)
            if not check_no_overflow(page, "流水列表"):
                failures += 1
            if "退款报销" in page.content():
                print("  ✓ 流水 4 卡汇总")
            else:
                print("  ✗ 流水汇总卡异常")
                failures += 1
            page.click('text=筛选')
            page.wait_for_timeout(300)
            if page.locator("#filter-panel").is_visible():
                print("  ✓ 筛选抽屉打开")
            page.evaluate("document.getElementById('filter-panel').classList.add('hidden')")

            nav = page.locator("nav.fixed")
            if nav.count() and nav.is_visible():
                joined = " ".join(nav.locator("a").all_inner_texts())
                if all(k in joined for k in ["首页", "流水", "记一笔", "报表", "更多"]):
                    print("  ✓ 底部导航五项齐全")
                else:
                    print(f"  ✗ 底部导航异常: {joined}")
                    failures += 1
            else:
                print("  ✗ 底部导航不可见")
                failures += 1

            page.goto(f"{BASE}/l/1/calendar/", wait_until="domcontentloaded")
            page.wait_for_timeout(600)
            if page.locator('a[href*="date_from"]').count():
                print("  ✓ 流水日历渲染")
            else:
                print("  ✗ 日历无日期链接")
                failures += 1
            if not check_no_overflow(page, "流水日历"):
                failures += 1

            page.goto(f"{BASE}/l/1/", wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            if page.locator("#trend-chart canvas").count():
                print("  ✓ ECharts 趋势图已渲染")
            else:
                print("  ✗ 趋势图未渲染")
                failures += 1
            if page.locator("#assets-chart canvas").count():
                print("  ✓ 资产分布环形图已渲染")
            else:
                print("  ✗ 资产环形图未渲染")
                failures += 1
            page.click('a[href*="month="]')
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(1500)
            if "回本月" in page.content():
                print("  ✓ 月份切换生效")
            else:
                print("  ✗ 月份切换失败")
                failures += 1

            page.goto(f"{BASE}/l/1/reports/", wait_until="domcontentloaded")
            page.wait_for_timeout(500)
            content = page.content()
            if "退款/报销统计" in content and "月度收支对比" in content:
                print("  ✓ 报表中心含退款统计与月度对比")
            else:
                print("  ✗ 报表中心缺新报表项")
                failures += 1
            page.goto(f"{BASE}/l/1/reports/builtin/refund/", wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            if page.locator("#chart-main canvas").count():
                print("  ✓ 退款/报销统计图表渲染")
            else:
                print("  ✗ 退款统计图未渲染")
                failures += 1
            page.goto(f"{BASE}/l/1/reports/builtin/trend/", wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            if page.locator("#chart-main canvas").count():
                print("  ✓ 趋势报表图表渲染")
                page.click('text=折线图')
                page.wait_for_timeout(800)
                if page.locator("#chart-main canvas").count():
                    print("  ✓ 图表切换为折线图")
                else:
                    print("  ✗ 图表切换失败")
                    failures += 1
            else:
                print("  ✗ 趋势报表图未渲染")
                failures += 1

            page.goto(f"{BASE}/l/1/categories/", wait_until="domcontentloaded")
            page.wait_for_timeout(500)
            if page.locator(".category-grid").count():
                print("  ✓ 分类宫格渲染")
            else:
                print("  ✗ 分类宫格缺失")
                failures += 1
            if not check_no_overflow(page, "分类宫格"):
                failures += 1

            page.close()
        browser.close()
    print(f"\n结果: {'全部通过' if failures == 0 else f'{failures} 处失败'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
