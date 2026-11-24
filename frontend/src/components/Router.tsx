// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { useState } from 'react';
import { HashRouter, Navigate, Route, Routes, useLocation } from 'react-router';
import { Button, Dialog, DialogTitle, DialogContent, DialogActions } from '@mui/material';
import { classes } from 'typestyle';
import { commonCss } from 'src/Css';
import Input from 'src/atoms/Input';
import BusyButton from 'src/atoms/BusyButton';
import SideNavigation from './SideNav';
import NativePage from './NativePage';
import { setArgoToken, type UiAuthMode } from 'src/lib/Argo';
import { embedded } from 'src/lib/Dashboard';
import { NativeUiContext, type Confirmation } from 'src/lib/NativeUiContext';
import {
  NativeListPage,
  NativePipelineDetails,
  NativeExperimentDetails,
  NativeNewExperiment,
  NativeNewRun,
  NativeCompare,
  NativeArtifactDetails,
  NativeScheduleDetails,
} from 'src/pages/NativePages';
import NativeRunDetails from 'src/pages/NativeRunDetails';
import NativeUpload from 'src/pages/NativeUpload';

export const RoutePrefix = { ARTIFACT: '/artifact', RECURRING_RUN: '/recurringrun' };
export const RoutePage = {
  START: '/start',
  PIPELINES: '/pipelines',
  PIPELINES_SHARED: '/shared/pipelines',
  EXPERIMENTS: '/experiments',
  ARCHIVED_EXPERIMENTS: '/archive/experiments',
  RUNS: '/runs',
  ARCHIVED_RUNS: '/archive/runs',
  COMPARE: '/compare',
  RECURRING_RUNS: '/recurringruns',
  ARTIFACTS: '/artifacts',
};
export const ExternalLinks = {
  DOCUMENTATION: 'https://www.kubeflow.org/docs/pipelines/',
  GITHUB: 'https://github.com/kubeflow/pipelines',
  GITHUB_ISSUE: 'https://github.com/kubeflow/pipelines/issues/new/choose',
};

const NAMESPACE_LABEL = /^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$/;

