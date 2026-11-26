import { expect, test } from '@playwright/test';

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
  await page.getByPlaceholder('teste01').fill(account.label);
  await page.getByLabel('Agente Windows').selectOption(agent.id);
  await page.getByRole('button', { name: 'Cadastrar conta' }).click();
  await expect(page.getByText(account.label, { exact: true })).toBeVisible();
  const actions = page.getByRole('combobox', { name: 'Selecionar ação' });
  async function execute(action: string) {
    await actions.selectOption(action);
    await page.getByRole('button', { name: 'Executar' }).click();
  }
  await expect(actions.locator('option[value="chiaki"]')).toHaveCount(0);
  await execute('link');
  const redirect = 'https://example.test/redirect?code=ficticio';
  await page.locator('textarea').fill(redirect);
  await page.getByRole('button', { name: 'Concluir vínculo' }).click();
  await execute('ps5');
  await expect(page.getByText('Nenhum PS5 retornado pela Sony.')).toBeVisible();
  await execute('ps4-lan');
  await expect(page.getByRole('heading', { name: 'PS4 na rede de Windows' })).toBeVisible();
  await expect(page.getByText('192.0.2.4')).toBeVisible();
  await execute('test');
  await expect(page.locator('#conteudo').getByText('Token expirado para teste.')).toBeVisible();
  chiakiImportEnabled = true;
  await page.reload();
  await expect(actions.locator('option[value="chiaki"]')).toHaveCount(1);
  await page.getByRole('button', { name: 'Excluir', exact: true }).click();
  await page.getByRole('dialog').getByRole('textbox').fill('Conta criada para teste');
  await page.getByRole('dialog').getByRole('button', { name: 'Excluir', exact: true }).click();
  await expect(page.locator('#conteudo').getByText('Conta excluída do agente e do banco.')).toBeVisible();
  expect(payloads).toEqual([{ label: account.label, agent_id: agent.id }, { redirect_url: redirect }]);
  expect(errors).toEqual([]);
});
