<div align="center">

<pre>
  ____  __  __ __  __   ____  _
 / ___||  \/  |  \/  | / ___|| |__   ___  _ __
 \___ \| |\/| | |\/| | \___ \| '_ \ / _ \| '_ \
  ___) | |  | | |  | |  ___) | | | | (_) | |_) |
 |____/|_|  |_|_|  |_| |____/|_| |_|\___/| .__/
                                         |_|
   Shop Bot  ·  catalog  ·  payments  ·  RBAC
</pre>

<br/>

<p>
  <strong>SMM Shop Bot</strong> is a production-grade Telegram commerce bot for
  digital goods and SMM services — catalog, cart, payments, promos, referrals,
  role-based admin, audit trail, PostgreSQL, optional Redis, and a web admin API.
</p>

<p>
  <a href="#-why-smm-shop-bot">Why</a> ·&nbsp;
  <a href="#-features">Features</a> ·&nbsp;
  <a href="#-architecture">Architecture</a> ·&nbsp;
  <a href="#-quick-start">Quick start</a> ·&nbsp;
  <a href="#-stack">Stack</a>
</p>

<p>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/awhite0030/smm-shop-bot?style=for-the-badge&color=blue" alt="License"/></a>
  &nbsp;<img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python"/>
  &nbsp;<img src="https://img.shields.io/badge/aiogram-3-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white" alt="aiogram"/>
  &nbsp;<img src="https://img.shields.io/badge/PostgreSQL-16-4169E1?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL"/>
  &nbsp;<img src="https://img.shields.io/badge/Redis-optional-DC382D?style=for-the-badge&logo=redis&logoColor=white" alt="Redis"/>
  &nbsp;<img src="https://img.shields.io/badge/Docker-Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker"/>
  &nbsp;<img src="https://img.shields.io/badge/PRs-welcome-brightgreen?style=for-the-badge" alt="PRs welcome"/>
</p>

<p>
  <img src="https://img.shields.io/github/stars/awhite0030/smm-shop-bot?style=social" alt="Stars"/>
  &nbsp;<img src="https://img.shields.io/github/last-commit/awhite0030/smm-shop-bot?style=social" alt="Last commit"/>
</p>

</div>

---

## ✨ Why SMM Shop Bot?

> *A Telegram shop is not a script — it's catalog, money, roles, and recovery.*

| Pain | What the bot does |
| --- | --- |
| Catalog + cart in pure chat | Full user flow: browse → cart → pay → deliver |
| Payment spaghetti | Telegram Payments / Stars, Platega webhooks, TipzySMM |
| Admin without audit | Permission-based admin + audit log |
| No stock truth | Transactional order processing on PostgreSQL |
| Ops without exports | CSV / export endpoints + web admin API |

Use it as a digital goods shop, SMM service panel, or internal commerce automation base.

---

## 🧩 Features

<table>
  <thead>
    <tr>
      <th align="left">Area</th>
      <th align="left">What you get</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><strong>Catalog</strong></td>
      <td>Products and categories with multi-step checkout</td>
    </tr>
    <tr>
      <td><strong>Cart &amp; orders</strong></td>
      <td>Cart, multi-step order form, transactional Postgres writes</td>
    </tr>
    <tr>
      <td><strong>Balance</strong></td>
      <td>User balance + operation history</td>
    </tr>
    <tr>
      <td><strong>Promos</strong></td>
      <td>Promo codes with limits and validity windows</td>
    </tr>
    <tr>
      <td><strong>Referrals</strong></td>
      <td>Built-in referral system</td>
    </tr>
    <tr>
      <td><strong>Reviews</strong></td>
      <td>Post-purchase feedback and ratings</td>
    </tr>
    <tr>
      <td><strong>RBAC admin</strong></td>
      <td>Roles and permission-based admin tools in Telegram</td>
    </tr>
    <tr>
      <td><strong>Broadcast</strong></td>
      <td>Mass messaging to users</td>
    </tr>
    <tr>
      <td><strong>Web admin</strong></td>
      <td>HTTP admin API + panel, CSV/export endpoints</td>
    </tr>
    <tr>
      <td><strong>Payments</strong></td>
      <td>Telegram Payments / Stars, Platega, TipzySMM integrations</td>
    </tr>
    <tr>
      <td><strong>Cache</strong></td>
      <td>Optional Redis for roles, catalog, and stats</td>
    </tr>
    <tr>
      <td><strong>Reliability</strong></td>
      <td>Audit log, recovery / reconciliation jobs, Alembic migrations, pytest</td>
    </tr>
  </tbody>
</table>

---

## 🏗 Architecture

```text
Telegram users
      │
      ▼
 aiogram bot
  ├─ user handlers: catalog, cart, profile, balance, referrals
  ├─ admin handlers: products, categories, roles, promos, broadcast
  ├─ middleware: security, rate limit, auto-answer
  ├─ services: payments, cleanup, recovery, reconciliation
  │
  ├─ PostgreSQL: users, catalog, orders, payments, audit
  ├─ Redis (optional): cache / acceleration
  ├─ Web admin API: management, exports, webhooks
  └─ External APIs: Telegram, Platega, TipzySMM
```

### Layout

```text
bot/
  main.py              # bot + web app bootstrap
  misc/env.py          # configuration
  handlers/user        # shop UX
  handlers/admin       # Telegram admin UX
  database/models      # SQLAlchemy models
  database/methods     # CRUD, transactions, audit
  web/                 # admin API, exports, webhooks
  misc/services        # payments, cleanup, recovery
migrations/            # Alembic
tests/                 # unit / integration
assets/                # demo UI screenshots
```

---

## ⚡ Quick start

```bash
git clone https://github.com/awhite0030/smm-shop-bot.git
cd smm-shop-bot

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env

alembic upgrade head
python run.py
```

### Docker

```bash
cp .env.example .env
docker compose up --build
```

---

## 🧪 Stack

| Layer | Tech |
| --- | --- |
| Bot | Python 3.11+, aiogram 3 |
| DB | PostgreSQL 16, SQLAlchemy async, Alembic |
| Cache | Redis 7 (optional) |
| Web | aiohttp admin API / panel |
| Quality | pytest |
| Deploy | Docker / Docker Compose |

---

## 🔗 Related

Pairs well with [smm-support-bot](https://github.com/awhite0030/smm-support-bot) for a full shop + support stack.

---

## 📊 Stats

<p>
  <img src="https://img.shields.io/github/languages/top/awhite0030/smm-shop-bot?style=flat-square" alt="Top language"/>
  &nbsp;<img src="https://img.shields.io/github/repo-size/awhite0030/smm-shop-bot?style=flat-square" alt="Repo size"/>
  &nbsp;<img src="https://img.shields.io/github/last-commit/awhite0030/smm-shop-bot?style=flat-square" alt="Last commit"/>
  &nbsp;<img src="https://img.shields.io/github/issues/awhite0030/smm-shop-bot?style=flat-square" alt="Issues"/>
</p>

---

## 📄 License

[MIT](LICENSE) © 2026 A. White.

<sub>Catalog. Cart. Cash. Audit. Ship.</sub>
