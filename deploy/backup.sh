#!/bin/bash
# Backup diário: cópia consistente do banco + fotos, local e fora do Mac.
# Chamado pelo launchd (com.oficina.backup.plist) todo dia às 3h.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source "${OFICINA_ENV:-$HOME/oficina-dados/oficina.env}"; set +a

DADOS="$OFICINA_DATA_DIR"
mkdir -p "$DADOS/backups"
ARQ="$DADOS/backups/db-$(date +%Y%m%d).sqlite3"

# .backup do SQLite é seguro com o app rodando (copiar o arquivo direto não é).
.venv/bin/python - "$DADOS/db.sqlite3" "$ARQ" <<'PY'
import sqlite3, sys
origem, destino = sys.argv[1], sys.argv[2]
with sqlite3.connect(origem) as src, sqlite3.connect(destino) as dst:
    src.backup(dst)
PY
gzip -f "$ARQ"

# Mantém 60 dias de cópias do banco no Mac
find "$DADOS/backups" -name 'db-*.sqlite3.gz' -mtime +60 -delete

if [ -n "${OFICINA_BACKUP_REMOTO:-}" ]; then
    # "copy" e não "sync": apagar uma foto no Mac NÃO apaga no backup (de propósito).
    rclone copy "$DADOS/media" "$OFICINA_BACKUP_REMOTO/media"
    rclone copy "$DADOS/backups" "$OFICINA_BACKUP_REMOTO/backups"
fi
echo "backup ok $(date)"
