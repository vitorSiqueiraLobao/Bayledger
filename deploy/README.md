# Running it on an always-on machine

This is the setup the app was built for: everything on one small machine (a Mac mini in our case) with Django served by gunicorn, SQLite and the photos on disk. A Cloudflare Tunnel exposes it over HTTPS without opening any router port. Database and photos live in one folder, `~/oficina-dados`, and that folder is what you back up.

The server side below is written for **macOS + launchd**. The scripts that run on *your* computer (`deploy.sh`, `puxar-backup.sh`) need `ssh`, `tar` and `curl`, so Linux and macOS both work. For a Linux server you would run `deploy/rodar.sh` under systemd instead of launchd; that is not provided here.

Replace `YOUR_USER` with the server's user name wherever it appears.

## 1. Keep the machine awake

```bash
sudo pmset -a sleep 0 disksleep 0 autorestart 1
```

This disables sleep and makes the Mac **come back by itself after a power cut**. A small UPS is worth it.

## 2. Code and dependencies

Use `~/oficina`, not `~/Documents` or `~/Desktop`: macOS blocks background services in those folders.

```bash
brew install python@3.13 rclone cloudflared
git clone https://github.com/vitorSiqueiraLobao/crm-oficina.git ~/oficina
cd ~/oficina
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
mkdir -p ~/oficina-dados/logs
cp deploy/oficina.env.example ~/oficina-dados/oficina.env
chmod 600 ~/oficina-dados/oficina.env
```

Edit `~/oficina-dados/oficina.env`: set `DJANGO_SECRET_KEY`, your domain, the data folder, your shop's name and labor split. Every variable is described in the root [README](../README.md#configuration). Set `OFICINA_CLOUDFLARE=1` if you use the tunnel below.

Create the owner:

```bash
set -a; source ~/oficina-dados/oficina.env; set +a
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
```

Employees are created later in the app, at `/painel/` → *Users* → *Add*, with *Staff status* unchecked. Mechanics (and how each one shares the labor with the owner) are added at `/painel/` → *Mecânicos*.

## 3. Start on boot (launchd)

```bash
for f in app backup; do
  sed "s/YOUR_USER/$(whoami)/g" deploy/com.oficina.$f.plist | sudo tee /Library/LaunchDaemons/com.oficina.$f.plist >/dev/null
  sudo chown root:wheel /Library/LaunchDaemons/com.oficina.$f.plist
  sudo launchctl bootstrap system /Library/LaunchDaemons/com.oficina.$f.plist
done
curl -I http://localhost:8000/entrar/                # should answer 200
tail -f ~/oficina-dados/logs/app.log
```

`com.oficina.app` runs `deploy/rodar.sh` (migrate, collectstatic, gunicorn on `127.0.0.1:8000`) and restarts it if it dies. `com.oficina.backup` runs `deploy/backup.sh` every day at 3 am. After updating the code by hand:

```bash
sudo launchctl kickstart -k system/com.oficina.app
```

## 4. Cloudflare Tunnel

You need a domain on Cloudflare.

```bash
cloudflared tunnel login
cloudflared tunnel create oficina                    # note the ID
cloudflared tunnel route dns oficina oficina.example.com
cp deploy/cloudflared-config.yml.example ~/.cloudflared/config.yml   # edit ID, user and domain
sed "s/YOUR_USER/$(whoami)/g" deploy/com.oficina.tunnel.plist | sudo tee /Library/LaunchDaemons/com.oficina.tunnel.plist >/dev/null
sudo chown root:wheel /Library/LaunchDaemons/com.oficina.tunnel.plist
sudo launchctl bootstrap system /Library/LaunchDaemons/com.oficina.tunnel.plist
```

The tunnel runs as a LaunchDaemon under your user and reads `~/.cloudflared/config.yml`; its log is `~/oficina-dados/logs/tunnel.log`. (The plist assumes Homebrew on Apple Silicon: `/opt/homebrew/bin/cloudflared`.)

In the Cloudflare dashboard turn on **SSL/TLS → Edge Certificates → Always Use HTTPS**.

## 5. Off-site backup (optional but recommended)

If the machine's disk dies, everything is lost without this.

1. Create a Cloudflare R2 bucket (or any storage `rclone` supports) and an API token.
2. Run `rclone config` and create a remote, e.g. `r2`.
3. Put `OFICINA_BACKUP_REMOTO=r2:your-bucket` in `oficina.env`.
4. Test: `deploy/backup.sh && rclone ls r2:your-bucket | head`

`backup.sh` always keeps 60 days of compressed database copies locally. With a remote set it also uploads the photos and the database copies using `rclone copy`, not `sync`, on purpose: deleting a photo on the server does **not** delete it from the backup.

To restore: download the latest `db-YYYYMMDD.sqlite3.gz`, gunzip it to `~/oficina-dados/db.sqlite3` and run `rclone copy r2:your-bucket/media ~/oficina-dados/media`.

## 6. Day to day, from your computer

The scripts need to know where the server is, and what your shop's settings are. Create two git-ignored files (neither is ever sent as code):

```bash
cp deploy/deploy.env.example deploy/deploy.env       # OFICINA_HOST and OFICINA_URL: where the server is
cp deploy/servidor.env.example deploy/servidor.env   # your shop's settings, pushed to the server's oficina.env
```

Your computer needs key-based SSH access to `OFICINA_HOST`. Then:

```bash
deploy/deploy.sh             # runs the tests, backs up the database on the server, sends the code, applies servidor.env, restarts, checks health
deploy/deploy.sh --env       # only applies servidor.env and restarts (for a config change, no code)
deploy/deploy.sh --voltar    # rolls back to the previous version
deploy/puxar-backup.sh       # pulls database + photos + oficina.env to ~/backups/oficina (keeps the last 30)
```

`deploy.sh` replaces the code folder but never touches `~/oficina-dados`, and it does not send `.env`, `deploy/deploy.env`, `deploy/servidor.env`, `.git`, the database or the photos.

**The server keeps its own `oficina.env`** (the one from step 2, with the secret key and the data folder). On each deploy `deploy/sincronizar_env.py` copies into it the keys listed in `servidor.env`, so a setting added by a new version reaches the server without editing it by hand. It only touches `OFICINA_*` keys (except `OFICINA_DATA_DIR`) and `DJANGO_TIME_ZONE`, it ignores empty values, and it keeps the previous file as `oficina.env.anterior`. The secret key, domain and data folder are never changed from your computer.

`--voltar` goes back to the previous code but does **not** undo database migrations. If the new version changed the database, run `manage.py migrate core <previous migration>` on the server first, or restore the backup the deploy took.
