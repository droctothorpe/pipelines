// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, Button, CircularProgress } from '@mui/material';
import { classes } from 'typestyle';
import * as yaml from 'js-yaml';
import { commonCss, padding } from 'src/Css';
import MD2Tabs from 'src/atoms/MD2Tabs';
import NativePage from 'src/components/NativePage';
import SidePanel from 'src/components/SidePanel';
import DetailsTable from 'src/components/DetailsTable';
import LogViewer from 'src/components/LogViewer';
import Editor from 'src/components/Editor';
import DagCanvas from './v2/DagCanvas';
import RunTimeline from './v2/RunTimeline';
import { action } from './NativePages';
import { NativeArtifactContent } from './NativeInspectors';
import { useNativeUi } from 'src/lib/NativeUiContext';
import { getArgoMetadata, hasArgoMetadata, type ArgoWorkflow, type ArgoNode } from 'src/lib/Argo';
import { argoRunView } from 'src/lib/ArgoRunGraph';
import { workflowAction } from 'src/lib/ArgoResources';
import {
  archiveRun,
  getUiRun,
  displayName,
  runState,
  retryRun,
  taskLogs,
  enc,
  downloadArtifact,
} from 'src/lib/NativeUi';
import { formatDateString, hasFinishedV2 } from 'src/lib/UiUtils';
import type { LayerFlowElement } from 'src/lib/v2/FlowTypes';
import { getTaskNodeKey } from 'src/lib/v2/StaticFlow';
import type { TaskTimingView } from 'src/lib/NativeViewTypes';

