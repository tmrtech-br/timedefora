import { expect, test } from '@playwright/test';
import { SHOTS } from './helpers';

test.describe('Página inicial e navegação', () => {
  test('home desktop apresenta marca, destaque e catálogo sem overflow', async ({ page }) => {
    await page.setViewportSize({ width: 1536, height: 864 });
    await page.goto('/');
    const hero = page.locator('.hero');
    await expect(hero.getByRole('heading', { level: 1 })).toHaveText('timedefora');
    await expect(hero.locator('.hero-feature')).toContainText('GTA VI');
    await expect(page.locator('.hero-panel .price-line')).toHaveCount(2);
    await expect(page.locator('.hero-panel')).toContainText('10 min — R$ 30');
    await expect(page.locator('.hero-panel')).toContainText('30 min — R$ 50');
    await expect(page.locator('.hero-panel')).toContainText('Fila:');
    await expect(page.locator('.games-grid .game-card')).toHaveCount(6);
    for (const t of ['GTA VI', 'Zelda', 'God of War', 'Spider-Man', 'Forza', 'EA FC']) await expect(page.locator('.games-grid')).toContainText(t);
    await expect(page.locator('.live-panel')).toContainText(/Jogando agora|Nenhuma fila ativa/);
    await expect(page.locator('.how-panel')).toContainText('3. Jogue no navegador');
    await expect(page.locator('.footer')).toContainText('A locadora voltou. Agora na sua casa.');
    await expect(page.locator('.side-links > a.active')).toHaveText('Catálogo');
    await expect(page.locator('.top-nav a.active')).toHaveText('Início');
    const sw = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(sw).toBeLessThanOrEqual(1536);
    await page.screenshot({ path: `${SHOTS}/01-home-desktop.png` });
  });

  test('home mobile sem rolagem horizontal', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/');
    await expect(page.locator('.games-grid .game-card')).toHaveCount(6);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    await page.screenshot({ path: `${SHOTS}/02-home-mobile.png`, fullPage: true });
    await page.getByRole('button', { name: 'Abrir menu' }).click();
    await expect(page.locator('.sidebar.open')).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/03-menu-mobile.png` });
    await page.keyboard.press('Escape');
    await expect(page.getByRole('button', { name: 'Abrir menu' })).toBeFocused();
  });

  test('botões e links levam ao destino correto', async ({ page }) => {
    await page.setViewportSize({ width: 1536, height: 864 });
    test.setTimeout(120_000);
    const cases: [string, RegExp][] = [['Jogos', /\/jogos$/], ['Como Funciona', /\/como-funciona$/], ['Suporte', /\/suporte$/]];
    for (const [label, url] of cases) {
      await page.goto('/');
      await expect(page.getByRole('heading', { name: 'timedefora' })).toBeVisible();
      await page.locator('.top-nav').getByRole('link', { name: label }).click();
      await expect(page).toHaveURL(url, { timeout: 20_000 });
    }
    await page.goto('/');
    await page.getByRole('link', { name: 'Entrar' }).click();
    await expect(page).toHaveURL(/\/entrar/);
    await page.goto('/');
    await page.getByRole('link', { name: 'Cadastrar' }).click();
    await expect(page.getByRole('heading', { name: 'Criar conta' })).toBeVisible();
    await page.goto('/');
    await page.getByRole('link', { name: 'Ver detalhes de Zelda' }).click();
    await expect(page).toHaveURL(/\/jogos\/zelda$/);
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Zelda');
    await page.goto('/');
    await page.getByRole('link', { name: 'Assistir ao vivo' }).click();
    await expect(page).toHaveURL(/\/jogos\/gta-vi#ao-vivo/);
    await expect(page.locator('#ao-vivo')).toContainText(/não configurada|Offline|Somente espectadores/);
    await page.route('**/api/catalog/games/gta-vi', async (route) => {
      const response = await route.fetch();
      const game = await response.json();
      game.availability.consoles = [{
        console_id: 'demo', console_name: 'Console de teste', messages: [], queue_size: 0,
        playing_now: null, current_window: null, next_window: null, queue: [],
        packages: [{ minutes: 10, price_cents: 3000, fits: true }],
      }];
      await route.fulfill({ response, json: game });
    });
    await page.route('**/api/catalog/games/gta-vi/quote?*', (route) => route.fulfill({ json: { available: true } }));
    await page.goto('/');
    await page.getByRole('link', { name: 'Jogar agora' }).click();
    await expect(page).toHaveURL(/\/jogos\/gta-vi#reservar/);
    await expect(page.locator('#reservar')).toBeVisible();
    await page.getByRole('radio', { name: /10 min/ }).click();
    await page.getByLabel(/Li e aceito a política/).check();
    await page.getByRole('button', { name: 'Entrar para reservar' }).click();
    await expect(page).toHaveURL(/\/entrar\?proximo=/);
    for (const p of ['/minhas-filas', '/sessoes', '/perfil', '/configuracoes']) {
      await page.goto(p);
      await expect(page).toHaveURL(/\/entrar\?proximo=/);
    }
  });

  test('catálogo filtra e mostra estado vazio', async ({ page }) => {
    await page.goto('/jogos');
    await expect(page.locator('.game-card').filter({ hasText: 'Forza' })).toBeVisible();
    await page.getByPlaceholder('Buscar jogos ou gêneros…').fill('corrida');
    await expect(page.locator('.game-card')).toHaveCount(1);
    await expect(page.locator('.game-card')).toContainText('Forza');
    await page.getByPlaceholder('Buscar jogos ou gêneros…').fill('zzzz');
    await expect(page.getByText('Nenhum jogo encontrado')).toBeVisible();
    await page.getByPlaceholder('Buscar jogos ou gêneros…').fill('');
    await page.locator('select').first().selectOption('nintendo');
    await expect(page.locator('.game-card')).toHaveCount(1);
    await page.screenshot({ path: `${SHOTS}/04-catalogo.png`, fullPage: true });
  });
});
