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
import { setArgoToken } from 'src/lib/Argo';
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

function Workspace({ namespace }: { namespace: string }) {
  const location = useLocation();
  const [connected, setConnected] = useState(false);
  const [token, setToken] = useState('');
  const [error, setError] = useState('');
  const [confirmation, setConfirmation] = useState<Confirmation>();
  const [busy, setBusy] = useState(false);
  const fail = (error: unknown) => setError(error instanceof Error ? error.message : String(error));
  return (
    <NativeUiContext.Provider value={{ namespace, fail, confirm: setConfirmation }}>
      <div className={commonCss.page}>
        <div className={commonCss.flexGrow} style={{ minHeight: 0 }}>
          <SideNavigation page={location.pathname} />
          {connected ? (
            <Routes>
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
          <p>
            Namespace: {namespace}. Use a Kubernetes bearer token with access to this namespace. The
            token stays in memory and is cleared on reload.
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
        </DialogContent>
        <DialogActions>
          <Button
            disabled={!token.trim()}
            onClick={() => {
              setArgoToken(token);
              setToken('');
              setConnected(true);
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
export default function Router({ namespace }: { namespace: string }) {
  return (
    <HashRouter>
      <Workspace namespace={namespace} />
    </HashRouter>
  );
}
