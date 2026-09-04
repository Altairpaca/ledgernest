# 账巢 LedgerNest

移动端优先的多用户协作记账系统。单服务端（Django 模块化单体），适合部署在自建 Linux 服务器上、通过 Tailscale Tailnet 内部访问。

- **技术栈**：Python 3.12+ / Django 5.2 / PostgreSQL（本地开发可用 SQLite）/ Django Templates / HTMX / Alpine.js / Tailwind CSS / Apache ECharts
- **定位**：手机解锁 → 打开网页 → 数秒完成一笔记账
- **部署边界**：仅 Tailnet 内部使用，不面向公网；不包含邮箱验证、OAuth、2FA、验证码等公网级基础设施（保留扩展空间）

---

## 功能范围

| 模块 | 能力 |
|---|---|
| 账户 | 用户名登录、注册（模式可配）、个人设置（显示名/语言/时区）、修改密码 |
| 账本 | 创建/切换/归档/恢复/设置（基础货币、时区、财年月份）、多成员协作 |
| 记账 | 支出/收入/转账/调整/**退款/报销**快速记账、分类拆分、多币种（手工汇率）、标签、交易对象 |
| 流水 | 日期分组列表、多条件筛选（日期/关键词/类型/账户/分类/标签/成员/金额）、分页、编辑/复制/软删除/恢复、筛选汇总 |
| 管理 | 账户（6 类）、分类（父子层级、防循环）、标签、成员（4 角色、邀请链接、转移所有权） |
| 预算 | 月度总预算 / 一级分类预算 / 具体分类预算，执行进度条 |
| 报表 | 10 类内置报表（趋势/分类/账户/成员/现金流/标签/交易对象/**退款报销**/**月度对比**/预算执行）+ 受控自定义报表（白名单维度/指标/图表，保存/共享/导出） |
| 导入导出 | CSV/XLSX 流水导入（模板下载、预览、行级错误、重复检测）、筛选导出、报表导出、账本 ZIP 备份/恢复 |
| 审计 | 流水增删改恢复、成员变化、账本设置、导入导出等关键操作留痕 |

## 技术架构与关键取舍

- **模块化单体**：`accounts / ledgers / transactions / reports / imports_exports / audit / core` 七个 Django 应用，一个服务提供页面、接口、静态资源和导出；禁止微服务/事件总线/Redis/异步队列。
- **金额约定**：流水金额一律存储为**正数**，方向由类型决定（expense 为负；income/refund/reimbursement 为正；transfer 账本内转移；adjustment 带符号：正=余额增加，负=余额减少）；多币种保存原币金额+汇率+基础币金额（`amount_base`），服务层统一计算，报表默认使用基础币金额。
- **退款/报销语义**：退款（消费退回）与报销（垫付回收）都使账户余额增加；统计上不并入收入/支出，单列「退款报销」合计；**净额 = 收入 − 支出 + 退款 + 报销**；两者不支持分类拆分，分类归入原支出分类。
- **余额与统计集中化**：所有余额/汇总/趋势计算收敛在 `transactions/services.py`，首页、账户页、报表、导出共用同一套算法，杜绝各页面复制口径。转账只改变账户间分布，不改变账本总资产。
- **拆分统计**：启用拆分时主分类可为空，统计优先基于拆分项（按拆分分类聚合 + 未拆分流水按主分类聚合），防止重复计算；拆分总和必须等于流水金额（模型层强制）。
- **软删除**：流水支持软删除（`deleted_at`），一律不计入余额与统计；账户/分类优先停用而非物理删除。
- **权限模型**：`owner(10) > admin(20) > editor(30) > viewer(40)`，数值越小权限越高。所有账本内 URL 均经成员校验（`_ensure_member`），编辑类操作要求 ≥ editor；跨账本访问返回 404；模型层另设账户/分类归属校验（数据隔离的第二道防线）。
- **报表安全**：自定义报表的维度/指标/排序/图表类型全部走白名单，通过 ORM 构建查询，禁止执行用户输入 SQL。
- **注册模式**：`REGISTRATION_MODE=open|admin|closed`（开放 / 仅管理员创建 / 关闭）。
- **i18n**：页面文案为简体中文（`LANGUAGE_CODE=zh-hans`），Django i18n 结构已就位，可按需接入翻译文件。
- **时区**：所有时间使用时区感知类型（`USE_TZ=True`），账本/用户可独立设置时区。

## 目录结构

