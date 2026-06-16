# SMM Shop Bot

Production-grade Telegram commerce bot for digital goods and SMM services: catalog, cart, payments, promo codes, referrals, role-based admin tools, audit trail, PostgreSQL storage, optional Redis cache, and a web admin API.

## Русская версия

### Назначение

`SMM Shop Bot` - это Telegram-магазин для цифровых товаров и SMM-услуг. Проект объединяет пользовательский Telegram-flow, административные сценарии, платежные интеграции, складские остатки, промокоды, реферальную механику, аудит операций и web/admin API.

Проект можно использовать как основу для:

- Telegram-магазина цифровых товаров;
- панели управления SMM-услугами;
- витрины с корзиной и пополнением баланса;
- internal commerce automation с ролями и аудитом;
- интеграции с внешними платежными и SMM API.

### Основные возможности

- Каталог товаров и категорий.
- Корзина и многошаговое оформление заказа.
- Покупки с транзакционной обработкой через PostgreSQL.
- Баланс пользователя и история операций.
- Промокоды с ограничениями и сроками действия.
- Реферальная система.
- Отзывы и оценки после покупки.
- Роли и permission-based админка.
- Broadcast-рассылки.
- CSV/export endpoints для операционных данных.
- Web admin API и web admin panel.
- Интеграция с Telegram Payments / Telegram Stars.
- Интеграция с Platega webhook.
- Интеграция с TipzySMM API.
- Optional Redis cache для ролей, каталога и статистики.
- Audit log и recovery/reconciliation jobs.
- Alembic migrations.
- Pytest test suite.

### Архитектура

```text
Telegram users
    |
    v
aiogram bot
    |
    +-- user handlers: catalog, cart, profile, balance, referrals
    +-- admin handlers: products, categories, roles, promos, broadcast
    +-- middleware: security, rate limit, auto answer
    +-- services: payments, cleanup, recovery, order reconciliation
    |
    +-- PostgreSQL: users, catalog, orders, payments, audit
    +-- Redis: optional cache and runtime acceleration
    +-- Web admin API: management, exports, integrations
    +-- External APIs: Telegram, Platega, TipzySMM
```

Ключевые директории:

- `bot/main.py` - запуск Telegram-бота и web-приложения.
- `bot/misc/env.py` - обязательная и опциональная конфигурация.
- `bot/handlers/user` - пользовательские сценарии магазина.
- `bot/handlers/admin` - административные Telegram-сценарии.
- `bot/database/models` - SQLAlchemy-модели.
- `bot/database/methods` - слой CRUD, транзакций, аудита и lazy queries.
- `bot/web` - web admin, API, exports, webhooks.
- `bot/misc/services` - платежи, cleanup, recovery, reconciliation.
- `migrations` - Alembic migrations.
- `tests` - unit/integration тесты.
- `assets` - демонстрационные изображения интерфейсов.

### Технологии

- Python 3.11+
- aiogram 3
- SQLAlchemy async
- PostgreSQL 16
- Alembic
- Redis 7
- Docker / Docker Compose
- pytest
- aiohttp / web routes

