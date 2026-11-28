import { expect, test } from '@playwright/test';

test('o cadastro pronto e o envio ficam verdes em etapas separadas', async ({ page }) => {
  const prefix = '/api/owner/consoles/console';
  let ready = false;
  let status = 'draft';
  let platform = 'PS4';
  await page.route('**/api/**', (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const reply = (json: unknown) => route.fulfill({ json });
    if (path === '/api/me/session') return reply({ authenticated: true, user: { id: 'owner', username: 'dono', roles: ['owner'], email_verified: true } });
    if (path === '/api/owner/terms') return reply({ accepted_at: new Date().toISOString() });
    if (path === '/api/owner/consoles') return reply([{ id: 'console', code: 'CONSOLE', name: 'Console de teste', platform_code: platform, review_status: status }]);
    if (path === prefix && request.method() === 'PATCH') {
      platform = request.postDataJSON().platform_code;
      return reply({ ok: true });
    }
    if (path === `${prefix}/review`) return reply({ status, pending: {}, pending_windows: [], missing: ready ? [] : ['Conclua o login Sony.'] });
    if (path === `${prefix}/submit`) { status = 'submitted'; return reply({ status }); }
    return reply([]);
  });
  await page.goto('/proprietario#cadastro');
  await page.getByRole('button', { name: 'Editar', exact: true }).click();
  const edit = page.getByRole('dialog', { name: 'Editar Console de teste' });
  await edit.getByLabel('Plataforma').selectOption('PS5');
  await edit.getByRole('button', { name: 'Salvar', exact: true }).click();
  await expect(page.getByText('CONSOLE · PS5', { exact: true })).toBeVisible();

  const steps = page.locator('.owner-steps').getByRole('listitem');
  await expect(steps.nth(0)).not.toHaveClass('done');
  ready = true;
  await page.getByRole('button', { name: 'Atualizar status' }).click();
  await expect(steps.nth(0)).toHaveClass('done');
  await expect(steps.nth(1)).not.toHaveClass('done');
  await page.getByRole('button', { name: 'Enviar para análise' }).click();
  await expect(steps.nth(1)).toHaveClass('done');
});

test('proprietário acompanha as etapas do console, o diagnóstico e os períodos no calendário', async ({ page }) => {
  const prefix = '/api/owner/consoles/console';
  const now = new Date();
  const day = new Date(now.getTime() - 10800000).toISOString().slice(0, 10);
  const window = { id: 'periodo', title: 'Jogo de teste', starts_at: `${day}T08:00:00-03:00`, ends_at: `${day}T22:00:00-03:00`, status: 'pending_review' };
  let reviewStatus = 'approved';
  let diagnosticStatus: string | null = null;
  let published = false;
  let validated = false;
  let submittedHours = false;

  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    const reply = (json: unknown) => route.fulfill({ json });
    if (path === '/api/me/session') return reply({ authenticated: true, user: { id: 'owner', username: 'dono', roles: ['owner'], email_verified: true } });
    if (path === '/api/owner/terms') return reply({ accepted_at: now.toISOString() });
    if (path === '/api/owner/consoles') return reply([{ id: 'console', code: 'PS4-01', name: 'PS4 de teste', platform_code: 'PS4', review_status: reviewStatus,
      approved_at: now.toISOString() }]);
    if (path === `${prefix}/review`) return reply({
      status: reviewStatus, approved_at: now.toISOString(), is_published: published, pending: {}, missing: [],
      notes: reviewStatus === 'rejected' ? 'Confira o horário de sábado.' : '',
      pending_windows: reviewStatus === 'changes_pending' ? [window] : [],
    });
    if (path === `${prefix}/diagnostics`) {
      if (route.request().method() === 'POST') diagnosticStatus = 'running';
      return reply({ run: diagnosticStatus ? { id: 'run', status: diagnosticStatus, results: [] } : null,
        validation: { validated_at: validated ? now.toISOString() : null, network_route: 'internet_psn' } });
    }
    if (path === `${prefix}/diagnostics/run/cancel`) { diagnosticStatus = 'cancelled'; return reply({ status: diagnosticStatus }); }
    if (path === `${prefix}/publish`) { published = true; return reply({ is_published: true }); }
    if (path === `${prefix}/games`) return reply({ games: [], drafts: [], assignments: [window] });
    if (path === `${prefix}/hours`) return reply({ hours: [], pending: route.request().method() === 'PUT' ? true : null });
    if (path === `${prefix}/submit`) { submittedHours = true; reviewStatus = 'submitted'; return reply({ status: reviewStatus }); }
    return reply([]);
  });

  await page.goto('/proprietario#cadastro');
  const review = page.locator('#validacao');
  await expect(review.getByText('Em andamento', { exact: true })).toBeVisible();
  await review.getByRole('button', { name: 'Aplicar configuração e testar' }).click();
  const progress = page.getByRole('dialog', { name: 'Diagnóstico do console' });
  await expect(progress.getByRole('progressbar')).toBeVisible();
  await expect(progress.getByText('Em execução', { exact: true })).toBeVisible();
  await progress.getByRole('button', { name: 'Cancelar', exact: true }).click();
  await expect(review.getByText('Diagnóstico cancelado.', { exact: true })).toBeVisible();

  validated = true;
  reviewStatus = 'changes_pending';
  await page.getByRole('link', { name: 'Disponibilidade', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Calendário do dia' })).toBeVisible();
  await expect(page.locator('.owner-calendar .cal2-ev')).toContainText(window.title);
  await page.getByRole('button', { name: 'Próximo dia' }).click();
  await expect(page.getByText('Nenhum período de jogo neste dia.')).toBeVisible();
  await page.getByRole('link', { name: 'Cadastro de console', exact: true }).click();
  await expect(review.getByRole('button', { name: 'Enviar para análise' })).toBeEnabled();
  await expect(review.getByRole('button', { name: 'Publicar para aluguel' })).toBeDisabled();

  reviewStatus = 'approved';
  await page.reload();
  await review.getByRole('button', { name: 'Publicar para aluguel' }).click();
  await expect(review.getByText('Aprovado', { exact: true })).toBeVisible();

  reviewStatus = 'rejected';
  await review.getByRole('button', { name: 'Atualizar status' }).click();
  await review.getByRole('button', { name: 'Ver motivo da recusa' }).click();
  const rejection = page.getByRole('dialog', { name: 'Ajustes solicitados pela equipe' });
  await expect(rejection.getByText('Confira o horário de sábado.')).toBeVisible();
  await rejection.getByRole('button', { name: 'Fechar', exact: true }).click();
  await page.getByRole('link', { name: 'Disponibilidade', exact: true }).click();
  await page.getByRole('button', { name: 'Salvar e enviar para análise' }).click();
  await expect(page.getByText('Novos horários enviados para análise.')).toBeVisible();
  expect(submittedHours).toBe(true);
});

