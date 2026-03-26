# The Skipper

Your fantasy baseball analyst — starting with SP starts optimization, built to expand.

## Stack

- **Next.js 14** — frontend (React + TypeScript)
- **Python serverless functions** — ESPN API calls (via `espn-api` package) and Anthropic API
- **Vercel** — hosting + env var management

## Project structure

```
the-skipper/
├── api/
│   ├── espn.py          # Python: fetches roster + free agents from ESPN
│   └── analyze.py       # Python: calls Anthropic API for recommendations
├── pages/
│   ├── _app.tsx
│   └── index.tsx        # Main UI
├── styles/
│   └── globals.css
├── requirements.txt     # Python deps (espn-api, anthropic, requests)
├── package.json
├── vercel.json          # Routes /api/*.py to Python runtime
└── tsconfig.json
```

---

## Deploy to Vercel

### 1. Fork / clone this repo

```bash
git clone <your-repo-url>
cd the-skipper
```

### 2. Install dependencies locally (optional, for dev)

```bash
npm install
pip install -r requirements.txt
```

### 3. Get your ESPN cookies (one-time)

1. Log into **fantasy.espn.com** in Chrome
2. Open DevTools (`F12`) → **Application** tab → **Cookies** → `https://www.espn.com`
3. Find and copy:
   - `espn_s2` — long encoded string
   - `SWID` — looks like `{A1B2C3D4-XXXX-XXXX-XXXX-XXXXXXXXXXXX}`

These cookies persist across sessions, so you rarely need to refresh them.

### 4. Set environment variables in Vercel

In your Vercel project → **Settings** → **Environment Variables**, add:

| Variable | Value |
|---|---|
| `ESPN_LEAGUE_ID` | Your ESPN fantasy league ID (from the URL) |
| `ESPN_SEASON` | `2026` (update each year) |
| `ESPN_S2` | Your `espn_s2` cookie value |
| `ESPN_SWID` | Your `SWID` cookie value |
| `ANTHROPIC_API_KEY` | From [console.anthropic.com](https://console.anthropic.com) |
| `APP_PASSWORD` | A password of your choosing — required to access the app |

### 5. Deploy

```bash
npx vercel --prod
```

Or connect your GitHub repo to Vercel for automatic deploys.

---

## Local development

```bash
# Install deps
npm install

# Run Next.js dev server (frontend only — Python routes need Vercel CLI)
npm run dev

# To test Python routes locally:
npx vercel dev
```

> **Note:** `vercel dev` runs the full stack locally including Python serverless functions. You'll need the Vercel CLI: `npm i -g vercel`.

---

## How it works

1. **Connect** — Enter your team ID + weekly starts limit. Credentials live in Vercel env vars.
2. **My Roster** — `/api/espn.py` authenticates with ESPN using your cookies, pulls your roster SP list with projected starts for the week.
3. **Free Agents** — Same API call fetches top 30 available SPs in your league by ownership %.
4. **Recommendations** — `/api/analyze.py` sends your roster + selected FAs to Claude. Returns structured add/drop/hold recommendations + a Mon–Sun action plan targeting your exact starts limit.

---

## Finding your Team ID

Your team ID is usually 1–12 (matching your team's slot in the league). You can find it by:
- Hovering over your team name on ESPN and checking the URL: `teamId=X`
- Or just try 1 and adjust if the wrong team loads

---

## Updating season year

Each March, update `ESPN_SEASON` in your Vercel env vars to the new year. No code changes needed.
