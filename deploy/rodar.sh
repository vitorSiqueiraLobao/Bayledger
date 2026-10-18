#!/bin/bash
# Sobe o app em produção. Chamado pelo launchd (com.oficina.app.plist).
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source "${OFICINA_ENV:-$HOME/oficina-dados/oficina.env}"; set +a

.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py collectstatic --noinput -v0

# 3 workers: alguém mandando foto pelo 4G lento não trava os outros.
exec .venv/bin/gunicorn config.wsgi --bind 127.0.0.1:8000 --workers 3 --timeout 120 \
    --access-logfile - --error-logfile -
