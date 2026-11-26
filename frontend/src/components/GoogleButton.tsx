'use client';
import { useEffect, useState } from 'react';
import { get } from '@/lib/api';
import { useFeatures } from '@/lib/features';

export default function GoogleButton({ intent = 'login', label = 'Continuar com Google' }: { intent?: 'login' | 'link'; label?: string }) {
  const features = useFeatures();
  const [configured, setConfigured] = useState<boolean | null>(null);
  useEffect(() => { get<{ configured: boolean }>('/auth/google/status').then((r) => setConfigured(r.configured)).catch(() => setConfigured(false)); }, []);
  if (configured === null || features?.google_login_enabled === false) return null;
  if (!configured) return <button className="btn block" disabled title="Google OAuth ainda não configurado neste ambiente">{label} (indisponível)</button>;
  return <a className="btn block" href={`/api/auth/google/start?intent=${intent}`}>{label}</a>;
}
