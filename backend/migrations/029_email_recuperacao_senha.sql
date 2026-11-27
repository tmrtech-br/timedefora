insert into public.notification_templates (code, channel, subject, body_text, body_html)
values (
  'password_reset',
  'email',
  'Redefina sua senha | Time de Fora',
  $text$Olá, {nome_usuario}!

Recebemos uma solicitação para redefinir a senha da sua conta no Time de Fora.
Acesse o link abaixo para criar uma nova senha. Ele é válido por {validade}.

{link}

Se você não solicitou a redefinição, pode ignorar este e-mail. Sua senha continua a mesma.

Equipe Time de Fora$text$,
  $email$<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Redefina sua senha | Time de Fora</title>
</head>
<body style="margin:0;padding:0;background-color:#f1edf9;color:#23163c;font-family:Arial,Helvetica,sans-serif">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color:#f1edf9">
    <tr><td align="center" style="padding:24px 12px">
      <!--[if mso]><table role="presentation" width="560" cellspacing="0" cellpadding="0"><tr><td><![endif]-->
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background-color:#ffffff;border:1px solid #dfd5f1;border-radius:20px;border-collapse:separate">
        <tr><td bgcolor="#22123d" style="padding:30px 26px 34px;border-radius:19px 19px 0 0;background-color:#22123d;background-image:linear-gradient(120deg,#22123d 15%,#50248b 100%);color:#ffffff">
          <p style="margin:0 0 20px;color:#e7c7ff;font-size:15px;font-weight:bold;letter-spacing:1px">TIME DE FORA</p>
          <h1 style="margin:0;font-size:32px;line-height:1.12;letter-spacing:-0.7px">Redefina sua senha</h1>
        </td></tr>
        <tr><td style="padding:28px 26px 26px">
          <p style="margin:0 0 10px;font-size:17px;line-height:1.5;font-weight:bold">Olá, {nome_usuario}!</p>
          <p style="margin:0 0 22px;font-size:16px;line-height:1.6">Recebemos uma solicitação para redefinir a senha da sua conta. Use o botão abaixo para criar uma nova senha.</p>
          <table role="presentation" cellspacing="0" cellpadding="0">
            <tr><td bgcolor="#6525ad" style="border-radius:10px;background-color:#6525ad">
              <a href="{link}" style="display:inline-block;padding:14px 22px;border:1px solid #6525ad;border-radius:10px;color:#ffffff;font-size:16px;line-height:1.25;font-weight:bold;text-decoration:none;mso-padding-alt:0;text-underline-color:#6525ad"><!--[if mso]><i style="mso-font-width:150%;mso-text-raise:24pt" hidden>&emsp;</i><![endif]--><span style="mso-text-raise:12pt">Criar nova senha</span><!--[if mso]><i style="mso-font-width:150%" hidden>&emsp;&#8203;</i><![endif]--></a>
            </td></tr>
          </table>
          <p style="margin:12px 0 24px;color:#58436e;font-size:14px;line-height:1.5">O link é válido por <strong>{validade}</strong>.</p>
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
            <tr><td style="padding:14px 16px;border-left:3px solid #ad76e7;border-radius:8px;background-color:#f5effc;color:#392650;font-size:14px;line-height:1.55">
              <strong>Não solicitou a redefinição?</strong><br>
              Pode ignorar este e-mail. Sua senha continua a mesma.
            </td></tr>
          </table>
          <p style="margin:22px 0 0;color:#58436e;font-size:13px;line-height:1.55">Se o botão não abrir, copie este endereço e cole no navegador.<br>
            <a href="{link}" style="color:#6525ad;text-decoration:underline;word-wrap:break-word;word-break:break-all">{link}</a>
          </p>
        </td></tr>
        <tr><td style="padding:16px 26px;border-top:1px solid #efe7f9;color:#58436e;font-size:13px;line-height:1.5">Mensagem automática da equipe Time de Fora.</td></tr>
      </table>
      <!--[if mso]></td></tr></table><![endif]-->
    </td></tr>
  </table>
</body>
</html>$email$
)
on conflict (code, channel) do update
set subject = excluded.subject, body_text = excluded.body_text, body_html = excluded.body_html;
