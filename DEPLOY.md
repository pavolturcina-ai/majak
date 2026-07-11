# MAJÁK — nasadenie (Render + Supabase)

Toto „dá systém do zásuvky": beží 24/7 a o **18:00** a **04:00** sa sám spustí.
Tri bežiace časti: **Supabase** (databáza), **Render web service** (API),
**Render cron jobs** (plánovač). Konektory sú voliteľné.

> Kľúče/heslá zadávaj **priamo v Supabase/Render** ako secrets. Nikdy ich necommituj.

---

## 1. Supabase (databáza) — ~5 min

1. Vytvor projekt na [supabase.com](https://supabase.com) (free tier stačí na štart).
2. Klikni hore **Connect → Connection String → URI** a vyber **Session pooler**
   (port `5432`, IPv4). Prepíš prefix na asyncpg:
   `postgresql://…` → `postgresql+asyncpg://…`. To je tvoj `DATABASE_URL`.
   - ✅ **Session pooler** (5432) — funguje z Render (IPv4) a podporuje prepared statements.
   - ⚠️ **Direct connection** (`db.<ref>.supabase.co`) je na free tieri **len IPv6** → z Render sa nedovolá.
   - ⚠️ **Transaction pooler** (`6543`) — rozbíja prepared statements, nepoužívaj.
   - Meno používateľa je `postgres.<project-ref>`. Heslo so špeciálnymi znakmi URL-encode.
3. **Project Settings → API** — skopíruj `SUPABASE_URL`, `service_role` kľúč
   (`SUPABASE_SERVICE_KEY`) a **JWT Secret** (`SUPABASE_JWT_SECRET`).

Migrácie sa aplikujú automaticky pri deployi (`preDeployCommand: python -m majak.migrate`).
Prípadne ručne z lokálu: `DATABASE_URL=… python -m majak.migrate`.

---

## 2. Anthropic (LLM kľúč) — ~2 min

1. Na [console.anthropic.com](https://console.anthropic.com) vytvor **API key**.
2. To je `ANTHROPIC_API_KEY`. (Bez neho beží extrakcia v heuristickom režime.)

---

## 3. Render (API + cron) — ~10 min

1. Na [render.com](https://render.com) → **New → Blueprint**.
2. Pripoj tento GitHub repo a vetvu → Render načíta `render.yaml` a navrhne
   **3 služby**: `majak-api` (web) + `majak-close-open` + `majak-fill-overnight` (cron).
3. Pred *Apply* vyplň secrets v env-groupe **`majak-secrets`**:
   - `DATABASE_URL`, `ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`,
     `SUPABASE_JWT_SECRET`, `CRON_SECRET` (dlhý náhodný reťazec).
   - Konektory nechaj prázdne, doplníš neskôr.
4. **Apply.** Render zbuildí image, spustí migrácie a nasadí API + cron joby.

Overenie:
```bash
curl https://majak-api.onrender.com/health          # {"status":"ok"}
# manuálne spusti nočný job (nemusíš čakať na 4:00):
curl -X POST https://majak-api.onrender.com/api/scheduler/fill-overnight \
     -H "Authorization: Bearer <CRON_SECRET>"
```

---

## 4. Čas / DST ⏰

Render cron beží v **UTC**. `render.yaml` je nastavený na **letný čas (CEST, UTC+2)**:

| Job | Lokálne | `render.yaml` (leto) | Zmeň v zime (CET, UTC+1) |
|-----|---------|----------------------|--------------------------|
| close-and-open | 18:00 | `0 16 * * *` | `0 17 * * *` |
| fill-overnight | 04:00 | `0 2 * * *`  | `0 3 * * *`  |

V zime (koniec októbra) uprav dva `schedule` riadky a redeployni.

---

## 5. Konektory (aby malo čo v noci sťahovať) — voliteľné

Bez nich sa job o 4:00 spustí, ale nič nenačíta. Keď budeš mať tokeny, pridaj
ich do `majak-secrets` a redeployni:
- **Gmail:** `GMAIL_CLIENT_ID/SECRET/REFRESH_TOKEN` (OAuth)
- **Slack:** `SLACK_BOT_TOKEN`
- **Fathom:** `FATHOM_API_KEY`
- **Kalendár:** `GCAL_CLIENT_ID/SECRET/REFRESH_TOKEN`

Implementácia `fetch_since` je pripravená ako seam v `src/majak/connectors/`.

---

## 6. Napojenie frontendu (Pages) na živé API — voliteľné

Report/Zoznam/Osoby zatiaľ bežia nad embedded `SEED`. Keď chceš živé dáta z DB:
- V **Import** stránke (`/import.html`) nastav *API base* na
  `https://majak-api.onrender.com/api` + token — vstupy pôjdu rovno do pipeline.
- Report neskôr prepneme z `const SEED` na `fetch('/api/days/current')`
  (Phase-1 adaptér `frontend/api.js` je pripravený).

---

## Zhrnutie: čo o 4:00 spraví
`majak-fill-overnight` → pre každý konektor `fetch_since(cursor)` → pipeline →
prepočíta otvorený deň → pošle notifikáciu. Idempotentné (dedup + kurzory), takže
opakované spustenie nič nepokazí.
