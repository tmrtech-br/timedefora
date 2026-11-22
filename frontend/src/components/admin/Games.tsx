'use client';
import { useState } from 'react';
import { Field, PageHeader, StatusPill } from '@/components/ui';
import { patch, post } from '@/lib/api';
import { useApi } from '@/lib/hooks';
import { DataTable, useAction } from './common';

type Game = Record<string, unknown> & { id: string; slug: string; title: string; status: string; commercial_license_status: string; platform_codes: string[]; genres: string[] };
const EMPTY = { slug: '', title: '', short_description: '', description: '', cover_url: '', banner_url: '', trailer_url: '', trailer_licensed: false, age_rating: '',
  release_date: '', requirements: '', min_minutes: 10, max_minutes: 120, featured_manual: false, image_rights_notes: '', stream_rights_allowed: false, platform_codes: ['PS5'], genres: '' };
const LIC: Record<string, string> = { not_verified: 'Não verificada', pending: 'Pendente', authorized: 'Autorizada', denied: 'Negada' };

export default function Games() {
  const list = useApi<Game[]>('/admin/games');
  const [f, setF] = useState<Record<string, unknown>>(EMPTY);
  const [editing, setEditing] = useState<string | null>(null);
  const [lic, setLic] = useState({ status: 'pending', doc_url: '', notes: '' });
  const { run, msg, busy } = useAction();
  const set = (k: string, v: unknown) => setF({ ...f, [k]: v });
  const body = () => ({ ...f, age_rating: f.age_rating || null, release_date: f.release_date || null, cover_url: f.cover_url || null, banner_url: f.banner_url || null,
    trailer_url: f.trailer_url || null, min_minutes: Number(f.min_minutes), max_minutes: Number(f.max_minutes),
    genres: String(f.genres).split(',').map((x) => x.trim()).filter(Boolean) });
  function edit(g: Game) {
    setEditing(g.id);
    setF({ ...EMPTY, ...Object.fromEntries(Object.entries(g).filter(([k]) => k in EMPTY).map(([k, v]) => [k, v ?? ''])), genres: g.genres.join(', '), platform_codes: g.platform_codes });
  }
  return (
    <div className="stack">
      <PageHeader title="Jogos" subtitle="Cadastro independente de consoles. Venda real exige licença comercial autorizada." />
      {msg}
      <section className="card stack">
        <h2>{editing ? 'Editar jogo' : 'Novo jogo'}</h2>
        <div className="grid3">
          <Field label="Título"><input value={String(f.title)} onChange={(e) => set('title', e.target.value)} /></Field>
          <Field label="Slug (URL)"><input value={String(f.slug)} onChange={(e) => set('slug', e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-'))} /></Field>
          <Field label="Frase de destaque"><input value={String(f.short_description)} onChange={(e) => set('short_description', e.target.value)} /></Field>
          <Field label="Capa (URL)"><input value={String(f.cover_url)} onChange={(e) => set('cover_url', e.target.value)} /></Field>
          <Field label="Banner (URL)"><input value={String(f.banner_url)} onChange={(e) => set('banner_url', e.target.value)} /></Field>
          <Field label="Trailer (URL)"><input value={String(f.trailer_url)} onChange={(e) => set('trailer_url', e.target.value)} /></Field>
          <Field label="Plataformas"><select multiple value={f.platform_codes as string[]} onChange={(e) => set('platform_codes', Array.from(e.target.selectedOptions).map((o) => o.value))} style={{ height: 90 }}>
            {['PS5', 'PS4', 'XBOX_SERIES', 'XBOX_ONE', 'SWITCH'].map((p) => <option key={p}>{p}</option>)}</select></Field>
          <Field label="Gêneros (separados por vírgula)"><input value={String(f.genres)} onChange={(e) => set('genres', e.target.value)} /></Field>
          <Field label="Classificação etária"><select value={String(f.age_rating)} onChange={(e) => set('age_rating', e.target.value)}><option value="">—</option>{['L', '10', '12', '14', '16', '18'].map((x) => <option key={x}>{x}</option>)}</select></Field>
          <Field label="Lançamento"><input type="date" value={String(f.release_date)} onChange={(e) => set('release_date', e.target.value)} /></Field>
          <Field label="Duração mínima (min)"><input type="number" value={String(f.min_minutes)} onChange={(e) => set('min_minutes', e.target.value)} /></Field>
          <Field label="Duração máxima (min)"><input type="number" value={String(f.max_minutes)} onChange={(e) => set('max_minutes', e.target.value)} /></Field>
        </div>
        <Field label="Descrição"><textarea value={String(f.description)} onChange={(e) => set('description', e.target.value)} /></Field>
        <Field label="Requisitos"><input value={String(f.requirements)} onChange={(e) => set('requirements', e.target.value)} /></Field>
        <Field label="Direitos de imagem / observações"><input value={String(f.image_rights_notes)} onChange={(e) => set('image_rights_notes', e.target.value)} /></Field>
        <div className="row">
          <label className="check"><input type="checkbox" checked={!!f.trailer_licensed} onChange={(e) => set('trailer_licensed', e.target.checked)} />Trailer licenciado</label>
          <label className="check"><input type="checkbox" checked={!!f.stream_rights_allowed} onChange={(e) => set('stream_rights_allowed', e.target.checked)} />Transmissão pública autorizada</label>
          <label className="check"><input type="checkbox" checked={!!f.featured_manual} onChange={(e) => set('featured_manual', e.target.checked)} />Destaque manual na home</label>
        </div>
        <div className="row">
          <button className="btn primary" disabled={busy} onClick={() => run(async () => { editing ? await patch(`/admin/games/${editing}`, body()) : await post('/admin/games', body()); list.reload(); }, editing ? 'Jogo atualizado.' : 'Jogo criado como rascunho.')}>{editing ? 'Salvar' : 'Cadastrar'}</button>
          {editing && <button className="btn" onClick={() => { setEditing(null); setF(EMPTY); }}>Novo</button>}
        </div>
      </section>
      {editing && <section className="card stack"><h2>Licenciamento comercial</h2>
        <div className="grid3"><Field label="Situação"><select value={lic.status} onChange={(e) => setLic({ ...lic, status: e.target.value })}>{Object.entries(LIC).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
          <Field label="Documento de autorização (URL)"><input value={lic.doc_url} onChange={(e) => setLic({ ...lic, doc_url: e.target.value })} /></Field>
          <Field label="Observações"><input value={lic.notes} onChange={(e) => setLic({ ...lic, notes: e.target.value })} /></Field></div>
        <button className="btn" onClick={() => run(async () => { await post(`/admin/games/${editing}/license`, { ...lic, doc_url: lic.doc_url || null }); list.reload(); }, 'Licença atualizada.')}>Registrar</button></section>}
      <section className="card"><DataTable rows={list.data} cols={[['Jogo', (g) => <button className="btn sm" onClick={() => edit(g)}>{g.title}</button>],
        ['Plataformas', (g) => g.platform_codes.join(', ')], ['Status', (g) => <StatusPill status={g.status} />], ['Licença', (g) => LIC[g.commercial_license_status]],
        ['Demo', (g) => (g.is_demo ? 'sim' : 'não')],
        ['Ações', (g) => <div className="row">{g.status !== 'published'
          ? <button className="btn sm primary" onClick={() => run(async () => { await patch(`/admin/games/${g.id}`, { status: 'published' }); list.reload(); }, 'Publicado.')}>Publicar</button>
          : <button className="btn sm" onClick={() => run(async () => { await patch(`/admin/games/${g.id}`, { status: 'unpublished', resolution: 'keep_existing' }); list.reload(); }, 'Despublicado (reservas mantidas).')}>Despublicar</button>}</div>]]} /></section>
    </div>
  );
}