```
ledgernest/
├── config/            # Django 配置（settings/urls/wsgi、settings_test）
├── core/              # 基础模型、软删除管理器、权限常量、中间件、演示数据命令
├── accounts/          # 自定义 User、登录/注册/设置/改密
├── ledgers/           # Ledger、Membership、Invitation、账本视图、仪表盘
├── transactions/      # Account/Category/Tag/Transaction/Split/Budget、记账与统计服务
├── reports/           # ReportDefinition、内置报表、自定义报表引擎（白名单）
├── imports_exports/   # CSV/XLSX 导入、导出、备份/恢复
├── audit/             # AuditLog 与审计写入服务
├── templates/         # 全部模板（移动端优先）
├── static/            # Tailwind 构建产物 + vendor（htmx/alpine/echarts 本地化）
├── tests/             # pytest 测试（73 个）+ 移动端冒烟脚本
├── docker/            # 容器入口脚本
├── Dockerfile / docker-compose.yml
└── .env.example
```

## 本地开发（SQLite，最快上手）

```bash
# 1. 环境准备（Python 3.12+；推荐 uv）
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# 2. 数据库迁移
python manage.py migrate

# 3. 静态资源（Tailwind 构建产物已提交，一般无需重跑）
npm install && npx tailwindcss -i static/css/input.css -o static/css/app.css --minify

# 4. 可选：演示数据（两个账本 + 六个月流水）
python manage.py seed_demo

# 5. 启动
python manage.py runserver 127.0.0.1:8000
```

访问 http://127.0.0.1:8000/ 。

## Docker 启动（PostgreSQL，推荐）

```bash
cp .env.example .env        # 修改 DJANGO_SECRET_KEY 与 INITIAL_ADMIN_*
docker compose up -d --build
```

首次启动自动：执行迁移 → 幂等创建初始管理员（`INITIAL_ADMIN_*`）→ 以 Gunicorn 启动。访问 http://<服务器>:8008/ 。

生成密钥：`python -c "import secrets; print(secrets.token_urlsafe(50))"`

## Tailnet 部署（三种访问方式）

1. **tailscale serve 推荐**：服务器上执行 `tailscale serve --bg 8008 http://127.0.0.1:8008`（或按需 `--https=443`），成员通过 `https://<tailnet-hostname>` 访问；Django 侧需将 `https://<tailnet-hostname>` 加入 `DJANGO_CSRF_TRUSTED_ORIGINS`。
2. **直连 Tailnet IP**：成员访问 `http://<100.x.y.z>:8008`；`DJANGO_ALLOWED_HOSTS` 建议设为该 IP（或 `*`），`CSRF_TRUSTED_ORIGINS` 加入该 Origin。
3. **可选反向代理**：nginx/caddy 反代到容器 8000，需配置 `X-Forwarded-Proto`（Django 已读取 `SECURE_PROXY_SSL_HEADER`）。

> 本仓库不会修改宿主机 Tailscale 配置。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `DJANGO_SECRET_KEY` | （未设置时每次启动随机生成） | **生产必设**，随机长串 |
| `DJANGO_DEBUG` | `false` | 本地调试时显式设为 `true` |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | 逗号分隔 |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | localhost 系列 | 逗号分隔 |
| `DB_ENGINE` | 空=SQLite | `postgres` 启用 PostgreSQL |
| `DB_NAME/DB_USER/DB_PASSWORD/DB_HOST/DB_PORT` | ledgernest | Docker 环境自动配置 |
| `REGISTRATION_MODE` | `closed` | `open`/`admin`/`closed` |
| `INITIAL_ADMIN_USERNAME/PASSWORD/EMAIL` | 空 | 首次启动幂等创建管理员 |
| `DEFAULT_CURRENCY` | `CNY` | 新建账本默认货币 |
| `DJANGO_TIME_ZONE` | `Asia/Taipei` | |
| `DEMO_PASSWORD` | `ledgernest123` | 演示数据密码（仅开发） |
| `EXPORT_ROW_LIMIT` | `50000` | 导出行数上限 |

## 管理员与演示数据

```bash
# 幂等创建初始管理员（环境变量驱动，Docker 启动自动执行）
INITIAL_ADMIN_USERNAME=admin INITIAL_ADMIN_PASSWORD=xxxx python manage.py create_initial_admin

# 演示数据（仅开发环境；已存在演示用户时幂等跳过）
python manage.py seed_demo
```

演示账号（密码统一 `ledgernest123`，仅开发环境）：

| 账号 | 角色 |
|---|---|
| `demo_owner` | 家庭账本所有者（另有个人账本；含退款/报销演示流水） |
| `demo_editor` | 家庭账本管理员 |
| `demo_viewer` | 家庭账本编辑者 |

## 测试与检查

```bash
python manage.py check                 # Django 系统检查
python manage.py makemigrations --check --dry-run   # 迁移完整性
python -m pytest                       # 108 个测试（认证/权限/余额/拆分/多币种/退款报销/报表白名单/导入导出/审计/隔离）

# 移动端响应式冒烟（需服务器运行在 127.0.0.1:8001 且已 seed_demo）
python tests/mobile_smoke.py           # 360x800 / 390x844 / 412x915 视口
```

