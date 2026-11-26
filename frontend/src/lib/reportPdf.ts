/** PDF textual com fontes padrão e paginação, gerado no navegador. */
export function downloadReportPdf(title: string, subtitle: string, lines: string[], filename: string) {
  const encode = (value: string) => Array.from(value).map((char) => {
    const code = char.charCodeAt(0);
    return (code >= 32 && code <= 255 ? code : 45).toString(16).padStart(2, '0');
  }).join('');
  const text = (value: string, y: number, size = 11) => `BT /F1 ${size} Tf 45 ${y} Td <${encode(value)}> Tj ET\n`;
  const wrapped = lines.flatMap((line) => line.match(/.{1,85}(?:\s|$)|.{1,85}/gu) ?? ['']);
  const pages = Math.max(1, Math.ceil(wrapped.length / 42));
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    `<< /Type /Pages /Count ${pages} /Kids [${Array.from({ length: pages }, (_, i) => `${4 + i * 2} 0 R`).join(' ')}] >>`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>',
  ];
  for (let page = 0; page < pages; page++) {
    const stream = text(title, 790, 18) + text(subtitle, 768) +
      text(`Gerado em ${new Date().toLocaleString('pt-BR')}`, 750) +
      wrapped.slice(page * 42, (page + 1) * 42).map((line, i) => text(line, 720 - i * 15)).join('') +
      text(`Página ${page + 1} de ${pages}`, 43);
    objects.push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents ${5 + page * 2} 0 R >>`,
      `<< /Length ${stream.length} >>\nstream\n${stream}endstream`);
  }
  let pdf = '%PDF-1.4\n';
  const offsets = objects.map((object, i) => {
    const offset = pdf.length;
    pdf += `${i + 1} 0 obj\n${object}\nendobj\n`;
    return offset;
  });
  const xref = pdf.length;
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  pdf += offsets.map((offset) => `${String(offset).padStart(10, '0')} 00000 n \n`).join('');
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  const url = URL.createObjectURL(new Blob([pdf], { type: 'application/pdf' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
