#!/bin/bash
# Roda no PC (Linux): puxa banco + fotos + oficina.env do Mac para ~/backups/oficina.
# Uso: deploy/puxar-backup.sh
set -euo pipefail
AQUI="$(cd "$(dirname "$0")" && pwd)"
# Host em deploy/deploy.env (não vai para o git; modelo: deploy/deploy.env.example).
[ -f "${OFICINA_DEPLOY_ENV:-$AQUI/deploy.env}" ] && { set -a; source "${OFICINA_DEPLOY_ENV:-$AQUI/deploy.env}"; set +a; }
HOST="${OFICINA_HOST:?defina OFICINA_HOST em deploy/deploy.env (veja deploy/deploy.env.example)}"
DESTINO="${OFICINA_BACKUP_LOCAL:-$HOME/backups/oficina}"
MANTER=30
mkdir -p "$DESTINO"
ARQ="$DESTINO/oficina-$(date +%Y%m%d-%H%M%S).tar.gz"

# No Mac: cópia consistente do SQLite (.backup é seguro com o app rodando) e tar de tudo.
ssh -o BatchMode=yes "$HOST" 'set -e
    cd ~/oficina-dados
    TMP=$(mktemp -d)
    ~/oficina/.venv/bin/python -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close()" db.sqlite3 "$TMP/db.sqlite3"
    cp oficina.env "$TMP/"
    [ -d media ] && ln -s ~/oficina-dados/media "$TMP/media"
    tar czhf - -C "$TMP" .
    rm -rf "$TMP"' > "$ARQ.parcial"
mv "$ARQ.parcial" "$ARQ"
chmod 600 "$ARQ"

ls -1t "$DESTINO"/oficina-*.tar.gz | tail -n +$((MANTER + 1)) | xargs -r rm -f
echo "backup ok: $ARQ ($(du -h "$ARQ" | cut -f1))"
