type Report = {
  title: string;
  headers: string[];
  rows: (string | number)[][];
  excelWidths?: number[];
  printWidths?: number[];
};

type ReportHeader = { title: string; subtitle: string; landscape?: boolean };

function save(filename: string, data: string, type: string) {
  const url = URL.createObjectURL(new Blob([data], { type }));
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function exportExcel(filename: string, reports: Report[], header?: ReportHeader) {
  const escape = (value: string | number) => String(value).replace(/[<>&"']/g, (c) => ({
    '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;', "'": '&apos;',
  })[c] ?? c).replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, '');
  const textCell = (value: string | number, style?: string) =>
    `<Cell${style ? ` ss:StyleID="${style}"` : ''}><Data ss:Type="${typeof value === 'number' ? 'Number' : 'String'}">${escape(value)}</Data></Cell>`;
  const banner = (value: string, style: string, columns: number) =>
    textCell(value, style).replace('<Cell ', `<Cell ss:MergeAcross="${columns - 1}" `);
  const table = ({ title, headers, rows, excelWidths }: Report) => `<Worksheet ss:Name="${escape(title.slice(0, 31))}"><Table>${
    headers.map((_, i) => `<Column ss:AutoFitWidth="0" ss:Width="${excelWidths?.[i] ?? (i === 0 ? 210 : 155)}"/>`).join('')
  }<Row ss:Height="32">${banner(header?.title ?? title, 'Title', headers.length)}</Row>${
    header ? `<Row ss:Height="26">${banner(header.subtitle, 'Subtitle', headers.length)}</Row><Row ss:Height="24">${banner(title, 'Section', headers.length)}</Row>` : ''
  }<Row ss:Height="22">${headers.map(value => textCell(value, 'Heading')).join('')}</Row>${
    rows.map((row, index) => `<Row ss:AutoFitHeight="1">${row.map(value => textCell(value, index % 2 ? 'Alternate' : 'Body')).join('')}</Row>`).join('')
  }</Table></Worksheet>`;
  const styles = `<Styles>
    <Style ss:ID="Title"><Font ss:Bold="1" ss:Color="#FFFFFF" ss:Size="17"/><Interior ss:Color="#251543" ss:Pattern="Solid"/><Alignment ss:Vertical="Center"/></Style>
    <Style ss:ID="Subtitle"><Font ss:Color="#514667" ss:Size="10"/><Alignment ss:Vertical="Center"/></Style>
    <Style ss:ID="Section"><Font ss:Bold="1" ss:Color="#563198" ss:Size="13"/><Alignment ss:Vertical="Center"/></Style>
    <Style ss:ID="Heading"><Font ss:Bold="1" ss:Color="#FFFFFF"/><Interior ss:Color="#7045C2" ss:Pattern="Solid"/><Alignment ss:Vertical="Center"/></Style>
    <Style ss:ID="Body"><Font ss:Color="#251543"/><Alignment ss:WrapText="1" ss:Vertical="Top"/></Style>
    <Style ss:ID="Alternate"><Font ss:Color="#251543"/><Interior ss:Color="#F1ECFA" ss:Pattern="Solid"/><Alignment ss:WrapText="1" ss:Vertical="Top"/></Style>
  </Styles>`;
  save(filename + '.xml', `<?xml version="1.0" encoding="UTF-8"?><?mso-application progid="Excel.Sheet"?><Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">${styles}${reports.map(table).join('')}</Workbook>`, 'application/xml;charset=utf-8');
}

export function printReports({ title, subtitle, landscape = false }: ReportHeader, reports: Report[]) {
  const page = window.open('', '_blank', 'popup');
  if (!page) return false;
  page.opener = null;
  const doc = page.document;
  doc.documentElement.lang = 'pt-BR';
  doc.title = title;
  const appendText = (parent: HTMLElement, tag: string, value: string) => {
    const item = doc.createElement(tag);
    item.textContent = value;
    parent.append(item);
  };
  appendText(doc.head, 'style', `
    @page { size: A4 ${landscape ? 'landscape' : 'portrait'}; margin: 14mm; }
    * { box-sizing: border-box; print-color-adjust: exact; -webkit-print-color-adjust: exact; }
    body { margin: 0 auto; max-width: ${landscape ? 1180 : 950}px; color: #251543; font: 11px system-ui, sans-serif; }
    header { padding: 22px 26px; background: #251543; color: white; border-bottom: 5px solid #a675ef; }
    header strong { color: #dbcaff; font-size: 13px; }
    h1 { margin: 6px 0; font-size: 27px; }
    section { margin: 22px 0; }
    h2 { color: #563198; margin: 0 0 8px; font-size: 16px; break-after: avoid; }
    p { margin: 4px 0; }
    table { width: 100%; border-collapse: collapse; }
    table.sized-columns { table-layout: fixed; }
    th, td { padding: 7px 9px; text-align: left; vertical-align: top; overflow-wrap: anywhere; }
    th { color: white; background: #7045c2; }
    td { border-bottom: 1px solid #e3d9f4; }
    tbody tr:nth-child(even) { background: #f5f0fd; }
    tr { break-inside: avoid; }
    @media screen { body { padding: 20px; } }
  `);
  const header = doc.createElement('header');
  appendText(header, 'strong', 'timedefora');
  appendText(header, 'h1', title);
  if (subtitle) appendText(header, 'p', subtitle);
  doc.body.append(header);
  for (const report of reports) {
    const section = doc.createElement('section');
    if (report.title !== title) appendText(section, 'h2', report.title);
    const table = doc.createElement('table');
    if (report.printWidths) {
      table.className = 'sized-columns';
      const cols = doc.createElement('colgroup');
      report.printWidths.forEach(width => {
        const column = doc.createElement('col');
        column.style.width = `${width}%`;
        cols.append(column);
      });
      table.append(cols);
    }
    const head = table.createTHead().insertRow();
    report.headers.forEach(value => appendText(head, 'th', value));
    const body = table.createTBody();
    report.rows.forEach(row => {
      const line = body.insertRow();
      row.forEach(value => { line.insertCell().textContent = String(value); });
    });
    if (report.rows.length) section.append(table);
    else appendText(section, 'p', 'Nenhum registro no filtro selecionado.');
    doc.body.append(section);
  }
  page.focus();
  page.print();
  return true;
}
