// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { useEffect, useMemo, useRef, useState } from 'react';
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
import { displayParameters } from 'src/lib/ArgoComponents';
import { workflowAction } from 'src/lib/ArgoResources';
import {
  archiveRun,
  restoreRun,
  isRunArchived,
  getUiRun,
  displayName,
  runState,
  retryRun,
  streamTaskLogs,
  type TaskLogSource,
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
  const selected = selection || (search.get('task') ? graph?.findTask(search.get('task')!) : null);
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
  const tasks: TaskTimingView[] = (graph?.nodes || []).map((node) => ({
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
          run && isRunArchived(run) ? 'Restore' : 'Archive',
          () =>
            run &&
            confirm({
              title: isRunArchived(run) ? 'Restore this run?' : 'Archive this run?',
              content:
                'Change where this run appears in the run list. Its workflow, logs and artifacts are preserved.',
              action: async () => {
                if (isRunArchived(run)) await restoreRun(run);
                else await archiveRun(run);
                await refresh();
                navigate(isRunArchived(run) ? '/runs' : '/archive/runs');
              },
            }),
          { id: 'archiveRunsBtn', disabled: !terminal },
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
  const logs = useTaskLogs(
    run,
    node,
    !artifactPort && tab === 2 && !node.memoizationStatus?.hit && node.type !== 'Importer',
  );
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
          <DetailsTable title='Input parameters' fields={displayParameters(run, node, 'inputs')} />
          <DetailsTable
            title='Output parameters'
            fields={displayParameters(run, node, 'outputs')}
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
          {node.type === 'Importer' ? (
            <Alert severity='info'>
              This importer resolves an artifact reference without an execution pod.
            </Alert>
          ) : node.memoizationStatus?.hit ? (
            <Alert severity='info'>
              This task reused cached outputs and did not create a new pod. Its artifact lineage
              links to the original producer.
            </Alert>
          ) : (
            <>
              {logs.error && <Alert severity='error'>{logs.error}</Alert>}
              <div className={commonCss.flex}>
                <Button onClick={logs.restart}>Refresh</Button>
                <span className={padding(10, 'l')} data-testid='log-status'>
                  {logs.source === 'live' && !logs.done
                    ? 'Streaming live logs'
                    : logs.source === 'live'
                      ? 'Live log stream ended'
                      : logs.source === 'archive'
                        ? 'Archived logs'
                        : ''}
                </span>
              </div>
              {!logs.source && !logs.done ? (
                <CircularProgress aria-label='Loading logs' size={24} />
              ) : (
                <LogViewer logLines={logs.lines} />
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

interface TaskLogState {
  lines: string[];
  source?: TaskLogSource;
  error?: string;
  done: boolean;
}

/**
 * Subscribe to a task's logs while the Logs tab is open. Running tasks stream
 * and follow; finished tasks load their archived logs. The run object refreshes
 * every few seconds, so the subscription is keyed by identity, not by object,
 * and is retried while the task is still running and no pod was available.
 */
function useTaskLogs(run: ArgoWorkflow, node: ArgoNode, enabled: boolean) {
  const latest = useRef({ run, node });
  latest.current = { run, node };
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<TaskLogState>({ lines: [], done: false });
  const key = `${run.metadata.uid}/${node.id}/${attempt}`;
  const finished = hasFinishedV2(node.phase) || !!run.status?.finishedAt;
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    setState({ lines: [], done: false });
    (async () => {
      try {
        for await (const update of streamTaskLogs(
          latest.current.run,
          latest.current.node,
          controller.signal,
        )) {
          if (controller.signal.aborted) return;
          setState((current) => ({
            ...current,
            source: update.source,
            lines: current.lines.concat(update.lines),
          }));
        }
        if (!controller.signal.aborted) setState((current) => ({ ...current, done: true }));
      } catch (error) {
        if (controller.signal.aborted) return;
        setState((current) => ({
          ...current,
          done: true,
          error: error instanceof Error ? error.message : String(error),
        }));
      }
    })();
    return () => controller.abort();
  }, [enabled, key]);
  useEffect(() => {
    if (!enabled || !state.error || finished) return;
    const timer = setTimeout(() => setAttempt((current) => current + 1), 3000);
    return () => clearTimeout(timer);
  }, [enabled, state.error, finished]);
  return { ...state, restart: () => setAttempt((current) => current + 1) };
}
