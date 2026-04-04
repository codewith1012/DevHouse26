alter table public.req_code_mapping
add column if not exists drift_level text default 'low',
add column if not exists last_signal_type text;

alter table public.development_signals
add column if not exists external_event_id text;

create unique index if not exists development_signals_external_event_id_idx
on public.development_signals(external_event_id)
where external_event_id is not null;

create table if not exists public.estimate_feedback (
  id bigint generated always as identity primary key,
  issue_id text not null references public.req_code_mapping(issue_id),
  heuristic_score double precision not null,
  llm_score double precision not null,
  predicted_score double precision not null,
  actual_effort_proxy double precision not null,
  absolute_error double precision not null,
  relative_error double precision not null,
  signal_count integer not null default 0,
  issue_duration_hours double precision not null default 0,
  created_at timestamptz not null default timezone('utc', now())
);

create index if not exists estimate_feedback_issue_id_idx
on public.estimate_feedback(issue_id);

create index if not exists estimate_feedback_created_at_idx
on public.estimate_feedback(created_at desc);
