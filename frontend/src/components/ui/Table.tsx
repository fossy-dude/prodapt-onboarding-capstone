import { type ReactNode } from 'react';

interface TableColumn {
  readonly key: string;
  readonly header: ReactNode;
}

interface TableProps<T> {
  readonly columns: readonly TableColumn[];
  readonly rows: readonly T[];
  /** Returns a `<tr>` for the row — supports stateful row components (e.g. per-row mutations). */
  readonly renderRow: (row: T) => ReactNode;
  readonly emptyState?: ReactNode;
  readonly caption?: string;
  readonly className?: string;
}

/**
 * Lightweight table primitive built on Tailwind utilities (UX brief §3.1).
 * Generic over the row type. Headers come from `columns`; each row body is
 * produced by `renderRow`, so rows keep full control over their own state.
 */
function Table<T>({
  columns,
  rows,
  renderRow,
  emptyState,
  caption,
  className = '',
}: TableProps<T>) {
  return (
    <div className={`overflow-x-auto ${className}`}>
      <table className="w-full text-left text-sm">
        {caption && <caption className="mb-2 text-xs text-neutral-500">{caption}</caption>}
        <thead>
          <tr className="border-b border-neutral-300 text-xs text-neutral-500">
            {columns.map((column) => (
              <th key={column.key} className="pb-2 pr-4 last:pr-0">
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && emptyState ? (
            <tr>
              <td colSpan={columns.length} className="py-4 text-sm text-neutral-500">
                {emptyState}
              </td>
            </tr>
          ) : (
            rows.map((row) => renderRow(row))
          )}
        </tbody>
      </table>
    </div>
  );
}

export { Table };
export type { TableColumn, TableProps };
