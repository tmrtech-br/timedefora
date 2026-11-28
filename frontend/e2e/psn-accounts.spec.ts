import { expect, test } from '@playwright/test';

test('proprietário cadastra e conecta a conta PSN pelo console sem agente', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const consoleRow = {
    id: 'console', code: 'PS5-01', name: 'PS5 de teste', platform_code: 'PS5',
    agent_id: null, owner_requested_psn_account_id: null as string | null,
  };
  const account = { id: 'psn', label: 'Conta de teste', status: 'pending', agent_id: null };
  const loginUrl = 'https://example.test/login';
  const redirectUrl = 'https://example.test/redirect?code=ficticio';
  let submittedRedirect: unknown;

  await page.route('**/api/**', (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === '/api/me/session') return route.fulfill({ json: {
      authenticated: true, user: { id: 'owner', username: 'dono', roles: ['owner'], email_verified: true },
    } });
    if (path === '/api/owner/terms') return route.fulfill({ json: { accepted_at: '2026-11-01T12:00:00Z' } });
    if (path === '/api/owner/consoles') return route.fulfill({ json: [consoleRow] });
    if (path === '/api/owner/psn-accounts') {
      if (request.method() === 'POST') {
        consoleRow.owner_requested_psn_account_id = account.id;
        return route.fulfill({ json: account, status: 201 });
      }
      return route.fulfill({ json: consoleRow.owner_requested_psn_account_id ? [account] : [] });
    }
    if (path === '/api/owner/psn-accounts/psn/login/start') return route.fulfill({ json: { login_url: loginUrl } });
    if (path === '/api/owner/psn-accounts/psn/login/finish') {
      submittedRedirect = request.postDataJSON();
      account.status = 'linked';
      return route.fulfill({ json: account });
    }
    return route.fulfill({ json: [] });
  });

  await page.goto('/proprietario#psn');
  const consoleCard = page.locator('.card').filter({ has: page.getByRole('heading', { name: 'Conta PSN do console' }) });
  await expect(consoleCard.getByText('Cadastre uma conta', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: 'Novo cadastro' }).click();
  await page.getByLabel('Nome para identificar a conta').fill(account.label);
  await page.getByLabel('Console PlayStation').selectOption(consoleRow.id);
  await page.getByRole('button', { name: 'Cadastrar conta PSN' }).click();

  await consoleCard.getByRole('button', { name: 'Fazer login Sony' }).click();
  const dialog = page.getByRole('dialog', { name: 'Login na conta Sony' });
  await expect(dialog.getByRole('link', { name: 'Abra o login da Sony' })).toHaveAttribute('href', loginUrl);
  await dialog.getByLabel('Endereço da página após o login').fill(redirectUrl);
  await dialog.getByRole('button', { name: 'Concluir' }).click();
  await expect(consoleCard.getByText('Conectada', { exact: true })).toBeVisible();
  expect(submittedRedirect).toEqual({ redirect_url: redirectUrl });
});

test('admin gerencia contas PSN com respostas simuladas do backend', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const user = { id: 'user', full_name: 'Pessoa Auditora', username: 'audit', roles: ['admin'],
    mfa_enabled: true, mfa_verified: true };
  const agent = { id: 'agent', name: 'Windows', is_simulated: false };
  const account = { id: 'psn', label: 'Conta de teste', agent_name: agent.name, agent_id: agent.id, status: 'pending' };
  let exists = false;
  let chiakiImportEnabled = false;
  const payloads: unknown[] = [];
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.route('**/api/**', async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    const method = req.method();
    const reply = (json: unknown, status = 200) => route.fulfill({ json, status });
    if (path === '/api/me/session') return reply({ authenticated: true, user });
    if (path === '/api/admin/agents') return reply([agent]);
    if (path === '/api/admin/psn-accounts/options') return reply({ chiaki_import_enabled: chiakiImportEnabled });
    if (path === '/api/admin/psn-accounts') {
      if (method === 'GET') return reply(exists ? [account] : []);
      payloads.push(req.postDataJSON());
      exists = true;
      return reply(account, 201);
    }
    if (path.endsWith('/login/start')) return reply({ login_url: 'https://example.test/login' });
    if (path.endsWith('/login/finish')) {
      payloads.push(req.postDataJSON());
      account.status = 'linked';
      return reply(account);
    }
    if (path.endsWith('/devices')) return reply({ ok: true, devices: [] });
    if (path.endsWith('/devices/ps4-lan')) return reply({
      ok: true, devices: [{ host_name: 'PS4 teste', address: '192.0.2.4', state: 'ligado' }],
    });
    if (path.endsWith('/test')) return reply({ ok: false, message: 'Token expirado para teste.' });
    if (method === 'DELETE') {
      exists = false;
      return reply({ ok: true });
    }
    return reply({});
  });

  await page.goto('/admin/contas-psn');
  await expect(page.getByRole('heading', { name: 'Contas PSN', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Novo cadastro' }).click();
  await page.getByLabel('Rótulo interno').fill(account.label);
  await page.getByLabel('Agente Windows').selectOption(agent.id);
  await page.getByRole('button', { name: 'Cadastrar conta' }).click();
  await expect(page.getByText(account.label, { exact: true })).toBeVisible();
  const actions = page.getByRole('dialog', { name: `Ações da conta ${account.label}` });
  const openActions = async (platform: 'PS4' | 'PS5') => {
    await page.getByRole('button', { name: 'Ações', exact: true }).click();
    await actions.getByLabel('Console').selectOption(platform);
  };
  const importButton = actions.getByRole('button', { name: 'Importar Chiaki' });
  await openActions('PS5');
  await expect(importButton).toHaveCount(0);
  await actions.getByRole('button', { name: 'Vincular', exact: true }).click();
  const redirect = 'https://example.test/redirect?code=ficticio';
  await actions.getByLabel('URL completa de retorno da Sony').fill(redirect);
  await actions.getByRole('button', { name: 'Concluir vínculo' }).click();
  await actions.getByRole('button', { name: 'Consultar PS5' }).click();
  await expect(page.getByText('Nenhum PS5 retornado pela Sony.')).toBeVisible();
  await actions.getByLabel('Console').selectOption('PS4');
  await actions.getByRole('button', { name: 'Buscar PS4 na rede local' }).click();
  await expect(actions.getByRole('heading', { name: 'Buscar PS4 na rede local' })).toBeVisible();
  await expect(page.getByText('192.0.2.4')).toBeVisible();
  await actions.getByRole('button', { name: 'Testar autenticação' }).click();
  await expect(actions.getByText('Token expirado para teste.')).toBeVisible();
  chiakiImportEnabled = true;
  await page.reload();
  await openActions('PS4');
  await expect(importButton).toBeVisible();
  await actions.getByRole('button', { name: 'Fechar' }).click();
  await page.getByRole('button', { name: 'Excluir', exact: true }).click();
  await page.getByRole('dialog').getByRole('textbox').fill('Conta criada para teste');
  await page.getByRole('dialog').getByRole('button', { name: 'Excluir', exact: true }).click();
  await expect(page.getByText('Conta excluída do agente e do banco.')).toBeVisible();
  await expect(page.getByText(account.label, { exact: true })).toHaveCount(0);
  expect(payloads).toEqual([{ label: account.label, agent_id: agent.id }, { redirect_url: redirect }]);
  expect(errors).toEqual([]);
});
