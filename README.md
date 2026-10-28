# Bayledger

A small web app for running an auto repair shop from a phone: open a work order (OS) by license plate, log parts and labor, keep track of what the shop owes its parts suppliers (with a photo of every receipt), see how much money came in, and keep an untouchable history of every change.

It is a Django project with server-rendered pages and almost no JavaScript, so it runs fine on a cheap phone over a slow connection. Data lives in a single SQLite file plus a folder of photos, which makes backups trivial.

> **Status:** early and simple. It was written quickly, with a lot of AI assistance, for one small shop, and has a test suite (`manage.py test core`) but no security audit. Read the code before trusting it with real money, and keep backups.
>
> **Language and locale:** the interface is in Brazilian Portuguese, money is in R$ and customer phone numbers are turned into WhatsApp links with the Brazil country code (configurable). Code identifiers are Portuguese too; the glossary below maps the main ones.

## What it does

| | |
|---|---|
| **Work orders** | Start from the plate: a known car opens its history, a new one asks for make/model/customer. Each OS has parts, labor, mileage and what the customer asked for. |
| **Parts and labor** | Parts record where they came from (store on credit, store paid on the spot, internet, customer brought it, shop stock), the price charged to the customer and the cost at the store. Labor records who did it: the owner, any mechanic, or the owner together with a mechanic. |
| **Store accounts ("fiado")** | Parts bought on credit are tracked per store. *Owed now* = the customer already paid; *expected* = the OS is still open. Pay a store by ticking the parts you are settling; every payment is kept as a record. |
| **Settling with mechanics** | What the shop owes each mechanic for his share of the labor. *Owed now* = the customer already paid; *expected* = the OS is still open. One button records the payment, and every settlement is kept with the jobs it covered. |
| **Receipt photos** | The part form opens the phone camera. Photos are resized (long side 2560 px, JPEG), stripped of GPS/EXIF and stored under `media/notas/`. One paper = one photo: a receipt taken in the last 7 days can be reused for other parts, with a full-screen viewer to flip through them. |
| **Revenue** | Totals for today / this week / this month / custom dates, by payment method, parts vs. labor, the markup on parts, the card surcharge, the labor split between owner and mechanic, and the owner's result. |
| **Print and WhatsApp** | A print-friendly page per OS (it does not show the labor split) and a pre-filled WhatsApp message with the cash and card totals. |
| **Search** | Every OS ever made, by number, plate, customer or car, filterable by status and dates. |
| **Audit trail** | Every create, update and delete of the important models is stored with user, time and before/after values. Nobody can edit it, not even through the admin. |
| **Export** | `/exportar/itens.csv` (owner only) dumps every line item for analysis in a spreadsheet. |

### How an OS moves

```
aberta (open, editable) ──► finalizada ("ready, waiting for payment") ──► paga (paid)
        │                          │                                         │
        └──────────────────────────┴──────────► cancelada (needs a reason) ◄──┘
```

- An open OS can also be paid directly, and a finalized one can be reopened by anyone.
- An OS is **never deleted**, only cancelled with a reason. Numbers are sequential with no gaps.
- Items can only be added or removed while the OS is open. A part already paid to its store, or a labor line already settled with its mechanic, cannot be removed.
- Anyone logged in can finalize, pay or cancel an unpaid OS. Reopening or cancelling a **paid** OS, and reopening a cancelled one, is only for the owner (`is_staff`).

### Money rules

- **Cash price** is the sum of items. **Card price** is cash × `OFICINA_ACRESCIMO_CARTAO` (default 1.10). The **card surcharge** (card price − cash price) is saved on the OS when it is paid by card, so changing the multiplier later does not change past orders. It counts as revenue and goes entirely to the owner, who pays for the card machine.
- **Convenience fee** (*taxa de comodidade*) = what the customer paid for parts − what the store charged. It goes entirely to the owner.
- **Labor split**: every mechanic has his own sharing rule, set in the admin panel (`/painel/` → *Mecânicos*):

  | Mechanic field | Meaning | Default |
  |---|---|---|
  | `percentual_dono_sozinho` | % of the job that goes to the owner when **this mechanic does it alone** | 30 |
  | `percentual_dono_junto` | % that goes to the owner when **the owner and this mechanic do it together** | 50 |

  Each labor line says who did it: the owner (keeps 100%), a mechanic alone, or the owner together with a mechanic. The mechanic gets the remainder, so cents never disappear. For example, with João at 30/50 and Pedro at 20/40, a R$ 200 job done by João alone splits 60 / 140, and the same job done by Pedro alone splits 40 / 160.

  The percentage applied is **saved on the labor line** at the time it is logged. Changing a mechanic's percentages later only affects new lines; past orders and the revenue screen do not move. Two mechanics on the same job? Log it as two labor lines.

