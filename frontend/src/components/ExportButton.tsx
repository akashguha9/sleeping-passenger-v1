'use client';

import { useState } from 'react';

type ExportFormat = 'json' | 'csv';

interface Props {
  label: string;
  filename: string;
  getData: () => unknown;
  format?: ExportFormat;
}

export function ExportButton({ label, filename, getData, format = 'json' }: Props) {
  const [exported, setExported] = useState(false);

  function handleExport() {
    const data = getData();
    let content: string;
    let mimeType: string;

    if (format === 'csv' && Array.isArray(data) && data.length > 0) {
      const headers = Object.keys(data[0] as object).join(',');
      const rows = (data as Record<string, unknown>[]).map((row) =>
        Object.values(row)
          .map((v) => {
            const s = Array.isArray(v) ? v.join(';') : String(v ?? '');
            return `"${s.replace(/"/g, '""')}"`;
          })
          .join(',')
      );
      content = [headers, ...rows].join('\n');
      mimeType = 'text/csv';
    } else {
      content = JSON.stringify(data, null, 2);
      mimeType = 'application/json';
    }

    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${filename}.${format}`;
    a.click();
    URL.revokeObjectURL(url);

    setExported(true);
    setTimeout(() => setExported(false), 2000);
  }

  return (
    <button
      onClick={handleExport}
      className={`flex items-center gap-2 px-4 py-2 rounded text-sm font-medium transition-colors ${
        exported
          ? 'bg-emerald-700 text-white'
          : 'bg-slate-700 hover:bg-slate-600 text-slate-200'
      }`}
    >
      <span>{exported ? '✓' : '↓'}</span>
      <span>{exported ? 'Exported' : label}</span>
      <span className="text-xs text-slate-500 uppercase">{format}</span>
    </button>
  );
}
