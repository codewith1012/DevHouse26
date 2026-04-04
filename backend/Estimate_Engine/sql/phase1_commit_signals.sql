create table if not exists public.development_signals (
  id bigint generated always as identity primary key,
  issue_id text not null references public.req_code_mapping(issue_id),
  signal_type text not null,
  source text not null default 'git',
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default timezone('utc', now())
);

create index if not exists development_signals_issue_id_idx
on public.development_signals(issue_id);

create index if not exists development_signals_signal_type_idx
on public.development_signals(signal_type);

alter table public.estimate_history
add column if not exists delta_score double precision,
add column if not exists drift_level text default 'low',
add column if not exists signal_type text default 'estimate_refresh',
add column if not exists signal_id bigint;

update public.estimate_history
set delta_score = updated_score - previous_score
where delta_score is null;

create index if not exists estimate_history_signal_type_idx
on public.estimate_history(signal_type);