- **Settling with a mechanic** (*acerto*): his balance is his share of the labor lines of **paid** OS that are not in any settlement yet. *Paguei* records a settlement (date, amount, who registered it) and links those lines to it, so they leave the balance. Lines of open or ready OS show as *expected* and join the balance once the customer pays.
- **Owner's result** = owner's share of the labor (from everybody) + convenience fee + card surcharge. Only paid OS count, by payment date. Parts and labor are shown at the cash price, with the card surcharge as a separate line, so mechanics' shares are always computed on the cash price.

### Users and permissions

There are no custom roles, only Django's:

- **Owner** = a staff user (the superuser you create at install time). Can open the admin panel at `/painel/`, reopen/cancel paid OS, export the CSV, and sees the audit history.
- **Employees** = any other user. Can do everything day to day (orders, parts, store payments, settling with mechanics, revenue screen) but not the owner-only actions above. Create them in `/painel/` → *Users* → *Add*, leaving *Staff status* unchecked.

- **Mechanics** are not users: they are records in the admin panel with their sharing rule (see above). Stop one from showing up on the form by unticking *Ativo*; his past jobs keep his name. Add as many as you need.

Everything except the login page requires a login, including the receipt photos (`/media/` goes through a login-protected view). Wrong passwords lock a user out for 15 minutes after 5 attempts, and an IP after 20, in both the app and the admin panel. Sessions last 60 days so nobody has to log in again on the phone all the time.

## Quick start

Requires Python 3.10 or newer.

```bash
git clone https://github.com/vitorSiqueiraLobao/Bayledger.git
cd Bayledger
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env                       # optional: your shop's name, labor split, ...
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser # this is the owner
.venv/bin/python manage.py semear_demo     # optional: demo orders in every status
.venv/bin/python manage.py runserver
```

Open <http://localhost:8000>. To add your mechanics (and their sharing rule), go to <http://localhost:8000/painel/> → *Mecânicos* → *Add*. `manage.py semear_demo --apagar` removes only the demo data. A fresh database starts empty.

Run the tests with `.venv/bin/python manage.py test core`. They fix their own configuration, so your `.env` does not affect them.

## Configuration

Nothing about a specific shop is hard-coded. Settings come from environment variables, read from a git-ignored `.env` in the project folder (development) or from the environment itself (production, see [deploy/README.md](deploy/README.md)). A variable that is already in the environment always wins over `.env`. All of them are optional in development.

| Variable | Default | What it does |
|---|---|---|
| `OFICINA_NOME` | `Minha Oficina` | Shop name on the printed OS and the WhatsApp message. |
| `OFICINA_NOME_DONO` | `Dono` | Owner's name as shown on screen. Mechanics are not configured here but in the admin panel. |
| `OFICINA_ACRESCIMO_CARTAO` | `1.10` | Card multiplier over the cash price. |
| `OFICINA_DDI` | `55` | Country code prepended to customer phones for the WhatsApp link. |
| `OFICINA_CLOUDFLARE` | `0` | `1` only behind Cloudflare: trust `CF-Connecting-IP` as the client IP for the login lockout. Anywhere else that header can be forged. |
| `OFICINA_DATA_DIR` | project folder | Where `db.sqlite3`, `media/` and `cache/` live. Point it outside the code in production. |
| `OFICINA_BACKUP_REMOTO` | empty | `rclone` destination for the off-site backup (production). |
| `DJANGO_DEBUG` | `1` | `0` in production. |
| `DJANGO_SECRET_KEY` | dev key when debugging | Required when `DJANGO_DEBUG=0`. |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated hosts; each non-local one is also added to `CSRF_TRUSTED_ORIGINS` as `https://host`. |
| `DJANGO_TIME_ZONE` | `America/Sao_Paulo` | Time zone for dates and "today". |

With `DJANGO_DEBUG=0` the app assumes HTTPS is terminated by a proxy in front of it (secure cookies, `X-Forwarded-Proto`). Plain HTTP in production mode will not let you log in.

Things that are code constants rather than settings: the payment methods, order statuses and part origins (`core/models.py`), the 7-day window for reusing receipt photos (`NOTAS_DIAS` in `core/views.py`), photo size/quality (`FOTO_NOTA_*` in `config/settings.py`) and the login lockout limits (`core/login.py`).

## Endpoints