### Быстрый старт

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
python run.py
```

Docker:

```bash
cp .env.example .env
docker compose up --build
```

### Переменные окружения

Создайте `.env` на основе `.env.example`.

| Переменная | Назначение |
| --- | --- |
| `TOKEN` | Telegram bot token. |
| `OWNER_ID` | Telegram ID владельца. |
| `POSTGRES_DB` | Имя базы данных. |
| `POSTGRES_USER` | Пользователь PostgreSQL. |
| `POSTGRES_PASSWORD` | Пароль PostgreSQL. |
| `POSTGRES_HOST` | Хост PostgreSQL. |
| `DB_PORT` | Порт PostgreSQL. |
| `REDIS_ENABLED` | Включить Redis cache: `1` или `0`. |
| `REDIS_HOST` | Хост Redis. |
| `REDIS_PASSWORD` | Пароль Redis, если используется. |
| `ADMIN_HOST` | Host web admin/API. |
| `ADMIN_PORT` | Port web admin/API. |
| `ADMIN_USERNAME` | Логин web admin. |
| `ADMIN_PASSWORD` | Пароль web admin. |
| `SECRET_KEY` | Секрет сессий web admin. |
| `ADMIN_API_KEY` | API key для admin endpoints. |
| `WEBHOOK_ENABLED` | Включить Telegram webhook mode. |
| `WEBHOOK_URL` | Public base URL webhook/API. |
| `WEBHOOK_SECRET` | Telegram webhook secret token. |
| `TIPZY_API_KEY` | API key TipzySMM. |
| `TIPZY_BASE_URL` | Base URL TipzySMM API. |
| `PLATEGA_SHOP_ID` | Shop ID Platega. |
| `PLATEGA_SECRET_KEY` | Secret key Platega. |
| `PLATEGA_WEBHOOK_SECRET` | Webhook secret Platega. |
| `TELEGRAM_PROVIDER_TOKEN` | Provider token для Telegram Payments. |

### Безопасность

- Не публикуйте `.env`, production logs, database dumps, Redis dumps, backup-файлы и клиентские выгрузки.
- Меняйте `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `SECRET_KEY`, `ADMIN_API_KEY` перед публикацией web admin.
- Не оставляйте web admin на публичном адресе без reverse proxy, TLS и access control.
- Включайте Redis password, если Redis доступен не только внутри приватной сети.
- Все платежные webhooks должны проверять secret/signature.
- Для production используйте отдельные сервисные ключи с минимальными правами.

### Миграции

```bash
alembic upgrade head
alembic revision --autogenerate -m "change description"
```

### Тестирование

```bash
pip install -r requirements.txt
pytest
```

Для отдельных областей:

```bash
pytest tests/test_payment_service.py
pytest tests/test_role_management.py
pytest tests/test_database_crud.py
```

### Production checklist

- Создать отдельного Telegram-бота.
- Создать production PostgreSQL базу.
- Заполнить `.env` реальными значениями на сервере.
- Применить Alembic migrations.
- Настроить backup PostgreSQL вне репозитория.
- Настроить reverse proxy и TLS для web admin/API.
- Ограничить доступ к web admin.
- Проверить платежные webhook callbacks.
- Проверить audit log и recovery jobs.
- Проверить, что `.env`, логи и базы не попадают в Git.

## English version

### Purpose

`SMM Shop Bot` is a Telegram commerce bot for digital goods and SMM services. It combines a user-facing Telegram flow, administrative tools, payment integrations, stock management, promo codes, referrals, operational audit, and a web admin API.

It can be used as a foundation for:

- a Telegram digital goods shop;
- an SMM services storefront;
- a cart and balance top-up flow;
- internal commerce automation with roles and audit;
- integrations with external payment and SMM APIs.

### Features

- Product and category catalog.
- Shopping cart and multi-step checkout.
- Transactional purchases backed by PostgreSQL.
- User balance and operation history.
- Promo codes with limits and expiration.
- Referral system.
- Post-purchase reviews and ratings.
- Role-based admin tooling.
- Broadcast messaging.
- CSV/export endpoints for operational data.
- Web admin API and web admin panel.
- Telegram Payments / Telegram Stars integration.
- Platega webhook integration.
- TipzySMM API integration.
- Optional Redis cache for roles, catalog, and statistics.
- Audit log and recovery/reconciliation jobs.
- Alembic migrations.
- Pytest test suite.

### Architecture

```text
Telegram users
    |
    v
aiogram bot
    |
    +-- user handlers: catalog, cart, profile, balance, referrals
    +-- admin handlers: products, categories, roles, promos, broadcast
    +-- middleware: security, rate limit, auto answer
    +-- services: payments, cleanup, recovery, order reconciliation
    |
    +-- PostgreSQL: users, catalog, orders, payments, audit
    +-- Redis: optional cache and runtime acceleration
    +-- Web admin API: management, exports, integrations
    +-- External APIs: Telegram, Platega, TipzySMM
```

