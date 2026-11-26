'use client';
import { useParams, useSearchParams } from 'next/navigation';
import { Suspense } from 'react';
import RequireAuth from '@/components/RequireAuth';
import { Skeleton } from '@/components/ui';
import TicketConversation from '../TicketConversation';
import styles from '../support.module.css';

function TicketPage() {
  const { id } = useParams<{ id: string }>();
  const audit = useSearchParams().get('auditoria') === '1';
  return <div className={styles.conversationPage}><TicketConversation key={`${id}:${audit}`} id={id} audit={audit} /></div>;
}

export default function Page() {
  return <RequireAuth><Suspense fallback={<Skeleton h={200} />}><TicketPage /></Suspense></RequireAuth>;
}