测试覆盖：登录、账本创建与切换、邀请加入与复用拦截、owner/admin/editor/viewer 权限边界、非成员访问隔离、跨账本引用拦截、六类流水创建（含退款/报销）、编辑/复制/软删除/恢复、转账余额、退款报销统计口径、拆分校验与统计、多币种基础金额、分类循环校验、预算统计、内置报表聚合（含退款/对比报表）、自定义报表白名单、CSV 导入预览/行级错误/去重（含退款/报销别名）、XLSX 导出、备份恢复往返、审计日志、数据隔离。测试运行于 SQLite（`config/settings_test.py`），业务逻辑保持数据库无关，PostgreSQL 下已实测统计结果一致。

## 权限模型

| 能力 | owner | admin | editor | viewer |
|---|---|---|---|---|
| 账本设置 / 归档 / 成员管理 / 邀请 | ✓ | ✓ | — | — |
| 记账 / 管理账户分类标签预算 / 导入 | ✓ | ✓ | ✓ | — |
| 查看流水 / 报表 / 导出 | ✓ | ✓ | ✓ | ✓ |
| 转移所有权 | ✓（仅所有者） | — | — | — |

邀请：管理员在成员页生成邀请链接（可限定用户名/邮箱、设置有效期与默认角色），Tailnet 内成员登录后访问链接即加入；邀请一次性使用，过期失效。

## 余额规则

- 账户余额 = 期初余额 + 收入 + 退款 + 报销 + 转入 + 正调整 − 支出 − 转出 − 负调整（软删除流水不计入）。
- 转账不改变账本总资产（总资产 = 各启用账户余额之和）。
- 多币种流水：`amount_base = amount × exchange_rate`（四舍五入到分）；调整的负向金额不换算。
- 创建/修改/删除/恢复流水后，首页、账户页、报表、导出使用同一服务层，保证一致。

## 导入格式（固定模板）

列：`日期, 类型, 金额, 账户, 目标账户, 分类, 交易对象, 描述, 标签`

- 日期：`YYYY-MM-DD`（兼容 `YYYY/MM/DD` 等）；类型：支出/收入/转账/调整/退款/报销（或英文 expense/income/transfer/adjustment/refund/reimbursement）
- 转账必须填写目标账户且不能与账户相同；分类/账户必须已存在；标签不存在自动创建
- 流程：上传 → 预览（行级校验）→ 确认导入。**策略：仅导入有效行**，错误行跳过并在结果页展示；重复检测基于「日期+类型+金额+账户+描述」指纹（近一年），命中即跳过。
- 模板下载：账本内「导入」页。

## 报表定义结构

`ReportDefinition.definition_json` 示例：

```json
{
  "date_range": {"type": "relative", "unit": "month", "value": 3},
  "types": ["expense"],
  "account_ids": [], "category_ids": [], "tag_ids": [], "member_ids": [],
  "group_by": "month",
  "metric": "net",
  "sort": "metric_desc",
  "chart": "bar",
  "limit": 50
}
```

- `date_range`：`relative`（month/year，1-120）或 `absolute`（YYYY-MM-DD）
- `group_by` 白名单：month / day / category / parent_category / account / tag / member / counterparty / type
- `metric` 白名单：amount / income / expense / net / count / avg
- `chart`：none / line / bar / pie；`sort`：metric_desc / metric_asc / label_asc / label_desc
- 保存前经 `validate_definition` 白名单校验归一化，查询全部由 ORM 构建。

## 备份与恢复

- 备份：账本内「导出」页下载 ZIP（`ledger.json`），包含账本信息、成员基础信息、账户、分类、标签、流水、拆分、预算、报表定义；**不包含密码与认证密钥**。
- 恢复（创建新账本，不覆盖现有数据）：

```bash
python manage.py restore_backup backup.zip [--owner 用户名]
```

## 已知限制（第一版有意简化）

- 无邮箱验证/找回密码/OAuth/2FA/登录限流（Tailnet 内部使用，环境变量已预留扩展位）。
- 汇率由用户手工输入（默认 1），不接入实时汇率服务。
- 导入为固定模板，不做字段映射器；去重为轻量指纹（非银行级）。
- 批量操作克制：仅「筛选结果导出」，无批量编辑/删除。
- 退款/报销不支持分类拆分（单笔归一个原消费分类）。
- 报表定义器为分步表单（非拖拽设计器）；自定义报表分组维度不支持多级分组。
- 邮件通知不存在，邀请通过链接/令牌在 Tailnet 内传递。
- 前端未接入 PWA/离线能力；图表数据由后端聚合返回，浏览器端仅渲染。

## 最值得继续实现的功能

1. **PWA + 移动端安装**（manifest/service worker），解锁「主屏打开、离线浏览」的真实 App 体验；
2. **智能记账建议**：基于历史分类/账户/交易对象的记忆与预测，为 Agent 分析（预留的稳定数据接口）提供入口；
3. **多币种实时汇率与账户币种转换**：接入汇率源，完善跨币种账本的日常使用。
