# Supabase control-plane setup

The engine and the site (quantumcapitaldata.tech) never talk directly. They
communicate through Supabase: the site writes **commands**, the engine polls
them and writes back **telemetry**. This guide wires that up.

## 1. Create the project

1. Go to https://supabase.com/dashboard -> **New project**.
2. Name it (e.g. `mt4-command-center`), pick a strong DB password, choose the
   region closest to where the **engine** runs (lower latency for polling).
3. Wait for it to finish provisioning (~2 min).

## 2. Run the schema

1. In the project, open **SQL Editor** -> **New query**.
2. Paste the entire contents of [`schema.sql`](../schema.sql) and click **Run**.
3. Confirm under **Table Editor** that `commands`, `bot_state`, and `trades`
   exist and that RLS is **enabled** (a shield icon on each table).

## 3. Collect the three values

**Project Settings -> API**:

| Value | Where it lives | Who uses it |
|---|---|---|
| **Project URL** (`https://xxxx.supabase.co`) | engine `.env` **and** site | both |
| **`service_role` key** (secret) | engine `.env` **only** | engine (bypasses RLS, server-side) |
| **`anon` / publishable key** | site env only | browser (RLS-gated) |

> The `service_role` key is a god-key. It goes ONLY in the engine's `.env`
> (already gitignored). Never commit it, never put it in the Next.js client
> bundle, never expose it to the browser.

## 4. Engine `.env`

Add these to the engine's `.env` (alongside the MetaApi/broker vars):

```dotenv
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGciOi...      # the service_role key
BOT_ID=default                          # unique per bot instance
```

## 5. Verify (no broker needed)

```bash
uv run mt4-executor hub-check
```

Expected: `OK: Supabase control plane reachable. 0 pending command(s).`
This publishes a row to `bot_state` and reads the (empty) command queue,
proving URL + service key + tables all work. If it fails, re-check the URL and
that you used the **service_role** key (not anon) in the engine `.env`.

## 6. Site env (Vercel, for quantumcapitaldata.tech)

The Next.js app uses the **anon** key only:

```dotenv
NEXT_PUBLIC_SUPABASE_URL=https://xxxx.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGciOi...   # the anon/publishable key
```

Add these in **Vercel -> Project -> Settings -> Environment Variables**. The
site reads `bot_state`/`trades` (RLS: authenticated) and inserts into
`commands` (RLS: authenticated) via the signed-in Supabase client. Enable an
auth provider under **Supabase -> Authentication** so only you can sign in.

## Security recap

- `service_role` key: engine only, server-side, never in git or the browser.
- `anon` key: safe for the browser because RLS restricts every table to
  authenticated users. For single-user, tighten the RLS policies in
  `schema.sql` from `to authenticated` to your specific `auth.uid()`.
