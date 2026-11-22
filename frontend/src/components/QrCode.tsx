'use client';
import { useEffect, useState } from 'react';
import QRCode from 'qrcode';

/** QR code gerado no próprio navegador (sem serviço externo: o conteúdo, ex. segredo TOTP, não sai da página). */
export default function QrCode({ value, size = 200, label }: { value: string; size?: number; label: string }) {
  const [svg, setSvg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    QRCode.toString(value, { type: 'svg', errorCorrectionLevel: 'M', margin: 2, color: { dark: '#000000', light: '#ffffff' } })
      .then((s) => { if (alive) { setSvg(s); setFailed(false); } })
      .catch(() => { if (alive) setFailed(true); });
    return () => { alive = false; };
  }, [value]);

  if (failed) return <p className="small dim">Não foi possível gerar o QR code; use a chave abaixo.</p>;
  if (!svg) return <div style={{ width: size, height: size }} aria-hidden="true" />;
  return (
    <div
      role="img"
      aria-label={label}
      style={{ width: size, height: size, background: '#fff', borderRadius: 8, padding: 4, lineHeight: 0 }}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
