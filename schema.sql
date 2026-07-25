-- mt4-executor <-> quantumcapitaldata.tech control-plane schema (Supabase / Postgres)
--
-- Security model:
--   * The ENGINE connects with the service-role key (bypasses RLS) - server-side only.
--   * The SITE (browser) connects with the anon key + a signed-in user session.
--   * RLS ensures only authenticated users can issue commands or read telemetry.
--     Tighten `auth.role() = 'authenticated'` to a specific owner uid for single-user.

-- ---------------------------------------------------------------------------
-- commands: site -> engine instruction queue
-- ---------------------------------------------------------------------------
create table if not exists public.commands (
    id           bigint generated always as identity primary key,
    bot_id       text        not null default 'default',
    type         text        not null check (type in ('start','stop','flatten','buy','sell')),
    payload      jsonb       not null default '{}'::jsonb,
    status       text        not null default 'pending' check (status in ('pending','done','failed')),
    detail       text,
    created_at   timestamptz not null default now(),
    processed_at timestamptz
);
create index if not exists commands_pending_idx
    on public.commands (bot_id, status, created_at);

-- ---------------------------------------------------------------------------
-- bot_state: engine -> site live status (one row per bot, upserted each tick)
-- ---------------------------------------------------------------------------
create table if not exists public.bot_state (
    bot_id         text primary key,
    running        boolean,
    balance        numeric,
    equity         numeric,
    currency       text,
    open_positions integer,
    positions      jsonb,
    last_error     text,
    server         text,
    mode           text,          -- demo | live, derived from the server name
    updated_at     timestamptz not null default now()
);
-- If upgrading an existing deployment, run:
--   alter table public.bot_state add column if not exists server text;
--   alter table public.bot_state add column if not exists mode text;

-- ---------------------------------------------------------------------------
-- trades: engine -> site executed-trade log (append-only)
-- ---------------------------------------------------------------------------
create table if not exists public.trades (
    id          bigint generated always as identity primary key,
    bot_id      text not null default 'default',
    source      text,                     -- strategy | manual | flatten
    string_code text,
    position_id text,
    raw         jsonb,
    created_at  timestamptz not null default now()
);
create index if not exists trades_bot_idx on public.trades (bot_id, created_at desc);

-- ---------------------------------------------------------------------------
-- Row-Level Security
-- ---------------------------------------------------------------------------
alter table public.commands  enable row level security;
alter table public.bot_state enable row level security;
alter table public.trades    enable row level security;

-- Authenticated users may issue and read commands.
create policy commands_rw on public.commands
    for all to authenticated using (true) with check (true);

-- Authenticated users may read telemetry (read-only from the browser).
create policy bot_state_read on public.bot_state
    for select to authenticated using (true);
create policy trades_read on public.trades
    for select to authenticated using (true);

-- NOTE: the engine uses the service-role key, which bypasses RLS, so it can
-- write bot_state/trades and update command status without extra policies.
