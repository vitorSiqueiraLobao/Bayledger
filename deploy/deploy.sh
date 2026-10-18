#!/bin/bash
# Roda no PC (Linux): testa, manda o código para o Mac e reinicia o app.
# Uso: deploy/deploy.sh            (deploy normal)
#      deploy/deploy.sh --voltar   (volta para a versão anterior)
set -euo pipefail
cd "$(dirname "$0")/.."
# Host e domínio ficam em deploy/deploy.env (não vai para o git; modelo: deploy/deploy.env.example).
[ -f "${OFICINA_DEPLOY_ENV:-deploy/deploy.env}" ] && { set -a; source "${OFICINA_DEPLOY_ENV:-deploy/deploy.env}"; set +a; }
HOST="${OFICINA_HOST:?defina OFICINA_HOST em deploy/deploy.env (veja deploy/deploy.env.example)}"
URL="${OFICINA_URL:+${OFICINA_URL%/}/entrar/}"

reiniciar_e_conferir() {
    # O launchd (KeepAlive) sobe o gunicorn de novo; o rodar.sh roda migrate e collectstatic.
    ssh -o BatchMode=yes "$HOST" 'pkill -f "gunicorn config.wsgi" || true
        for i in $(seq 30); do
            sleep 2
            [ "$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/entrar/)" = 200 ] && exit 0
        done
        echo "app não subiu, fim do log:"; tail -20 ~/oficina-dados/logs/app.log; exit 1'
    [ -n "$URL" ] && echo "público: $(curl -s -o /dev/null -w '%{http_code}' "$URL")"
    return 0
}

if [ "${1:-}" = "--voltar" ]; then
    ssh -o BatchMode=yes "$HOST" 'set -e; cd ~
        [ -d oficina.anterior ] || { echo "não há versão anterior"; exit 1; }
        mv oficina.anterior oficina.tmp; mv oficina/.venv oficina.tmp/
        mv oficina oficina.anterior; mv oficina.tmp oficina'
    reiniciar_e_conferir
    echo "voltou para a versão anterior"
    exit 0
fi

echo "== testes"
.venv/bin/python manage.py test core -v0

echo "== backup do banco no Mac (antes de migrations)"
ssh -o BatchMode=yes "$HOST" '~/oficina/deploy/backup.sh' | tail -1

echo "== enviando código"
# Pasta nova + troca: arquivos apagados aqui também somem lá. O .venv é reaproveitado.
# Configuração local (.env, deploy.env) e o .git nunca vão: o Mac tem o próprio oficina.env.
tar czf - --exclude=.venv --exclude=__pycache__ --exclude=db.sqlite3 --exclude='*.xlsx' \
    --exclude=media --exclude=staticfiles --exclude=cache --exclude=.claude \
    --exclude=.git --exclude=.env --exclude=deploy/deploy.env . |
ssh -o BatchMode=yes "$HOST" 'set -e; cd ~
    rm -rf oficina.novo; mkdir oficina.novo; tar xzf - -C oficina.novo
    mv oficina/.venv oficina.novo/
    rm -rf oficina.anterior; mv oficina oficina.anterior; mv oficina.novo oficina
    oficina/.venv/bin/pip install -q --disable-pip-version-check -r oficina/requirements.txt'

echo "== reiniciando"
reiniciar_e_conferir
echo "deploy ok"
