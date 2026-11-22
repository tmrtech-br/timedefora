import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = { title: 'LocaPlay | Locadora de games na nuvem', description: 'Protótipo demonstrativo de locação de tempo de videogames.' };
export default function RootLayout({ children }: Readonly<{children: React.ReactNode}>) { return <html lang="pt-BR"><body>{children}</body></html>; }