| Path | What |
|---|---|
| `/` | Home: plate lookup and cars currently in the shop |
| `/entrar/`, `/sair/` | Log in / out |
| `/placa/?placa=ABC1D23` | Plate lookup: known car → its page, new car → new OS form |
| `/carro/<id>/`, `/carro/<id>/nova-os/` | A car and its history, new OS for it |
| `/os/`, `/os/nova/` | Search all OS, new OS for a new car |
| `/os/<id>/` | One OS: items, split, totals, actions |
| `/os/<id>/peca/`, `/os/<id>/servico/` | Add a part / a labor line |
| `/os/<id>/item/<item>/remover/`, `/os/<id>/status/` | POST: remove an item; finalize, pay, reopen, cancel |
| `/os/<id>/imprimir/` | Printable OS |
| `/lojas/`, `/lojas/<id>/` | Store accounts; settle a store (POST) |
| `/mecanicos/`, `/mecanicos/<id>/` | Mechanics' balances; settle with a mechanic (POST) |
| `/faturamento/` | Revenue |
| `/exportar/itens.csv` | CSV of every line item (owner only) |
| `/media/<path>` | Receipt photos (login required) |
| `/painel/` | Django admin: data, photos, audit history (owner only) |

## Project layout

```
config/            Django settings, URLs, WSGI
core/
  models.py        Cliente, Veiculo, Mecanico, Loja, Nota, PagamentoLoja, PagamentoMecanico, OrdemServico, ItemOS, Registro
  views.py         All the screens
  forms.py         Forms and validation
  audit.py         Signals + middleware that fill the audit trail (Registro)
  login.py         Login lockout
  imagens.py       Receipt photo resizing
  management/      `semear_demo` command
  templates/ static/ templatetags/
deploy/            Scripts to run it on a small always-on machine (see deploy/README.md)
.env.example       Development settings model
```

### Glossary

| Portuguese | English |
|---|---|
| OS (*ordem de serviço*) | Work order / repair order |
| Peça | Part |
| Mão de obra, serviço | Labor |
| Loja | Parts store (supplier) |
| Fiado | Buying on credit / a tab |
| Nota | The paper receipt the store hands over with the parts |
| Placa | License plate |
| Dono | Owner |
| Mecânico | Mechanic (a person who does labor, with his own sharing rule) |
| Acerto | Settlement: paying a mechanic his share |
| Taxa de comodidade | Convenience fee (markup on parts) |
| Faturamento | Revenue |
| Registro | Audit-trail entry |

## Running it for real

[deploy/README.md](deploy/README.md) describes a setup that has worked for a small shop: an always-on Mac, gunicorn under launchd, a Cloudflare Tunnel for HTTPS without opening router ports, a daily database backup, and one-command deploy/rollback/backup scripts. The scripts read your server address from `deploy/deploy.env` (git-ignored; model in `deploy/deploy.env.example`), so nothing about your machines is in the repository.

## License

[PolyForm Internal Use License 1.0.0](LICENSE). In plain words: you may use and modify this software to run **your own business** (your own workshop). You may **not** distribute it (not even for free), sublicense it, sell it, offer it as a service to other businesses, or build a product on top of it. The text in [LICENSE](LICENSE) is what counts.

**Freelancers and consultants:** you may install, configure, adapt, maintain and support it for a workshop's own use and charge for that work (see *Additional permission* at the top of [LICENSE](LICENSE)). You may not sell or rent the software itself, bundle it into a product, or host it as a service for several businesses. The work can be sold; the software cannot.

This is a *source-available* license, not an OSI-approved open-source one. If you want to do something it does not allow (for example, offer the app to other shops), contact the author.

The inline icons are from [Lucide](https://lucide.dev) and keep their own license (ISC).

### Printed work-order form

The A4 print view follows the workshop form: colored customer fields, service request,
23 item lines (expanding for larger orders), card/cash totals and handwritten workshop notes.
Print with A4 paper and browser headers/footers disabled; background colors are requested by the page.
Unknown fields such as address, chassis and disposal authorization are left for manual completion.

The header uses private PNG files in `OFICINA_DATA_DIR/media/impressao/`:
`logo.png`, `endereco.png`, `telefone.png` and `pix.png` (the original Pix QR image).
Copy these assets along with the shop's media when deploying; never commit them.
`OFICINA_IMPRESSAO_DIR` can override this directory. Missing assets are omitted, with the
configured shop name used when no logo is installed. Images are embedded in the authenticated
print page, so saving/printing requires no external image service. No payment amount is changed
or encoded by the print view: the supplied QR image is preserved exactly.
