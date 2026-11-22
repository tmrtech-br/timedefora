'use client';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect } from 'react';
import { Loading } from './ui';
import { useAuth } from '@/lib/auth';

export default function RequireAuth({ children }: { children: React.ReactNode }) {
  const { me, loading } = useAuth();
  const router = useRouter();
  const path = usePathname();
  useEffect(() => { if (!loading && !me) router.replace(`/entrar?proximo=${encodeURIComponent(path)}`); }, [loading, me, router, path]);
  if (loading || !me) return <Loading />;
  return <>{children}</>;
}
