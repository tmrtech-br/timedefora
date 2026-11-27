import { Gamepad2 } from 'lucide-react';

export default function AuthCard({ title, subtitle, children }: { title: React.ReactNode; subtitle?: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'grid', placeItems: 'center', minHeight: '60vh' }}>
      <div className="card" style={{ width: 'min(460px, 100%)', padding: 28 }}>
        <div style={{ display: 'grid', placeItems: 'center', marginBottom: 10 }}>
          <span className="avatar" style={{ width: 56, height: 56 }}><Gamepad2 size={28} aria-hidden /></span>
        </div>
        <h1 style={{ textAlign: 'center', margin: '0 0 4px', fontSize: 24 }}>{title}</h1>
        {subtitle && <p className="muted" style={{ textAlign: 'center', marginTop: 0 }}>{subtitle}</p>}
        <div className="stack" style={{ marginTop: 16 }}>{children}</div>
      </div>
    </div>
  );
}
