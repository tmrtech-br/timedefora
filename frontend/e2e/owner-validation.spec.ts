import { expect, test } from '@playwright/test';

test('proprietário acompanha as etapas do console, o diagnóstico e os períodos no calendário', async ({ page }) => {
  const prefix = '/api/owner/consoles/console';
  const now = new Date();
  const day = new Date(now.getTime() - 10800000).toISOString().slice(0, 10);
  const window = { id: 'periodo', title: 'Jogo de teste', starts_at: `${day}T08:00:00-03:00`, ends_at: `${day}T22:00:00-03:00`, status: 'pending_review' };
  let reviewStatus = 'approved';
  let diagnosticStatus: string | null = null;
  let published = false;
  let validated = false;

  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    const reply = (json: unknown) => route.fulfill({ json });
    if (path === '/api/me/session') return reply({ authenticated: true, user: { id: 'owner', username: 'dono', roles: ['owner'], email_verified: true } });
    if (path === '/api/owner/terms') return reply({ accepted_at: now.toISOString() });
    if (path === '/api/owner/consoles') return reply([{ id: 'console', code: 'PS4-01', name: 'PS4 de teste', platform_code: 'PS4', review_status: reviewStatus }]);
    if (path === `${prefix}/review`) return reply({
      status: reviewStatus, approved_at: now.toISOString(), is_published: published, pending: {}, missing: [],
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
    if (path === `${prefix}/hours`) return reply({ hours: [], pending: null });
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
});
