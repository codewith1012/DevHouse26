alter table public.req_code_mapping
add column if not exists confidence double precision,
add column if not exists uncertainty text,
add column if not exists estimate_breakdown jsonb,
add column if not exists last_estimated_at timestamptz;

create table if not exists public.estimate_history (
  id bigint generated always as identity primary key,
  issue_id text not null references public.req_code_mapping(issue_id),
  previous_score double precision not null,
  updated_score double precision not null,
  change_reason text not null,
  changed_at timestamptz not null default timezone('utc', now())
);

create index if not exists estimate_history_issue_id_idx
on public.estimate_history(issue_id);

create index if not exists estimate_history_changed_at_idx
on public.estimate_history(changed_at desc);
