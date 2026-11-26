type Report = { title: string; headers: string[]; rows: (string | number)[][] };

function save(filename: string, data: string, type: string) {
  const url = URL.createObjectURL(new Blob([data], { type }));
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function exportExcel(filename: string, reports: Report[]) {
  const escape = (value: string | number) => String(value).replace(/[<>&"']/g, (c) => ({
    '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;', "'": '&apos;',
  })[c] ?? c).replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, '');
  const table = ({ title, headers, rows }: Report) => `<Worksheet ss:Name="${escape(title.slice(0, 31))}"><Table>${[headers, ...rows].map(row => (
    `<Row>${row.map(value => `<Cell><Data ss:Type="${typeof value === 'number' ? 'Number' : 'String'}">${escape(value)}</Data></Cell>`).join('')}</Row>`
  )).join('')}</Table></Worksheet>`;
  save(filename + '.xml', `<?xml version="1.0" encoding="UTF-8"?><?mso-application progid="Excel.Sheet"?><Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">${reports.map(table).join('')}</Workbook>`, 'application/xml;charset=utf-8');
}

export function printReport({ title, headers, rows }: Report) {
  const page = window.open('', '_blank', 'popup');
  if (!page) return false;
  page.opener = null;
  page.document.title = title;
  const style = page.document.createElement('style');
  style.textContent = 'body{font:12px system-ui}table{border-collapse:collapse;width:100%}td,th{border:1px solid #aaa;padding:5px;text-align:left;overflow-wrap:anywhere}tr{break-inside:avoid}';
  page.document.head.append(style);
  const heading = page.document.createElement('h1');
  heading.textContent = title;
  const table = page.document.createElement('table');
  const head = table.createTHead().insertRow();
  headers.forEach(value => {
    const cell = page.document.createElement('th');
    cell.textContent = value;
    head.append(cell);
  });
  const body = table.createTBody();
  rows.forEach(row => {
    const line = body.insertRow();
    row.forEach(value => { line.insertCell().textContent = String(value); });
  });
  page.document.body.append(heading, table);
  page.print();
  return true;
}
