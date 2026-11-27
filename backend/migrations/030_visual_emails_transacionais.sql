-- Atualiza o modelo original e preserva modelos que já têm HTML próprio.
with templates as (
  select id, code,
         replace(replace(replace(subject, '&', '&amp;'), '<', '&lt;'), '>', '&gt;') as heading,
         replace(replace(replace(body_text, '&', '&amp;'), '<', '&lt;'), '>', '&gt;') as copy
    from public.notification_templates
   where channel = 'email'
     and body_html like '<div style="font-family:Arial,sans-serif;background:#0b0718;%'
), content as (
  select id, heading,
         case
           when code in ('verify_email', 'email_change') then $code$
             <p style="margin:0 0 16px">Olá, {nome_usuario}! Digite o código abaixo para confirmar seu e-mail.</p>
             <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
               <tr><td align="center" bgcolor="#efe4ff" style="padding:15px 4px;border:1px solid #d9bdfa;border-radius:10px;color:#45147e;font-family:Consolas,monospace;font-size:26px;font-weight:bold;letter-spacing:0.14em;white-space:nowrap">{codigo}</td></tr>
             </table>
             <p style="margin:14px 0 0">O código expira em <strong>{validade}</strong>. Se você não pediu a confirmação, pode ignorar este e-mail.</p>
           $code$
           when code = 'security_alert' then $security$
             <p style="margin:0 0 14px">Olá, {nome_usuario}! Registramos uma atividade de segurança na sua conta.</p>
             <p style="margin:0 0 18px;padding:12px 14px;border-left:3px solid #ad76e7;background-color:#f5effc"><strong>Data e hora</strong><br>{quando}</p>
             <p style="margin:0 0 18px">Se você não reconhecer essa atividade, troque sua senha e encerre as sessões no seu perfil.</p>
             <a href="{site}/perfil" style="display:inline-block;padding:12px 16px;border:1px solid #6525ad;border-radius:8px;background-color:#6525ad;color:#ffffff;font-weight:bold;text-decoration:none">Revisar minha conta</a>
           $security$
           else '<p style="margin:0">' ||
                replace(replace(copy, '{link}', '<a href="{link}" style="color:#6525ad;font-weight:bold;text-decoration:underline">Abrir no Time de Fora</a>'), chr(10), '<br>') ||
                '</p>'
         end as body
    from templates
)
update public.notification_templates as template
   set body_html = $header$<!doctype html>
<html lang="pt-BR">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background-color:#f1edf9;color:#23163c;font-family:Arial,Helvetica,sans-serif">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color:#f1edf9">
    <tr><td align="center" style="padding:24px 12px">
      <!--[if mso]><table role="presentation" width="560" cellspacing="0" cellpadding="0"><tr><td><![endif]-->
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background-color:#fff;border:1px solid #dfd5f1;border-radius:20px;border-collapse:separate">
        <tr><td bgcolor="#22123d" style="padding:26px;border-radius:19px 19px 0 0;background-color:#22123d;background-image:linear-gradient(120deg,#22123d 15%,#50248b 100%);color:#ffffff">
          <p style="margin:0 0 14px;color:#e7c7ff;font-size:14px;font-weight:bold;letter-spacing:1px">TIME DE FORA</p>
          <h1 style="margin:0;font-size:26px;line-height:1.2">$header$ || content.heading || $body$</h1>
        </td></tr>
        <tr><td style="padding:24px 26px;color:#23163c;font-size:16px;line-height:1.6;overflow-wrap:anywhere">$body$ || content.body || $footer$</td></tr>
        <tr><td style="padding:16px 26px;border-top:1px solid #efe7f9;color:#58436e;font-size:13px;line-height:1.5">Mensagem automática da equipe Time de Fora.</td></tr>
      </table>
      <!--[if mso]></td></tr></table><![endif]-->
    </td></tr>
  </table>
</body>
</html>$footer$
  from content
 where template.id = content.id;
