// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { useState } from 'react';
import CustomTable, { type Row, type Column } from './CustomTable';
import type { ListRequest } from 'src/lib/NativeViewTypes';
export interface NativeRow extends Row {
  name: string;
  created?: string;
  sortValues?: Record<string, string>;
}
export function tablePage(rows: NativeRow[], request: ListRequest) {
  const filter = request.filter
    ? JSON.parse(decodeURIComponent(request.filter)).predicates?.[0]?.string_value || ''
    : '';
  const filtered = rows.filter((row) =>
    row.name.toLocaleLowerCase().includes(filter.toLocaleLowerCase()),
  );
  const key = request.sortBy?.split(' ')[0] || 'name';
  const value = (row: NativeRow) =>
    key === 'created_at' ? row.created || '' : (row.sortValues?.[key] ?? row.name);
  filtered.sort(
    (a, b) =>
      (value(a).localeCompare(value(b)) || a.id.localeCompare(b.id)) *
      (request.orderAscending ? 1 : -1),
  );
  const start = Number(request.pageToken || 0),
    size = request.pageSize || 10;
  return {
    rows: filtered.slice(start, start + size),
    next: start + size < filtered.length ? String(start + size) : '',
  };
}
export default function NativeTable({
  rows,
  columns,
  selected = [],
  select,
  filterLabel,
  expand,
  toggle,
  emptyMessage,
  filterActions,
  disablePaging,
  radio = false,
}: {
  rows: NativeRow[];
  columns: Column[];
  selected?: string[];
  select?: (ids: string[]) => void;
  filterLabel: string;
  expand?: (row: Row) => React.ReactNode;
  toggle?: (id: string) => void;
  emptyMessage?: string;
  filterActions?: React.ReactNode;
  disablePaging?: boolean;
  radio?: boolean;
}) {
  const [request, setRequest] = useState<ListRequest>({
    pageSize: 10,
    sortBy: 'created_at',
    orderAscending: false,
  });
  const page = tablePage(rows, request);
  return (
    <CustomTable
      columns={columns}
      rows={page.rows}
      dataVersion={rows}
      emptyMessage={emptyMessage}
      filterActions={filterActions}
      disablePaging={disablePaging}
      useRadioButtons={radio}
      selectedIds={selected}
      updateSelection={select}
      disableSelection={!select}
      filterLabel={filterLabel}
      initialSortColumn='created_at'
      reload={async (request) => {
        setRequest({ ...request });
        return tablePage(rows, request).next;
      }}
      getExpandComponent={expand && toggle ? (index) => expand(page.rows[index]) : undefined}
      toggleExpansion={toggle ? (index) => toggle(page.rows[index].id) : undefined}
    />
  );
}