function Workspace({
  namespace,
  authMode,
  onNamespace,
}: {
  namespace: string;
  authMode: UiAuthMode;
  onNamespace?: (namespace: string) => void;
}) {
  const location = useLocation();
  const [tokenConnected, setTokenConnected] = useState(false);
  // Single-user proxies authenticate with their own service account and
  // multi-user proxies with the gateway's identity, once a namespace is known;
  // otherwise a namespace-scoped browser token is required before any request.
  const multiUser = authMode === 'multi-user';
  const connected = authMode === 'single-user' || (multiUser && !!namespace) || tokenConnected;
  const [token, setToken] = useState('');
  const [candidate, setCandidate] = useState('');
  const [error, setError] = useState('');
  const [confirmation, setConfirmation] = useState<Confirmation>();
  const [busy, setBusy] = useState(false);
  const fail = (error: unknown) => setError(error instanceof Error ? error.message : String(error));
  return (
    <NativeUiContext.Provider value={{ namespace, fail, confirm: setConfirmation }}>
      <div className={commonCss.page}>
        <div className={commonCss.flexGrow} style={{ minHeight: 0 }}>
          {/* The central dashboard has its own navigation for these pages. */}
          {!embedded() && <SideNavigation page={location.pathname} />}
          {connected ? (
            // Stock remounted a page per location so list selections and
            // query-seeded forms never leak across navigations; run details
            // keeps its instance across query changes (tab, task selection).
            <Routes
              key={
                location.pathname.startsWith('/runs/details/')
                  ? location.pathname
                  : `${location.pathname}${location.search}${location.hash}`
              }
            >
              <Route path='/pipelines' element={<NativeListPage kind='pipelines' />} />
              <Route path='/pipeline_versions/new' element={<NativeUpload />} />
              <Route
                path='/shared/pipelines'
                element={<NativeListPage kind='pipelines' shared />}
              />
              <Route
                path='/pipelines/details/:pipelineId/version/:versionId?'
                element={<NativePipelineDetails />}
              />
              <Route path='/pipelines/details/:pipelineId' element={<NativePipelineDetails />} />
              <Route path='/experiments' element={<NativeListPage kind='experiments' />} />
              <Route
                path='/archive/experiments'
                element={<NativeListPage kind='experiments' archived />}
              />
              <Route path='/experiments/new' element={<NativeNewExperiment />} />
              <Route
                path='/experiments/details/:experimentId'
                element={<NativeExperimentDetails />}
              />
              <Route path='/runs' element={<NativeListPage kind='runs' />} />
              <Route path='/archive/runs' element={<NativeListPage kind='runs' archived />} />
              <Route path='/runs/new' element={<NativeNewRun />} />
              <Route path='/runs/details/:runId' element={<NativeRunDetails />} />
              <Route path='/compare' element={<NativeCompare />} />
              <Route path='/recurringruns' element={<NativeListPage kind='schedules' />} />
              <Route path='/recurringrun/details/:scheduleId' element={<NativeScheduleDetails />} />
              <Route path='/artifacts' element={<NativeListPage kind='artifacts' />} />
              <Route path='/artifacts/:runId/:nodeId/:port' element={<NativeArtifactDetails />} />
              <Route path='*' element={<Navigate to='/pipelines' replace />} />
            </Routes>
          ) : (
            <NativePage title='Pipelines'>{null}</NativePage>
          )}
        </div>
      </div>
      <Dialog open={!connected} maxWidth='sm' fullWidth>
        <DialogTitle>Connect to Kubeflow Pipelines</DialogTitle>
        <DialogContent>
          {multiUser ? (
            <>
              <p>
                {embedded()
                  ? 'Waiting for the dashboard to select a namespace. You can also enter one.'
                  : 'Enter the namespace whose pipelines you want to work with.'}
              </p>
              <Input
                label='Namespace'
                value={candidate}
                onChange={(event) => setCandidate(event.target.value)}
                variant='outlined'
                autoComplete='off'
                autoFocus
              />
            </>
          ) : (
            <>
              <p>
                Namespace: {namespace}. Use a Kubernetes bearer token with access to this namespace.
                The token stays in memory and is cleared on reload.
              </p>
              <Input
                label='Kubernetes bearer token'
                type='password'
                value={token}
                onChange={(event) => setToken(event.target.value)}
                variant='outlined'
                autoComplete='off'
                autoFocus
              />
            </>
          )}
        </DialogContent>
        <DialogActions>
          <Button
            disabled={multiUser ? !NAMESPACE_LABEL.test(candidate.trim()) : !token.trim()}
            onClick={() => {
              if (multiUser) {
                onNamespace?.(candidate.trim());
                return;
              }
              setArgoToken(token);
              setToken('');
              setTokenConnected(true);
            }}
          >
            Connect
          </Button>
        </DialogActions>
      </Dialog>
      <Dialog open={!!error} onClose={() => setError('')}>
        <DialogTitle>Error</DialogTitle>
        <DialogContent className={commonCss.prewrap}>{error}</DialogContent>
        <DialogActions>
          <Button onClick={() => setError('')}>OK</Button>
        </DialogActions>
      </Dialog>
      <Dialog open={!!confirmation} onClose={() => !busy && setConfirmation(undefined)}>
        <DialogTitle>{confirmation?.title}</DialogTitle>
        <DialogContent className={classes(commonCss.prewrap)}>
          {confirmation?.content}
        </DialogContent>
        <DialogActions>
          <Button disabled={busy} onClick={() => setConfirmation(undefined)}>
            Cancel
          </Button>
          <BusyButton
            title='Confirm'
            busy={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await confirmation?.action();
                setConfirmation(undefined);
              } catch (error) {
                setConfirmation(undefined);
                fail(error);
              } finally {
                setBusy(false);
              }
            }}
          />
        </DialogActions>
      </Dialog>
    </NativeUiContext.Provider>
  );
}
export default function Router({
  namespace,
  authMode = 'token',
  onNamespace,
}: {
  namespace: string;
  authMode?: UiAuthMode;
  /** Multi-user mode without a dashboard: the person names the namespace. */
  onNamespace?: (namespace: string) => void;
}) {
  return (
    <HashRouter>
      <Workspace namespace={namespace} authMode={authMode} onNamespace={onNamespace} />
    </HashRouter>
  );
}
