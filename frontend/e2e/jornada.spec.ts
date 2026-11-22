import { expect, test } from '@playwright/test';
import { lastCode, resetAdminMfa, SHOTS, totp, uid } from './helpers';

// Credenciais do superadmin do ambiente de TESTE (as mesmas usadas no seed --admin). Nunca use em produção.
const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL || '';
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || '';

test('jornada completa: cadastro → código → reserva → pagamento → sala de espera → jogar → encerrar', async ({ page }) => {
  test.setTimeout(180_000);
  const id = uid();
  const email = `e2e_${id}@teste.com`;
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/cadastrar');
  await page.screenshot({ path: `${SHOTS}/05-cadastro.png`, fullPage: true });
  await page.getByLabel('Nome completo').fill('Jogador de Teste');
  await page.getByLabel('Nome de usuário público').fill(`e2e_${id}`);
  await page.getByLabel('E-mail', { exact: true }).fill(email);
  await page.getByLabel('Senha', { exact: true }).fill('Teste2026seguro');
  await page.getByLabel('Confirmar senha').fill('Teste2026seguro');
  await page.getByLabel(/termos de uso/).check();
  await page.getByLabel(/política de privacidade/).check();
  await page.getByRole('button', { name: 'Cadastrar', exact: true }).click();
  await expect(page).toHaveURL(/verificar-email/);
  await page.getByLabel('Código de verificação').fill('000000');
  await page.getByRole('button', { name: 'Confirmar' }).click();
  await expect(page.locator('.alert.error')).toContainText(/incorreto|Tentativas/);
  await page.getByLabel('Código de verificação').fill(lastCode(email));
  await page.getByRole('button', { name: 'Confirmar' }).click();
  await expect(page.getByText('E-mail confirmado')).toBeVisible();

  // Escolhe um jogo com fila vazia: o pacote começa no próximo minuto cheio
  const games = await (await page.request.get('/api/catalog/games')).json();
  const free = games.find((g: { queue_size: number; status: string }) => g.queue_size === 0 && g.status === 'available');
  expect(free, 'precisa de um jogo com fila vazia no seed').toBeTruthy();
  await page.goto(`/jogos/${free.slug}`);
  await expect(page.getByText('Disponibilidade e fila')).toBeVisible();
  await page.getByRole('radio', { name: /10 min/ }).click();
  await expect(page.getByText(/Início estimado:/)).toBeVisible();
  await page.getByLabel(/Li e aceito a política/).check();
  await page.screenshot({ path: `${SHOTS}/06-detalhe-jogo.png`, fullPage: true });
  await page.getByRole('button', { name: 'Reservar e ir para o pagamento' }).click();
  await expect(page).toHaveURL(/\/checkout\//);
  await expect(page.getByText(/Reserva provisória: conclua/)).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/07-checkout.png`, fullPage: true });
  await page.getByRole('button', { name: 'Pagar com Pix' }).click();
  await expect(page).toHaveURL(/checkout\/simulado/);
  await expect(page.getByRole('heading', { name: 'Pagamento SIMULADO' })).toBeVisible();
  await page.getByRole('button', { name: 'Simular pagamento aprovado' }).click();
  await expect(page.getByText('Pagamento confirmado!')).toBeVisible({ timeout: 15000 });

  await page.goto('/minhas-filas');
  await expect(page.getByText('Sua posição: 1º')).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/08-minhas-filas.png`, fullPage: true });
  await page.getByRole('link', { name: 'Sala de espera' }).first().click();
  await expect(page.getByRole('heading', { name: 'Sala de espera' })).toBeVisible();
  await page.getByRole('radio', { name: 'Teclado e mouse' }).click();
  await page.screenshot({ path: `${SHOTS}/09-sala-de-espera.png`, fullPage: true });
  // O início é arredondado para o minuto cheio: aguarda a liberação feita com o relógio do servidor
  await expect(page.getByRole('button', { name: 'Começar a jogar' })).toBeEnabled({ timeout: 75_000 });
  await page.getByRole('button', { name: 'Começar a jogar' }).click();
  await expect(page).toHaveURL(/\/jogar\//);
  await expect(page.getByText('Sessão SIMULADA')).toBeVisible();
  await page.locator('.player').click();
  await page.keyboard.press('Space');
  await expect(page.getByText(/comandos enviados: [1-9]/)).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/10-jogando.png`, fullPage: true });
  page.once('dialog', (d) => d.accept());
  await page.getByRole('button', { name: 'Encerrar sessão' }).click();
  await expect(page.getByText('Sessão encerrada.')).toBeVisible();
  await page.keyboard.press('Space');   // após o fim, o servidor recusa
  await page.goto('/sessoes');
  await expect(page.getByText('encerrada por você')).toBeVisible();
  await page.goto('/pagamentos');
  await expect(page.locator('table')).toContainText('simulado');
});

test('painel administrativo exige MFA e permite configurar console', async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  test.skip(!ADMIN_EMAIL || !ADMIN_PASSWORD, 'Defina E2E_ADMIN_EMAIL e E2E_ADMIN_PASSWORD');
  resetAdminMfa(ADMIN_EMAIL);
  await page.goto('/admin');
  await expect(page).toHaveURL(/\/entrar/);           // painel exige login
  await page.getByLabel('E-mail').fill(ADMIN_EMAIL);
  await page.getByLabel('Senha').fill(ADMIN_PASSWORD);
  await page.getByRole('button', { name: 'Entrar' }).click();
  await page.waitForURL((u) => !u.pathname.startsWith('/entrar'));
  await page.goto('/admin');
  await expect(page.getByText('Ative a autenticação em dois fatores')).toBeVisible();   // MFA obrigatório
  await page.goto('/configuracoes');
  await page.getByRole('button', { name: 'Ativar' }).click();
  const secret = (await page.locator('code').first().textContent())!.trim();
  await page.getByLabel('Código de 6 dígitos').fill(totp(secret));
  await page.getByRole('button', { name: 'Confirmar' }).click();
  await expect(page.getByText('Códigos de recuperação')).toBeVisible();
  await page.goto('/admin');
  await expect(page.getByRole('heading', { name: 'Visão geral' })).toBeVisible();
  await expect(page.locator('.kpi').first()).not.toContainText('…');
  await page.screenshot({ path: `${SHOTS}/11-admin-visao-geral.png`, fullPage: true });
  await page.goto('/admin/consoles');
  await page.getByPlaceholder('Código (PS5-05)').fill(`PS5-E${uid().toUpperCase()}`);
  await page.getByPlaceholder('Nome (PS5 nº 05)').fill('PS5 de teste E2E');
  await page.getByRole('button', { name: 'Cadastrar' }).click();
  await expect(page.getByText('Console criado')).toBeVisible();
  await page.getByLabel('Método (obrigatório)').selectOption('hdmi_capture');
  await expect(page.getByText('canal de controle separado').first()).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/12-admin-config-console.png`, fullPage: true });
  await page.getByRole('button', { name: 'Salvar configuração' }).click();
  await expect(page.locator('.alert.error')).toContainText(/agent_id|Agente|Selecione/);
  await page.getByRole('button', { name: 'Publicar', exact: true }).click();
  await expect(page.locator('.alert.error')).toContainText('Publicação bloqueada');
  await page.goto('/admin/agenda');
  await expect(page.getByText('Calendário do dia')).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/13-admin-calendario.png`, fullPage: true });
  await page.goto('/admin/filas');
  await expect(page.getByRole('heading', { name: 'Filas' })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/14-admin-filas.png`, fullPage: true });
  await page.goto('/admin/auditoria');
  await expect(page.locator('table')).toContainText('INSERT');
});