export default function NativeRunDetails() {
  const { runId = '' } = useParams();
  const { namespace, fail, confirm } = useNativeUi();
  const navigate = useNavigate();
  const [search, setSearch] = useSearchParams();
  const client = useQueryClient();
  const [tab, setTab] = useState(search.get('tab') === 'timeline' ? 1 : 0);
  const [selection, setSelection] = useState<LayerFlowElement | null>(null);
  const workflow = useQuery({
    queryKey: ['native', namespace, 'run', runId],
    queryFn: ({ signal }) => getUiRun(namespace, runId, signal),
    refetchInterval: 5000,
  });
  const run = workflow.data;
  const graph = useMemo(() => (run ? argoRunView(run) : undefined), [run]);
  const selected =
    selection ||
    (search.get('task')
      ? {
          layers: ['root'],
          element: graph?.elements.find(
            (element) => element.id === getTaskNodeKey(search.get('task')!),
          )!,
        }
      : null);
  const details = selected?.element && graph?.describe(selected.element.id);
  const refresh = async () => {
    await client.invalidateQueries({ queryKey: ['native', namespace] });
  };
  const perform = async (operation: () => Promise<unknown>) => {
    try {
      await operation();
      await refresh();
    } catch (error) {
      fail(error);
    }
  };
  const terminal = !!run && hasFinishedV2(runState(run));
  const tasks: TaskTimingView[] = Object.values(run?.status?.nodes || {}).map((node) => ({
    task_id: node.id,
    name: node.name,
    display_name: node.displayName,
    type: ['DAG', 'TaskGroup', 'Retry', 'Steps', 'StepGroup'].includes(node.type)
      ? 'DAG'
      : node.type,
    state: node.memoizationStatus?.hit ? 'CACHED' : runState({ ...run!, status: { ...node } }),
    create_time: node.startedAt ? new Date(node.startedAt) : undefined,
    end_time: node.finishedAt ? new Date(node.finishedAt) : undefined,
  }));
  return (
    <NativePage
      title={run ? displayName(run) : runId}
      breadcrumbs={[{ displayName: 'Runs', href: '/runs' }]}
      error={workflow.error}
      actions={{
        clone: action('Clone run', () => navigate(`/runs/new?cloneFromRun=${enc(runId)}`), {
          id: 'cloneRunBtn',
          disabled: !run,
        }),
        retry: action('Retry', () => run && perform(() => retryRun(run)), {
          id: 'retryRunBtn',
          disabled: !run?.live || !['Failed', 'Error'].includes(run.status?.phase || ''),
          disabledTitle: 'Only failed live runs can be retried. Archived runs can be cloned.',
        }),
        terminate: action(
          'Terminate',
          () =>
            run &&
            confirm({
              title: 'Terminate this run?',
              content: 'Stop this workflow immediately, including its running tasks.',
              action: async () => {
                await workflowAction(run, 'terminate');
                await refresh();
              },
            }),
          { id: 'terminateRunBtn', disabled: !run?.live || terminal },
        ),
        archive: action(
          'Archive',
          () =>
            run &&
            confirm({
              title: 'Archive this run?',
              content:
                'Remove the live workflow and its pods after verifying the durable Argo archive. Artifacts remain available.',
              action: async () => {
                await archiveRun(run);
                await refresh();
                navigate('/archive/runs');
              },
            }),
          { id: 'archiveRunsBtn', disabled: !terminal || !run?.live },
        ),
        refresh: action('Refresh', () => refresh().catch(fail), { id: 'refreshBtn' }),
      }}
    >
      {!run ? (
        <div className={padding()}>
          {workflow.isPending ? (
            <CircularProgress aria-label='Loading run' size={24} />
          ) : (
            'Run data could not be loaded.'
          )}
        </div>
      ) : (
        <div className={classes(commonCss.page, padding(20, 't'))}>
          <MD2Tabs
            selectedTab={tab}
            tabs={['Graph', 'Timeline', 'Detail', 'Pipeline Spec']}
            onSwitch={(value) => {
              setTab(value);
              const next = new URLSearchParams(search);
              value === 1 ? next.set('tab', 'timeline') : next.delete('tab');
              setSearch(next, { replace: true });
            }}
          />
          {tab === 0 && graph && (
            <div className={commonCss.page} style={{ position: 'relative', overflow: 'hidden' }}>
              <DagCanvas
                graphId={`run:${runId}`}
                layers={['root']}
                elements={graph.elements}
                getSubDagElements={graph.resolve}
                selectedElement={selected}
                focusNodeId={search.get('task') ? getTaskNodeKey(search.get('task')!) : undefined}
                onElementClick={(_, selection) => setSelection(selection)}
              />
              <div className='z-20'>
                <SidePanel
                  isOpen={!!details?.node}
                  title={details?.artifact || details?.node?.displayName || ''}
                  defaultWidth='50%'
                  onClose={() => {
                    setSelection(null);
                    const next = new URLSearchParams(search);
                    next.delete('task');
                    setSearch(next, { replace: true });
                  }}
                >
                  {details?.node && (
                    <Task
                      key={`${details.node.id}/${details.artifact || ''}`}
                      run={run}
                      node={details.node}
                      artifactPort={details.artifact}
                      onRefresh={refresh}
                    />
                  )}
                </SidePanel>
              </div>
            </div>
          )}
          {tab === 1 && (
            <RunTimeline
              run={{
                state: runState(run),
                created_at: run.metadata.creationTimestamp
                  ? new Date(run.metadata.creationTimestamp)
                  : undefined,
                finished_at: run.status?.finishedAt ? new Date(run.status.finishedAt) : undefined,
              }}
              tasks={tasks}
              loading={false}
              onOpenTask={(id) => {
                setTab(0);
                setSelection(null);
                setSearch({ task: id });
              }}
            />
          )}
          {tab === 2 && (
            <div className={classes(commonCss.scrollContainer, padding())}>
              <DetailsTable
                title='Run details'
                fields={[
                  ['Name', displayName(run)],
                  ['Run ID', run.metadata.uid],
                  ['Status', runState(run)],
                  [
                    'Description',
                    run.metadata.annotations?.['pipelines.kubeflow.org/description'] || '',
                  ],
                  ['Created at', formatDateString(run.metadata.creationTimestamp)],
                  ['Finished at', formatDateString(run.status?.finishedAt)],
                  ['Namespace', namespace],
                  ['Workflow', run.metadata.name],
                  ['Pipeline Version', run.spec.workflowTemplateRef?.name || '-'],
                ]}
              />
              <DetailsTable
                title='Run parameters'
                fields={(run.spec.arguments?.parameters || []).map((parameter) => [
                  parameter.name,
                  parameter.value || '',
                ])}
              />
            </div>
          )}
          {tab === 3 && (
            <div className={commonCss.codeEditor} data-testid='spec-ir'>
              <Editor
                value={yaml.dump(run.status?.storedWorkflowTemplateSpec || run.spec)}
                mode='yaml'
                theme='github'
                readOnly
                width='100%'
                height='100%'
                setOptions={{ useWorker: false }}
              />
            </div>
          )}
        </div>
      )}
    </NativePage>
  );
}

