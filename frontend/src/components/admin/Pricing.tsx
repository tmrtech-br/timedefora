'use client';
import DateTimeField, { isLocalDateTime } from './DateTimeField';
import { useState } from 'react';
import { Field, PageHeader } from '@/components/ui';
import { patch, post } from '@/lib/api';
import { useApi } from '@/lib/hooks';
import { dateTime, money } from '@/lib/format';
import { DataTable, fromLocalInput, need, NewRecord, nowLocalInput, useAction } from './common';

export default function Pricing() {
  const pk = useApi<Record<string, unknown>[]>('/admin/packages');
  const cp = useApi<Record<string, unknown>[]>('/admin/coupons');
  const games = useApi<{ id: string; title: string }[]>('/admin/games').data;
  const [p, setP] = useState({ name: '', minutes: 10, price: '30', game_id: '', platform_code: '', is_promotion: false, local_start_time: '', local_end_time: '', valid_until: '' });
  const [c, setC] = useState({ code: '', discount_type: 'percent', discount_value: 10, max_redemptions: '', per_user_limit: 1, valid_until: '', game_id: '' });
  const { run, msg } = useAction();
  return (
    <div className="stack">
      <PageHeader title="Preços, pacotes e cupons" subtitle="Preços resolvidos no servidor (jogo > console > plataforma > geral, e por faixa horária)." />
      {msg}
      <section className="card stack"><h2>Pacotes</h2><NewRecord title="Novo pacote">{(close) => <><div className="grid3">
        <Field label="Nome"><input value={p.name} onChange={(e) => setP({ ...p, name: e.target.value })} /></Field>
        <Field label="Minutos" hint="5 a 480"><input type="number" min={5} max={480} value={p.minutes} onChange={(e) => setP({ ...p, minutes: Number(e.target.value) })} /></Field>
        <Field label="Preço (R$)"><input maxLength={10} inputMode="decimal" value={p.price} onChange={(e) => setP({ ...p, price: e.target.value.replace(/[^\d.,]/g, '') })} /></Field>
        <Field label="Jogo (opcional)"><select value={p.game_id} onChange={(e) => setP({ ...p, game_id: e.target.value })}><option value="">Todos</option>{games?.map((g) => <option key={g.id} value={g.id}>{g.title}</option>)}</select></Field>
        <Field label="Plataforma (opcional)"><select value={p.platform_code} onChange={(e) => setP({ ...p, platform_code: e.target.value })}><option value="">Todas</option>{['PS5', 'PS4', 'XBOX_SERIES', 'XBOX_ONE', 'SWITCH'].map((x) => <option key={x}>{x}</option>)}</select></Field>
        <Field label="Faixa horária início"><input type="time" value={p.local_start_time} onChange={(e) => setP({ ...p, local_start_time: e.target.value })} /></Field>
        <Field label="Faixa horária fim"><input type="time" value={p.local_end_time} onChange={(e) => setP({ ...p, local_end_time: e.target.value })} /></Field>
        <label className="check"><input type="checkbox" checked={p.is_promotion} onChange={(e) => setP({ ...p, is_promotion: e.target.checked })} />Promoção</label></div>
        <div className="pricing-validity"><DateTimeField label="Válido até (opcional)" min={nowLocalInput()} value={p.valid_until} onChange={(valid_until) => setP({ ...p, valid_until })} /></div>
        <button className="btn primary" onClick={() => run(async () => {
          const price = Number(p.price.replace(',', '.'));
          need(p.name.trim().length >= 2, 'Informe o nome do pacote (mínimo 2 caracteres).');
          need(Number.isInteger(p.minutes) && p.minutes >= 5 && p.minutes <= 480, 'Minutos devem estar entre 5 e 480.');
          need(p.price.trim() !== '' && Number.isFinite(price) && price >= 0, 'Informe um preço válido (não pode ser negativo).');
          need(price <= 10000, 'Preço máximo: R$ 10.000,00.');
          need(!p.valid_until || (isLocalDateTime(p.valid_until) && p.valid_until > nowLocalInput()), '“Válido até” deve ser uma data futura.');
          need(!p.local_start_time === !p.local_end_time, 'Preencha início e fim da faixa horária (ou deixe os dois vazios).');
          await post('/admin/packages', { name: p.name, minutes: p.minutes, price_cents: Math.round(price * 100),
          game_id: p.game_id || null, platform_code: p.platform_code || null, is_promotion: p.is_promotion, local_start_time: p.local_start_time || null, local_end_time: p.local_end_time || null,
          valid_until: fromLocalInput(p.valid_until) }); pk.reload(); close(); }, 'Pacote criado.')}>Criar</button></>}</NewRecord>
        <DataTable limit={5} rows={pk.data} error={pk.error?.message} cols={[['Nome', (r) => String(r.name)], ['Minutos', (r) => String(r.minutes)], ['Preço', (r) => money(Number(r.price_cents))],
          ['Escopo', (r) => [r.game_title, r.console_name, r.platform_code].filter(Boolean).join(' · ') || 'geral'], ['Faixa', (r) => (r.local_start_time ? `${r.local_start_time}–${r.local_end_time}` : '—')],
          ['Ativo', (r) => <button className="btn sm" onClick={() => run(async () => { await patch(`/admin/packages/${r.id}`, { active: !r.active }); pk.reload(); })}>{r.active ? 'ativo (desativar)' : 'inativo (ativar)'}</button>]]} />
      </section>
      <section className="card stack"><h2>Cupons</h2><NewRecord title="Novo cupom">{(close) => <><div className="grid3">
        <Field label="Código"><input maxLength={30} value={c.code} onChange={(e) => setC({ ...c, code: e.target.value.toUpperCase() })} /></Field>
        <Field label="Tipo"><select value={c.discount_type} onChange={(e) => setC({ ...c, discount_type: e.target.value })}><option value="percent">Percentual</option><option value="fixed">Valor fixo (centavos)</option></select></Field>
        <Field label="Valor" hint={c.discount_type === 'percent' ? '1 a 100 (%)' : 'em centavos'}><input type="number" min={1} max={c.discount_type === 'percent' ? 100 : undefined} value={c.discount_value} onChange={(e) => setC({ ...c, discount_value: Number(e.target.value) })} /></Field>
        <Field label="Limite total" hint="Vazio = sem limite"><input type="number" min={1} value={c.max_redemptions} onChange={(e) => setC({ ...c, max_redemptions: e.target.value.replace('-', '') })} /></Field>
        <Field label="Limite por usuário"><input type="number" min={1} value={c.per_user_limit} onChange={(e) => setC({ ...c, per_user_limit: Number(e.target.value) })} /></Field>
        </div>

        <div className="pricing-validity"><DateTimeField label="Válido até (opcional)" min={nowLocalInput()} value={c.valid_until} onChange={(valid_until) => setC({ ...c, valid_until })} /></div>
        <button className="btn primary" onClick={() => run(async () => {
          need(/^[A-Z0-9]{3,30}$/.test(c.code), 'Código do cupom: 3 a 30 letras (A-Z) ou números, sem espaços.');
          need(Number.isInteger(c.discount_value) && c.discount_value > 0, 'Informe um valor de desconto maior que zero.');
          need(c.discount_type !== 'percent' || c.discount_value <= 100, 'Desconto percentual deve ser no máximo 100%.');
          need(c.max_redemptions === '' || (Number.isInteger(Number(c.max_redemptions)) && Number(c.max_redemptions) >= 1), 'Limite total deve ser 1 ou mais (ou vazio para sem limite).');
          need(Number.isInteger(c.per_user_limit) && c.per_user_limit >= 1, 'Limite por usuário deve ser 1 ou mais.');
          need(!c.valid_until || (isLocalDateTime(c.valid_until) && c.valid_until > nowLocalInput()), '“Válido até” deve ser uma data futura.');
          await post('/admin/coupons', { ...c, max_redemptions: c.max_redemptions ? Number(c.max_redemptions) : null, valid_until: fromLocalInput(c.valid_until), game_id: c.game_id || null }); cp.reload(); close(); }, 'Cupom criado.')}>Criar</button></>}</NewRecord>
        <DataTable limit={5} rows={cp.data} error={cp.error?.message} cols={[['Código', (r) => String(r.code)], ['Desconto', (r) => (r.discount_type === 'percent' ? `${r.discount_value}%` : money(Number(r.discount_value)))],
          ['Usos', (r) => `${r.used}/${r.max_redemptions ?? '∞'}`], ['Validade', (r) => dateTime(r.valid_until as string)],
          ['', (r) => <button className="btn sm" onClick={() => run(async () => { await patch(`/admin/coupons/${r.id}`, { active: !r.active }); cp.reload(); })}>{r.active ? 'Desativar' : 'Ativar'}</button>]]} />
      </section>
    </div>
  );
}
