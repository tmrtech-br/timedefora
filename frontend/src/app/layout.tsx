import type { Metadata, Viewport } from 'next';
import '@fontsource/poppins/latin-400.css';
import '@fontsource/poppins/latin-500.css';
import '@fontsource/poppins/latin-600.css';
import '@fontsource/poppins/latin-700.css';
import '@fontsource/poppins/latin-700-italic.css';
import '@fontsource/poppins/latin-800-italic.css';
import './globals.css';
import AppShell from '@/components/AppShell';
import ChunkRecovery from '@/components/ChunkRecovery';
import { AuthProvider } from '@/lib/auth';

export const metadata: Metadata = {
  title: { default: 'LocaPlay | Locadora de games na nuvem', template: '%s | LocaPlay' },
  description: 'Alugue tempo em consoles e jogue direto no navegador.',
};
export const viewport: Viewport = { themeColor: '#0b0918', width: 'device-width', initialScale: 1 };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="pt-BR">
      <body>
        <ChunkRecovery />
        <AuthProvider>
          <AppShell>{children}</AppShell>
        </AuthProvider>
      </body>
    </html>
  );
}
