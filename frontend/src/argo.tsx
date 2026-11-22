// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0

import 'src/build/tailwind.output.css';
import '@xyflow/react/dist/style.css';
import { StrictMode, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { StyledEngineProvider, ThemeProvider } from '@mui/material/styles';
import { cssRule } from 'typestyle';
import { fonts, theme } from 'src/Css';
import Router from 'src/components/Router';
import { getUiConfig } from 'src/lib/Argo';
import { useDashboardNamespace } from 'src/lib/Dashboard';

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

/**
 * An explicit `?namespace=` wins; otherwise the hosting dashboard's selection,
 * a namespace chosen in the UI, the proxy's own namespace, then `argo`. A
 * multi-user proxy names no namespace of its own, so it stays empty until one
 * of the others answers.
 */
function App() {
  const config = useQuery({
    queryKey: ['ui-config'],
    queryFn: ({ signal }) => getUiConfig(signal),
    staleTime: Infinity,
    retry: false,
  });
  const dashboard = useDashboardNamespace();
  const [chosen, setChosen] = useState('');
  const previous = useRef<string | undefined>(undefined);
  const namespace =
    requested ||
    dashboard ||
    chosen ||
    config.data?.namespace ||
    (config.data?.authMode === 'multi-user' ? '' : 'argo');
  useEffect(() => {
    // Switching namespace in the dashboard leaves the list route in place, but a
    // detail page belongs to the old namespace: fall back to its list.
    const segments = window.location.hash.replace(/^#\/?/, '').split('/');
    if (previous.current && previous.current !== namespace && segments.length > 1) {
      window.location.hash = '#/' + segments[0];
    }
    previous.current = namespace;
  }, [namespace]);
  if (!config.data) return null;
  return (
    <Router
      key={namespace}
      namespace={namespace}
      authMode={config.data.authMode}
      onNamespace={setChosen}
    />
  );
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
