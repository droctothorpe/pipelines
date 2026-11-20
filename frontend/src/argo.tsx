// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0

import 'src/build/tailwind.output.css';
import '@xyflow/react/dist/style.css';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { StyledEngineProvider, ThemeProvider } from '@mui/material/styles';
import { cssRule } from 'typestyle';
import { fonts, theme } from 'src/Css';
import Router from 'src/components/Router';
import { getUiConfig } from 'src/lib/Argo';

cssRule('html, body, #root', {
  margin: 0,
  display: 'flex',
  background: 'white',
  color: 'rgba(0, 0, 0, .66)',
  fontFamily: fonts.main,
  fontSize: 13,
  height: '100%',
  width: '100%',
});

const requested = new URLSearchParams(window.location.search).get('namespace');

/** An explicit `?namespace=` wins; otherwise the proxy's own namespace, then `argo`. */
function App() {
  const config = useQuery({
    queryKey: ['ui-config'],
    queryFn: ({ signal }) => getUiConfig(signal),
    staleTime: Infinity,
    retry: false,
  });
  if (!config.data) return null;
  const namespace = requested || config.data.namespace || 'argo';
  return <Router key={namespace} namespace={namespace} authMode={config.data.authMode} />;
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={new QueryClient()}>
      <StyledEngineProvider injectFirst>
        <ThemeProvider theme={theme}>
          <App />
        </ThemeProvider>
      </StyledEngineProvider>
    </QueryClientProvider>
  </StrictMode>,
);
