/** Relatório em PDF com cabeçalho, tabelas e paginação, gerado no navegador. */
export function downloadReportPdf(title: string, subtitle: string, tables: {
  title: string; headers: string[]; rows: (string | number)[][];
}[], filename: string) {
  const encode = (value: string) => Array.from(value).map((char) => {
    const code = char.charCodeAt(0);
    return (code >= 32 && code <= 255 ? code : 45).toString(16).padStart(2, '0');
  }).join('');
  const text = (value: string, x: number, y: number, size: number, bold = false, color = '0.15 0.08 0.26') =>
    `${color} rg BT /F${bold ? 2 : 1} ${size} Tf ${x} ${y} Td <${encode(value)}> Tj ET\n`;
  const rectangle = (x: number, y: number, width: number, height: number, color: string) =>
    `${color} rg ${x} ${y} ${width} ${height} re f\n`;
  const heading = rectangle(35, 742, 525, 65, '0.15 0.08 0.26')
    + rectangle(35, 739, 525, 3, '0.66 0.46 0.94')
    + text('timedefora', 49, 788, 11, true, '0.86 0.79 1')
    + text(title, 49, 768, 18, true, '1 1 1') + text(subtitle, 49, 750, 10, false, '1 1 1');
  const content: string[] = [];
  let current = heading;
  let y = 711;
  function nextPage() {
    content.push(current);
    current = heading;
    y = 711;
  }
  for (const table of tables) {
    const widths = table.headers.length === 2 ? [340, 185] : [275, 118, 132];
    const columns = widths.map((_, i) => 44 + widths.slice(0, i).reduce((total, width) => total + width, 0));
    function tableHeader(continued = false) {
      current += text(table.title + (continued ? ' (continuação)' : ''), 35, y, 14, true);
      y -= 23;
      current += rectangle(35, y - 5, 525, 18, '0.44 0.27 0.76');
      table.headers.forEach((label, i) => { current += text(label, columns[i], y, 10, true, '1 1 1'); });
      y -= 17;
    }
    if (y < 106) nextPage();
    tableHeader();
    if (!table.rows.length) {
      current += text('Nenhum registro no período.', 44, y, 10);
      y -= 19;
    }
    table.rows.forEach((row, index) => {
      const cells = row.map((cell, i) => {
        const limit = Math.floor((widths[i] - 18) / 6.5);
        return String(cell).match(new RegExp(`.{1,${limit}}(?: |$)|.{1,${limit}}`, 'gu')) ?? [''];
      });
      const rowHeight = Math.max(...cells.map((cell) => cell.length)) * 13 + 7;
      if (y - rowHeight < 55) { nextPage(); tableHeader(true); }
      if (index % 2 === 0) current += rectangle(35, y - rowHeight + 10, 525, rowHeight, '0.96 0.93 0.99');
      cells.forEach((cell, i) => cell.forEach((line, lineIndex) => {
        current += text(line.trim(), columns[i], y - lineIndex * 13, 10);
      }));
      y -= rowHeight;
    });
    y -= 16;
  }
  content.push(current);
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    `<< /Type /Pages /Count ${content.length} /Kids [${content.map((_, i) => `${5 + i * 2} 0 R`).join(' ')}] >>`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>',
  ];
  content.forEach((body, i) => {
    const stream = body + text(`Página ${i + 1} de ${content.length}`, 35, 38, 10);
    objects.push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents ${6 + i * 2} 0 R >>`,
      `<< /Length ${stream.length} >>\nstream\n${stream}endstream`);
  });
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
