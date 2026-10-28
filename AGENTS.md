# Bayledger

Django 5 app (server-rendered, almost no JS) for running an auto repair shop: work orders (OS), parts/labor, store accounts, mechanic settlements, revenue, audit trail. SQLite + a media folder. README.md has the full feature and money-rule description; read it before touching business logic.

## Commands

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py semear_demo        # demo data (--apagar removes it)
.venv/bin/python manage.py runserver 8000
.venv/bin/python manage.py test core          # tests ignore your .env
```

## Conventions

- Code identifiers, UI text and commit-relevant domain terms are in Brazilian Portuguese (`OrdemServico`, `ItemOS`, `Mecanico`, `acerto`, ...); the README glossary maps them. Keep new identifiers in Portuguese to match.
- Settings come from `OFICINA_*` / `DJANGO_*` env vars (see README "Configuration"); nothing shop-specific is hard-coded.
- An OS is never deleted, only cancelled with a reason; numbers are gapless. Important models are audited (`core/audit.py`); the audit log is not editable.
- Money that depends on a changeable setting is frozen on the row when it happens (`ItemOS.percentual_dono`, `OrdemServico.acrescimo_cartao`). Preserve that when adding fields.
- Schema changes need a migration in `core/migrations/`; the deploy script runs them after taking a DB backup. Reverting a deploy does not undo migrations.
- Add or update tests in `core/tests.py` for behavior changes.

## Never commit

Nothing personal goes in this public repo: shop/owner names, hosts, domains, customer data, `.env`, `deploy/deploy.env`, `deploy/servidor.env`, `db.sqlite3`, `*.xlsx`, `.Codex/`. Add `*.example` models instead.

## Deploy

`deploy/README.md` describes the production setup (a headless Mac behind a Cloudflare tunnel, LaunchDaemons, backups). It needs the maintainer's local `deploy/*.env` files and SSH access, so it only works from their own machine.
