-- Companion selfie pool (HeyGen-generated looks). Run once in Supabase SQL editor.

create table if not exists companion_selfies (
  id              uuid primary key default gen_random_uuid(),
  companion_id    text        not null,
  scene           text        not null,
  tags            text[]      not null default '{}',
  heygen_look_id  text        unique,
  storage_path    text,
  status          text        not null default 'pending',   -- pending | ready | failed
  created_at      timestamptz not null default now()
);

create index if not exists companion_selfies_lookup
  on companion_selfies (companion_id, status);

alter table companion_selfies enable row level security;
-- No policies = no anon/authenticated access. The service key bypasses RLS.

insert into storage.buckets (id, name, public)
values ('companion-selfies', 'companion-selfies', true)
on conflict (id) do nothing;

drop policy if exists "companion selfies are publicly readable" on storage.objects;
create policy "companion selfies are publicly readable"
  on storage.objects for select
  using (bucket_id = 'companion-selfies');
