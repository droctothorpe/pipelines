// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import type { ReactNode } from 'react';
import { useNavigate } from 'react-router';
import { Alert } from '@mui/material';
import Toolbar, { type ToolbarActionMap, type Breadcrumb } from './Toolbar';
import { commonCss } from 'src/Css';

export default function NativePage({
  title,
  actions = {},
  breadcrumbs = [],
  error,
  children,
}: {
  title: string;
  actions?: ToolbarActionMap;
  breadcrumbs?: Breadcrumb[];
  error?: unknown;
  children: ReactNode;
}) {
  const navigate = useNavigate();
  return (
    <div className={commonCss.page}>
      <Toolbar pageTitle={title} actions={actions} breadcrumbs={breadcrumbs} navigate={navigate} />
      {error ? (
        <Alert severity='error'>{error instanceof Error ? error.message : String(error)}</Alert>
      ) : null}
      {children}
    </div>
  );
}
