# LedgerNest 账巢

<p align="center">
  <b>Self-hosted, mobile-first collaborative accounting with explicit ledger semantics.</b>
</p>

<p align="center">
  <a href="README.en.md">English overview</a> · <a href="README.zh-CN.md">中文完整文档</a>
</p>

<p align="center">
  <img src="docs/overview.svg" alt="LedgerNest accounting semantics and system boundaries" width="96%">
</p>

LedgerNest is a self-hosted collaborative accounting system built around one principle: balances, reports, exports, permissions, audit history, and recovery should all agree because they share the same explicit ledger semantics.

| Core area | Contract |
| --- | --- |
| Transactions | expense / income / transfer / adjustment / refund / reimbursement remain distinct |
| Accounting correctness | transfer does not change total book value; split totals are validated; reports avoid double counting |
| Multi-currency | original amount, FX rate, and base-currency amount are stored explicitly |
| Isolation | owner / admin / editor / viewer roles plus cross-ledger reference checks |
| Recovery | soft delete, audit history, import validation, ZIP backup / restore |
| Delivery | Django + PostgreSQL, mobile-first UI, self-hosted / Tailnet-friendly deployment |

**Stack:** Python 3.12+ · Django 5.2 · PostgreSQL · HTMX · Alpine.js · Tailwind CSS · ECharts · pytest · Docker

For technical reviewers, start with the concise [English overview](README.en.md). For the full feature matrix, deployment guide, permission model, report definitions, import format, and operational notes, use the [Chinese documentation](README.zh-CN.md).

> LedgerNest is applied systems evidence: the emphasis is correctness, isolation, auditability, and product delivery rather than model novelty.

MIT licensed.