Important directories:

- `bot/main.py` - Telegram bot and web application startup.
- `bot/misc/env.py` - required and optional configuration.
- `bot/handlers/user` - user-facing shop flows.
- `bot/handlers/admin` - Telegram admin flows.
- `bot/database/models` - SQLAlchemy models.
- `bot/database/methods` - CRUD, transactions, audit, and lazy query layer.
- `bot/web` - web admin, API, exports, and webhooks.
- `bot/misc/services` - payments, cleanup, recovery, and reconciliation.
- `migrations` - Alembic migrations.
- `tests` - unit and integration tests.
- `assets` - interface demo images.

### Stack

- Python 3.11+
- aiogram 3
- SQLAlchemy async
- PostgreSQL 16
- Alembic
- Redis 7
- Docker / Docker Compose
- pytest
- aiohttp / web routes

### Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
python run.py
```

Docker:

```bash
cp .env.example .env
docker compose up --build
```

### Environment

Create `.env` from `.env.example`.

| Variable | Description |
| --- | --- |
| `TOKEN` | Telegram bot token. |
| `OWNER_ID` | Telegram owner ID. |
| `POSTGRES_DB` | Database name. |
| `POSTGRES_USER` | PostgreSQL user. |
| `POSTGRES_PASSWORD` | PostgreSQL password. |
| `POSTGRES_HOST` | PostgreSQL host. |
| `DB_PORT` | PostgreSQL port. |
| `REDIS_ENABLED` | Enable Redis cache: `1` or `0`. |
| `REDIS_HOST` | Redis host. |
| `REDIS_PASSWORD` | Redis password, if enabled. |
| `ADMIN_HOST` | Web admin/API host. |
| `ADMIN_PORT` | Web admin/API port. |
| `ADMIN_USERNAME` | Web admin username. |
| `ADMIN_PASSWORD` | Web admin password. |
| `SECRET_KEY` | Web admin session secret. |
| `ADMIN_API_KEY` | API key for admin endpoints. |
| `WEBHOOK_ENABLED` | Enable Telegram webhook mode. |
| `WEBHOOK_URL` | Public webhook/API base URL. |
| `WEBHOOK_SECRET` | Telegram webhook secret token. |
| `TIPZY_API_KEY` | TipzySMM API key. |
| `TIPZY_BASE_URL` | TipzySMM API base URL. |
| `PLATEGA_SHOP_ID` | Platega shop ID. |
| `PLATEGA_SECRET_KEY` | Platega secret key. |
| `PLATEGA_WEBHOOK_SECRET` | Platega webhook secret. |
| `TELEGRAM_PROVIDER_TOKEN` | Telegram Payments provider token. |

### Security

- Never publish `.env`, production logs, database dumps, Redis dumps, backups, or customer exports.
- Change `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `SECRET_KEY`, and `ADMIN_API_KEY` before exposing the web admin.
- Do not expose the web admin publicly without reverse proxy, TLS, and access control.
- Enable Redis password when Redis is reachable outside a private network.
- Payment webhooks must verify secrets/signatures.
- Use separate service keys with minimal permissions in production.

### Migrations

```bash
alembic upgrade head
alembic revision --autogenerate -m "change description"
```

### Testing

```bash
pip install -r requirements.txt
pytest
```

Focused checks:

```bash
pytest tests/test_payment_service.py
pytest tests/test_role_management.py
pytest tests/test_database_crud.py
```

### Production checklist

- Create a dedicated Telegram bot.
- Create a production PostgreSQL database.
- Fill `.env` with real server-side values.
- Apply Alembic migrations.
- Configure PostgreSQL backups outside the repository.
- Configure reverse proxy and TLS for web admin/API.
- Restrict access to the web admin.
- Verify payment webhook callbacks.
- Verify audit log and recovery jobs.
- Verify that `.env`, logs, and databases are not tracked by Git.
