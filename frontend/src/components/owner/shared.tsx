'use client';
import { Field } from '@/components/ui';

export type OwnerConsole = {
  id: string; code: string; name: string; platform_code: string; agent_id: string | null; is_published: boolean; status: string;
  owner_requested_psn_account_id?: string | null; psn_account_id?: string | null; review_status?: string; review_notes?: string;
  approved_at?: string | null; model?: string; location?: string; description?: string; serial_number?: string | null;
  pending?: { rate?: { rate_cents: number; rate_unit: string; min_minutes: number; max_minutes: number } };
};
export type PsnAccount = { id: string; label: string; online_id: string | null; status: string; agent_id: string | null };

export const REVIEW_LABEL: Record<string, string> = {
  draft: 'Rascunho', submitted: 'Em análise', approved: 'Aprovado', changes_pending: 'Alterações não enviadas', rejected: 'Reprovado',
};

/** Seletor do console em que o proprietário está trabalhando (compartilhado entre os menus). */
export function ConsolePicker({ consoles, value, onChange }: { consoles: OwnerConsole[] | null; value: string; onChange: (id: string) => void }) {
  if (!consoles?.length) return <p className="muted">Cadastre um console em <a className="link-purple" href="#cadastro">Cadastro de console</a> primeiro.</p>;
  return <Field label="Console"><select value={value} onChange={(e) => onChange(e.target.value)}>
    <option value="">Selecione o console</option>
    {consoles.map((c) => <option key={c.id} value={c.id}>{c.name} · {c.platform_code} · {c.is_published ? 'Publicado' : REVIEW_LABEL[c.review_status ?? 'draft']}</option>)}
  </select></Field>;
}

/** Gráfico de barras simples em SVG (sem dependências): rótulo à esquerda, barra proporcional e valor. */
export function BarChart({ title, data, format }: { title: string; data: { label: string; value: number }[]; format: (v: number) => string }) {
  const max = Math.max(1, ...data.map((d) => d.value));
  const rowH = 32;
  return <figure className="owner-chart" aria-label={title}>
    <figcaption>{title}</figcaption>
    {data.length === 0 ? <p className="small muted">Sem dados no período.</p> :
      <svg viewBox={`0 0 600 ${data.length * rowH}`} width="100%" role="img" aria-label={title} preserveAspectRatio="xMinYMin meet">
        {data.map((d, i) => {
          const w = Math.max(2, (d.value / max) * 360);
          return <g key={d.label} transform={`translate(0 ${i * rowH})`}>
            <text x="0" y="21" className="oc-label">{d.label.length > 22 ? d.label.slice(0, 21) + '…' : d.label}</text>
            <rect x="170" y="6" width={w} height="20" rx="5" className="oc-bar" />
            <text x={176 + w} y="21" className="oc-value">{format(d.value)}</text>
          </g>;
        })}
      </svg>}
  </figure>;
}
