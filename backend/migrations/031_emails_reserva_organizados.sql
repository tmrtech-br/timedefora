-- E-mails de reserva mais organizados: "Sua vez está chegando", "Pagamento aprovado" e "Problema técnico".
-- Detalhes em tabela, botão de ação claro. "Problema técnico" leva ao suporte. Mesmo cabeçalho/rodapé da 030.
with content(code, heading, body) as (
  values
  ('turn_soon', 'Sua vez de jogar {jogo} está chegando!', $turn$
    <p style="margin:0 0 16px">Olá, {nome_usuario}! Faltam aproximadamente <strong>{minutos} minutos</strong> para a sua sessão.</p>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 18px;border:1px solid #e6dcf5;border-radius:12px;border-collapse:separate">
      <tr><td style="padding:10px 14px;color:#6b5a84;font-size:14px;width:42%">Jogo</td><td style="padding:10px 14px;font-weight:bold">{jogo}</td></tr>
      <tr><td style="padding:10px 14px;color:#6b5a84;font-size:14px;border-top:1px solid #efe7f9">Console</td><td style="padding:10px 14px;border-top:1px solid #efe7f9">{console}</td></tr>
      <tr><td style="padding:10px 14px;color:#6b5a84;font-size:14px;border-top:1px solid #efe7f9">Posição na fila</td><td style="padding:10px 14px;border-top:1px solid #efe7f9">{posicao}</td></tr>
      <tr><td style="padding:10px 14px;color:#6b5a84;font-size:14px;border-top:1px solid #efe7f9">Início previsto</td><td style="padding:10px 14px;border-top:1px solid #efe7f9">{inicio_previsto}</td></tr>
      <tr><td style="padding:10px 14px;color:#6b5a84;font-size:14px;border-top:1px solid #efe7f9">Fim previsto</td><td style="padding:10px 14px;border-top:1px solid #efe7f9">{fim_previsto}</td></tr>
      <tr><td style="padding:10px 14px;color:#6b5a84;font-size:14px;border-top:1px solid #efe7f9">Duração</td><td style="padding:10px 14px;border-top:1px solid #efe7f9">{duracao}</td></tr>
    </table>
    <p style="margin:0 0 18px">Prepare o controle (ou teclado e mouse) e confira sua conexão. Seu tempo só começa a contar quando o console estiver pronto.</p>
    <a href="{link}" style="display:inline-block;padding:12px 18px;border:1px solid #6525ad;border-radius:8px;background-color:#6525ad;color:#ffffff;font-weight:bold;text-decoration:none">Abrir a sala de espera</a>
  $turn$),
  ('payment_approved', 'Pagamento aprovado — {jogo}', $paid$
    <p style="margin:0 0 16px">Olá, {nome_usuario}! Recebemos seu pagamento de <strong>{valor}</strong>. Sua reserva está confirmada.</p>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 18px;border:1px solid #e6dcf5;border-radius:12px;border-collapse:separate">
      <tr><td style="padding:10px 14px;color:#6b5a84;font-size:14px;width:42%">Reserva</td><td style="padding:10px 14px;font-weight:bold;font-family:Consolas,monospace">{codigo}</td></tr>
      <tr><td style="padding:10px 14px;color:#6b5a84;font-size:14px;border-top:1px solid #efe7f9">Jogo</td><td style="padding:10px 14px;border-top:1px solid #efe7f9;font-weight:bold">{jogo}</td></tr>
      <tr><td style="padding:10px 14px;color:#6b5a84;font-size:14px;border-top:1px solid #efe7f9">Console</td><td style="padding:10px 14px;border-top:1px solid #efe7f9">{console}</td></tr>
      <tr><td style="padding:10px 14px;color:#6b5a84;font-size:14px;border-top:1px solid #efe7f9">Duração</td><td style="padding:10px 14px;border-top:1px solid #efe7f9">{duracao}</td></tr>
      <tr><td style="padding:10px 14px;color:#6b5a84;font-size:14px;border-top:1px solid #efe7f9">{modo}</td><td style="padding:10px 14px;border-top:1px solid #efe7f9">{inicio_previsto} até {fim_previsto}</td></tr>
      <tr><td style="padding:10px 14px;color:#6b5a84;font-size:14px;border-top:1px solid #efe7f9">Valor pago</td><td style="padding:10px 14px;border-top:1px solid #efe7f9">{valor}</td></tr>
    </table>
    <p style="margin:0 0 18px">Avisaremos quando sua vez estiver chegando. Na hora, é só entrar na sala de espera e clicar em "Começar a jogar".</p>
    <a href="{link}" style="display:inline-block;padding:12px 18px;border:1px solid #6525ad;border-radius:8px;background-color:#6525ad;color:#ffffff;font-weight:bold;text-decoration:none">Ver minha reserva</a>
  $paid$),
  ('console_not_ready', 'Problema técnico na sua sessão de {jogo}', $fail$
    <p style="margin:0 0 16px">Olá, {nome_usuario}! O console <strong>{console}</strong> não ficou pronto no horário da sua reserva por um problema técnico.</p>
    <p style="margin:0 0 18px;padding:12px 14px;border-left:3px solid #2e9e5b;background-color:#eef8f1"><strong>Seu tempo NÃO foi consumido.</strong><br>Nossa equipe já foi avisada e vai remarcar ou reembolsar a reserva.</p>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 18px;border:1px solid #e6dcf5;border-radius:12px;border-collapse:separate">
      <tr><td style="padding:10px 14px;color:#6b5a84;font-size:14px;width:42%">Reserva</td><td style="padding:10px 14px;font-weight:bold;font-family:Consolas,monospace">{codigo}</td></tr>
      <tr><td style="padding:10px 14px;color:#6b5a84;font-size:14px;border-top:1px solid #efe7f9">Jogo</td><td style="padding:10px 14px;border-top:1px solid #efe7f9">{jogo}</td></tr>
      <tr><td style="padding:10px 14px;color:#6b5a84;font-size:14px;border-top:1px solid #efe7f9">Console</td><td style="padding:10px 14px;border-top:1px solid #efe7f9">{console}</td></tr>
    </table>
    <p style="margin:0 0 18px">Se quiser escolher entre remarcar ou receber o reembolso, ou tiver qualquer dúvida, fale com o suporte.</p>
    <a href="{site}/suporte" style="display:inline-block;padding:12px 18px;border:1px solid #6525ad;border-radius:8px;background-color:#6525ad;color:#ffffff;font-weight:bold;text-decoration:none">Falar com o suporte</a>
  $fail$)
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
 where template.code = content.code and template.channel = 'email';

-- Texto simples e notificação no site do "Problema técnico": apontam para o suporte.
update public.notification_templates
   set body_text = 'O console {console} não ficou pronto no horário da reserva {codigo} por um problema técnico. Seu tempo NÃO foi consumido: nossa equipe já foi avisada e vai remarcar ou reembolsar sua reserva. Fale com o suporte: {site}/suporte'
 where code = 'console_not_ready';
