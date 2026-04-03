alter table public.req_code_mapping
add column if not exists heuristic_score double precision,
add column if not exists llm_score double precision,
add column if not exists final_score double precision;

comment on column public.req_code_mapping.heuristic_score is
'Heuristic engine output for the requirement.';

comment on column public.req_code_mapping.llm_score is
'LLM-generated score or estimate for the requirement.';

comment on column public.req_code_mapping.final_score is
'Final combined score after merging heuristic and LLM outputs.';

select
  column_name,
  data_type
from information_schema.columns
where table_schema = 'public'
  and table_name = 'req_code_mapping'
order by ordinal_position;