function Task({
  run,
  node,
  artifactPort,
  onRefresh,
}: {
  run: ArgoWorkflow;
  node: ArgoNode;
  artifactPort?: string;
  onRefresh: () => Promise<void>;
}) {
  const { fail } = useNativeUi();
  const [tab, setTab] = useState(0);
  const metadata = useQuery({
    queryKey: ['native', run.metadata.namespace, run.metadata.uid, node.id, 'metadata'],
    queryFn: ({ signal }) => getArgoMetadata(run, node, signal),
    enabled: !!hasArgoMetadata(node),
  });
  const logs = useQuery({
    queryKey: ['native', run.metadata.namespace, run.metadata.uid, node.id, 'logs'],
    queryFn: ({ signal }) => taskLogs(run, node, signal),
    enabled: !artifactPort && tab === 2 && !node.memoizationStatus?.hit,
    retry: false,
  });
  if (artifactPort) return <NativeArtifactContent run={run} node={node} port={artifactPort} />;
  return (
    <div className={commonCss.page}>
      {node.message && (
        <Alert severity={node.phase === 'Failed' || node.phase === 'Error' ? 'error' : 'info'}>
          {node.message}
        </Alert>
      )}
      {node.type === 'Suspend' && node.phase === 'Running' && (
        <Alert
          severity='info'
          action={
            <Button
              onClick={async () => {
                try {
                  await workflowAction(run, 'resume');
                  await onRefresh();
                } catch (error) {
                  fail(error);
                }
              }}
            >
              Resume
            </Button>
          }
        >
          This run is waiting for approval.
        </Alert>
      )}
      <MD2Tabs
        tabs={['Input/Output', 'Task Details', 'Logs']}
        selectedTab={tab}
        onSwitch={setTab}
      />
      {tab === 0 && (
        <div className={classes(commonCss.scrollContainer, padding(20))}>
          {metadata.error && <Alert severity='error'>{metadata.error.message}</Alert>}
          <DetailsTable
            title='Input parameters'
            fields={(node.inputs?.parameters || [])
              .filter((parameter) => !/^(kfp-meta-|kfp-uri-|kfp-metadata$)/.test(parameter.name))
              .map((parameter) => [parameter.name, parameter.value || ''])}
          />
          <DetailsTable
            title='Output parameters'
            fields={(node.outputs?.parameters || [])
              .filter((parameter) => !/^(kfp-meta-|kfp-uri-|kfp-metadata$)/.test(parameter.name))
              .map((parameter) => [parameter.name, parameter.value || ''])}
          />
          <DetailsTable
            title='Input artifacts'
            valueComponent={({ value }) => <>{value}</>}
            fields={(metadata.data?.inputs || []).map((input) => [
              input.port,
              <Link className={commonCss.link} to={`/runs/details/${enc(input.producer.run)}`}>
                {input.uri}
              </Link>,
            ])}
          />
          <DetailsTable
            title='Output artifacts'
            valueComponent={({ value }) => <>{value}</>}
            fields={(metadata.data?.artifacts || []).map((artifact) => [
              artifact.port,
              <>
                <Link
                  className={commonCss.link}
                  to={`/artifacts/${enc(run.metadata.uid)}/${enc(node.id)}/${enc(artifact.port)}`}
                >
                  {artifact.type}
                </Link>
                <Button onClick={() => downloadArtifact(run, node, artifact.port).catch(fail)}>
                  Download
                </Button>
              </>,
            ])}
          />
          {!!Object.keys(metadata.data?.metrics || {}).length && (
            <DetailsTable
              title='Metrics'
              fields={Object.entries(metadata.data!.metrics).map(([name, value]) => [
                name,
                String(value),
              ])}
            />
          )}
        </div>
      )}
      {tab === 1 && (
        <div className={classes(commonCss.scrollContainer, padding(20))}>
          <DetailsTable
            title='Task details'
            fields={[
              ['Task ID', node.id],
              ['Task name', node.displayName],
              ['Task type', node.type],
              ['Status', node.memoizationStatus?.hit ? 'Cached' : node.phase || 'Pending'],
              ['Created At', formatDateString(node.startedAt)],
              ['Finished At', formatDateString(node.finishedAt)],
              ['Parent task ID', node.boundaryID || '-'],
              ['Message', node.message || '-'],
            ]}
          />
        </div>
      )}
      {tab === 2 && (
        <div className={commonCss.page}>
          {node.memoizationStatus?.hit ? (
            <Alert severity='info'>
              This task reused cached outputs and did not create a new pod. Its artifact lineage
              links to the original producer.
            </Alert>
          ) : (
            <>
              {logs.error && <Alert severity='error'>{logs.error.message}</Alert>}
              <div>
                <Button onClick={() => void logs.refetch()}>Refresh</Button>
              </div>
              {logs.isPending ? (
                <CircularProgress aria-label='Loading logs' size={24} />
              ) : (
                <LogViewer logLines={logs.data || []} />
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