test('a página do jogo resume a disponibilidade e lista durações só na reserva', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const packages = Array.from({ length: 23 }, (_, index) => ({ minutes: 10 + index * 5, price_cents: 100, fits: true }));
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/catalog/games/jogo-teste') return route.fulfill({ json: {
      id: 'game', title: 'Jogo teste', status: 'scheduled', status_label: 'Agendado', platforms: [], genres: [],
      availability: { server_time: new Date().toISOString(), notice: 'Horários estimados.', consoles: [
        { console_id: 'console', console_name: 'PS4 de teste', messages: ['Próxima disponibilidade: amanhã.'], queue_size: 0, packages, queue: [] },
      ] }, packages, rate_cents_per_minute: 0,
    } });
    if (path === '/api/me/session') return route.fulfill({ json: { authenticated: false } });
    return route.fulfill({ json: {} });
  });
  await page.goto('/jogos/jogo-teste');
  const availability = page.getByRole('region', { name: 'Disponibilidade e fila' });
  await expect(availability.getByText('Próxima disponibilidade: amanhã.')).toBeVisible();
  await expect(availability.getByRole('listitem')).toHaveCount(1);
  await page.getByRole('radio', { name: 'Informar minutos', exact: false }).check();
  const durations = page.getByLabel('Quantidade de minutos');
  await expect(durations.getByRole('option')).toHaveCount(24);
  await durations.selectOption('30');
  await expect(durations).toHaveValue('30');
});

test('admin confere e publica o jogo antes de aprovar o console', async ({ page }) => {
  const game = { id: 'game', title: 'Jogo para revisão', slug: 'jogo-para-revisao', status: 'draft',
    commercial_license_status: 'pending', platform_codes: ['PS4'], genres: [] };
  let approved = false;
  await page.route('**/api/**', (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const reply = (json: unknown) => route.fulfill({ json });
    if (path === '/api/me/session') return reply({ authenticated: true, user: { id: 'admin', username: 'admin', roles: ['superadmin'], mfa_enabled: true, mfa_verified: true } });
    if (path === '/api/admin/agents') return reply([{ id: 'agent', name: 'Agente' }]);
    if (path === '/api/admin/owner-reviews') return reply(approved ? [] : [{
      id: 'console', code: 'PS4-01', name: 'Console para revisão', platform_code: 'PS4', status: 'submitted',
      pending: {}, hours: [], agent_id: 'agent', psn_status: 'linked',
      windows: [{ id: 'window', game_id: game.id, title: game.title, game_status: game.status, min_minutes: 10, max_minutes: 60,
        starts_at: '2026-11-28T08:00:00-03:00', ends_at: '2026-11-28T22:00:00-03:00' }],
    }]);
    if (path === '/api/admin/games/game') {
      if (request.method() === 'PATCH') game.status = request.postDataJSON().status;
      return reply(game);
    }
    if (path === '/api/admin/owner-reviews/console/approve') { approved = true; return reply({ ok: true }); }
    return reply([]);
  });
  await page.goto('/admin/aprovacoes');
  const approve = page.getByRole('button', { name: 'Aprovar vínculo', exact: false });
  await expect(approve).toBeDisabled();
  await page.getByRole('button', { name: game.title }).click();
  const details = page.getByRole('dialog', { name: `Cadastro de ${game.title}` });
  await expect(details.getByText('Plataformas', { exact: true })).toBeVisible();
  await details.getByRole('button', { name: 'Publicar jogo' }).click();
  await expect(details.getByText('publicado', { exact: true })).toBeVisible();
  await details.getByRole('button', { name: 'Fechar', exact: true }).click();
  await expect(approve).toBeEnabled();
  await approve.click();
  await expect(page.getByText('Nenhum console aguardando análise.')).toBeVisible();
});
