-- Atualiza o rascunho ativo preservando a versão associada aos aceites anteriores.
with previous_terms as (
  update public.policy_documents
     set is_current = false
   where kind = 'terms' and version = '0.1-rascunho' and is_current
     and strpos(body, 'A LocaPlay oferece') > 0
  returning kind, title, body, requires_legal_review
)
insert into public.policy_documents (kind, version, title, body, requires_legal_review, is_current, published_at)
select kind, '0.2-rascunho', title, replace(body, 'A LocaPlay oferece', 'A timedefora oferece'),
       requires_legal_review, true, now()
  from previous_terms;

update public.notification_templates
   set subject = replace(subject, 'LocaPlay', 'timedefora'),
       body_text = replace(body_text, 'LocaPlay', 'timedefora'),
       body_html = replace(body_html, 'LocaPlay', 'timedefora')
 where strpos(subject, 'LocaPlay') > 0
    or strpos(body_text, 'LocaPlay') > 0
    or strpos(body_html, 'LocaPlay') > 0;
