// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import { Alert, CircularProgress, IconButton, Menu, MenuItem, Tooltip } from '@mui/material';
import MoreVertIcon from '@mui/icons-material/MoreVert';
import AddIcon from '@mui/icons-material/Add';
import { classes } from 'typestyle';
import * as yaml from 'js-yaml';
import { commonCss, padding } from 'src/Css';
import MD2Tabs from 'src/atoms/MD2Tabs';
import NativePage from 'src/components/NativePage';
import NativeTable, { type NativeRow } from 'src/components/NativeTable';
import { type Column, ExpandState } from 'src/components/CustomTable';
import { type ToolbarActionConfig, type ToolbarActionMap } from 'src/components/Toolbar';
import DetailsTable from 'src/components/DetailsTable';
import Editor from 'src/components/Editor';
import PipelineGraph from 'src/components/graph/PipelineGraph';
import { PipelineVersionCard } from 'src/components/navigators/PipelineVersionCard';
import type { LayerFlowElement } from 'src/lib/v2/FlowTypes';
import { VERSION_NAME, VERSION_DESCRIPTION, CODE_SOURCE } from 'src/lib/NativeImport';
import { statusToIcon } from './StatusV2';
import { formatTaskElapsed } from 'src/lib/v2/RunTaskTiming';
import { formatDateString } from 'src/lib/UiUtils';
import { argoStaticView, type ArgoManifest } from 'src/lib/ArgoGraph';
import { useNativeUi } from 'src/lib/NativeUiContext';
import { useInventory, useArtifactInventory } from 'src/lib/NativeQueries';
import type { NativeResource } from 'src/lib/ArgoResources';
import {
  archiveRun,
  restoreRun,
  isRunArchived,
  resourceId,
  resourceMatches,
  deleteArchivedRun,
  deleteNativeResource,
  displayName,
  description,
  pipelineId,
  pipelineHref,
  experimentHref,
  runHref,
  runState,
  EXPERIMENT,
  enc,
  type UiRun,
} from 'src/lib/NativeUi';

export const action = (
  title: string,
  callback: () => void,
  options: Partial<ToolbarActionConfig> = {},
): ToolbarActionConfig => ({ title, tooltip: title, action: callback, ...options });
export const createAction = (
  title: string,
  callback: () => void,
  id: string,
  width: number,
  primary = true,
) =>
  action(title, callback, {
    id,
    icon: AddIcon,
    outlined: true,
    primary,
    style: { minWidth: width },
  });
const cell = ({ value }: { value?: React.ReactNode }) => <>{value}</>;
const link = (to: string, name: string) => (
  <Link className={commonCss.link} to={to} title={name}>
    {name}
  </Link>
);
export const runColumns: Column[] = [
  { label: 'Run name', flex: 1.5, sortKey: 'name', customRenderer: cell },
  { label: 'Status', flex: 0.5, customRenderer: cell },
  { label: 'Duration', flex: 0.5 },
  { label: 'Experiment', flex: 1, customRenderer: cell },
  { label: 'Pipeline Version', flex: 1, customRenderer: cell },
  { label: 'Recurring Run', flex: 0.5, customRenderer: cell },
  { label: 'Start time', flex: 1, sortKey: 'created_at' },
];
export function runRows(
  runs: UiRun[],
  versions: NativeResource[],
  experiments: NativeResource[],
): NativeRow[] {
  return runs.map((run) => {
    const version = versions.find((version) =>
      resourceMatches(
        version,
        run.metadata.labels?.['pipelines.kubeflow.org/version-id'] ||
          run.spec.workflowTemplateRef?.name ||
          run.metadata.annotations?.['pipelines.kubeflow.org/workflow-template'],
      ),
    );
    const experimentName = run.metadata.labels?.[EXPERIMENT];
    const experiment = experiments.find((exp) => resourceMatches(exp, experimentName));
    const started = run.status?.startedAt || run.metadata.creationTimestamp;
    const end = run.status?.finishedAt;
    const elapsed = started
      ? (end ? Date.parse(end) : run.status?.phase === 'Running' ? Date.now() : NaN) -
        Date.parse(started)
      : NaN;
    const schedule = run.metadata.labels?.['workflows.argoproj.io/cron-workflow'];
    return {
      id: run.metadata.uid,
      name: displayName(run),
      created: run.metadata.creationTimestamp,
      otherFields: [
        link(runHref(run), displayName(run)),
        statusToIcon(
          runState(run),
          started ? new Date(started) : undefined,
          end ? new Date(end) : undefined,
          run.status?.message,
        ),
        formatTaskElapsed(elapsed),
        experimentName
          ? link(
              experimentHref(experimentName),
              experiment ? displayName(experiment) : experimentName,
            )
          : '-',
        version
          ? link(
              pipelineHref(version),
              version.metadata.annotations?.[VERSION_NAME] || version.metadata.name,
            )
          : run.spec.workflowTemplateRef?.name || '-',
        schedule ? link(`/recurringrun/details/${enc(schedule)}`, schedule) : '-',
        formatDateString(started),
      ],
    };
  });
}
const pipelineColumns: Column[] = [
  { label: 'Pipeline name', flex: 1, sortKey: 'name', customRenderer: cell },
  { label: 'Description', flex: 3 },
  { label: 'Uploaded on', flex: 1, sortKey: 'created_at' },
];
const versionColumns: Column[] = [
  { label: 'Version name', flex: 1, customRenderer: cell },
  { label: 'Description', flex: 3 },
  { label: 'Uploaded on', flex: 1, sortKey: 'created_at' },
];
function versionRows(versions: NativeResource[]): NativeRow[] {
  return versions.map((version) => ({
    id: version.metadata.name,
    name: version.metadata.name,
    created: version.metadata.creationTimestamp,
    otherFields: [
      link(
        pipelineHref(version),
        version.metadata.annotations?.[VERSION_NAME] || version.metadata.name,
      ),
      description(version),
      formatDateString(version.metadata.creationTimestamp),
    ],
  }));
}

function PipelineMenu() {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  return (
    <>
      <Tooltip title='More actions'>
        <IconButton
          id='pipeline-more-actions'
          aria-label='More actions'
          aria-haspopup='menu'
          onClick={(event) => setAnchor(event.currentTarget)}
        >
          <MoreVertIcon />
        </IconButton>
      </Tooltip>
      <Menu
        id='pipeline-more-actions-menu'
        anchorEl={anchor}
        open={!!anchor}
        onClose={() => setAnchor(null)}
      >
        <Tooltip title='Namespace metadata transfer is not available in native execution.'>
          <span>
            <MenuItem disabled>Import / export namespace data…</MenuItem>
          </span>
        </Tooltip>
      </Menu>
    </>
  );
}

export function NativeListPage({
  kind,
  archived = false,
  shared = false,
}: {
  kind: 'pipelines' | 'experiments' | 'runs' | 'schedules' | 'artifacts';
  archived?: boolean;
  shared?: boolean;
}) {
  const { namespace, fail, confirm } = useNativeUi();
  const navigate = useNavigate();
  const client = useQueryClient();
  const inventory = useInventory();
  const artifacts = useArtifactInventory(kind === 'artifacts');
  const [selected, setSelected] = useState<string[]>([]);
  const [expanded, setExpanded] = useState<string[]>([]);
  const versions = inventory.versions.data || [],
    pipelines = inventory.pipelines.data || [],
    experiments = inventory.experiments.data || [],
    runs = inventory.runs.data || [],
    schedules = inventory.schedules.data || [];
  const refresh = async () => {
    await client.invalidateQueries({ queryKey: ['native', namespace] });
  };
  // Argo Server answers list requests from an informer that can lag a deletion
  // by a moment, so a single refetch may still show what was just removed.
  // Refetch until the removed identities are gone, bounded.
  const gone = (ids: string[]) =>
    !(['pipelines', 'versions', 'experiments', 'runs', 'schedules'] as const).some((kind) =>
      (
        (client.getQueryData(['native', namespace, kind]) as NativeResource[] | undefined) || []
      ).some((entry) => ids.includes(entry.metadata.uid || '') || ids.includes(resourceId(entry))),
    );
  const complete = async (operation: () => Promise<unknown>, removed: string[] = []) => {
    await operation();
    setSelected([]);
    await refresh();
    for (let attempt = 0; attempt < 8 && removed.length && !gone(removed); attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      await refresh();
    }
  };
  const groups = new Map<string, NativeResource[]>();
  for (const version of versions)
    groups.set(pipelineId(version), [...(groups.get(pipelineId(version)) || []), version]);
  for (const pipeline of pipelines)
    if (!groups.has(resourceId(pipeline))) groups.set(resourceId(pipeline), []);
  const title = {
    pipelines: 'Pipelines',
    experiments: 'Experiments',
    runs: 'Runs',
    schedules: 'Recurring Runs',
    artifacts: 'Artifacts',
  }[kind];
  let columns: Column[],
    rows: NativeRow[],
    actions: ToolbarActionMap = {};
  const selectedRuns = runs.filter((run) => selected.includes(run.metadata.uid));
  const none = !selected.length;
  const confirmRuns = (deleting: boolean) =>
    confirm({
      title: `${deleting ? 'Delete' : 'Archive'} ${selectedRuns.length} run(s)?`,
      content: deleting
        ? 'Permanently remove these runs from the Argo archive. Stored artifacts are not deleted.'
        : 'Move these runs to Archived. Their workflows, logs and artifacts are preserved.',
      action: () =>
        complete(
          () => Promise.all(selectedRuns.map(deleting ? deleteArchivedRun : archiveRun)),
          deleting ? selectedRuns.map((run) => run.metadata.uid) : [],
        ),
    });
  if (kind === 'pipelines') {
    columns = pipelineColumns;
    rows = [...groups]
      .filter(
        ([id]) =>
          !shared ||
          pipelines.some(
            (pipeline) => resourceId(pipeline) === id && pipeline.data?.shared === 'true',
          ),
      )
      .map(([id, entries]) => {
        const version = [...entries].sort((a, b) =>
          (b.metadata.creationTimestamp || '').localeCompare(a.metadata.creationTimestamp || ''),
        )[0];
        const record = pipelines.find((pipeline) => resourceId(pipeline) === id) || version;
        return {
          id,
          name: displayName(record),
          created: record.metadata.creationTimestamp,
          expandState: expanded.includes(id) ? ExpandState.EXPANDED : ExpandState.COLLAPSED,
          otherFields: [
            link(
              version ? pipelineHref(version) : `/pipelines/details/${enc(id)}`,
              displayName(record),
            ),
            description(record),
            formatDateString(record.metadata.creationTimestamp),
          ],
        };
      });
    actions = {
      upload: createAction(
        'Upload pipeline',
        () => navigate('/pipeline_versions/new'),
        'createPipelineVersionBtn',
        160,
        false,
      ),
      refresh: action('Refresh', () => refresh().catch(fail), { id: 'refreshBtn' }),
      delete: action(
        'Delete',
        () =>
          confirm({
            title: `Delete ${selected.length} pipeline(s)?`,
            content:
              'Delete all selected WorkflowTemplate versions. Existing runs, archives, and artifacts will not be deleted.',
            action: () =>
              complete(
                () =>
                  Promise.all(
                    selected.map(async (id) => {
                      await Promise.all(
                        (groups.get(id) || []).map((version) =>
                          deleteNativeResource(namespace, version),
                        ),
                      );
                      const record = pipelines.find((pipeline) => resourceId(pipeline) === id);
                      if (record) await deleteNativeResource(namespace, record);
                    }),
                  ),
                selected.flatMap((id) => [
                  id,
                  ...(groups.get(id) || []).map((version) => version.metadata.uid || ''),
                ]),
              ),
          }),
        {
          id: 'deletePipelinesBtn',
          disabled: none,
          disabledTitle: 'Select at least one pipeline to delete',
        },
      ),
    };
  } else if (kind === 'runs') {
    columns = runColumns;
    rows = runRows(
      runs.filter((run) => isRunArchived(run) === archived),
      versions,
      experiments,
    );
    actions = archived
      ? {
          restore: action(
            'Restore',
            () => complete(() => Promise.all(selectedRuns.map(restoreRun))).catch(fail),
            { disabled: none, id: 'restoreBtn' },
          ),
          delete: action('Delete', () => confirmRuns(true), {
            disabled: none,
            id: 'deleteRunsBtn',
          }),
        }
      : {
          create: createAction('Create run', () => navigate('/runs/new'), 'createNewRunBtn', 130),
          compare: action(
            'Compare runs',
            () => navigate(`/compare?runlist=${selected.map(enc).join(',')}`),
            {
              disabled: selected.length < 2 || selected.length > 5,
              style: { minWidth: 125 },
              id: 'compareBtn',
              disabledTitle: 'Select at least two runs to compare',
            },
          ),
          clone: action('Clone run', () => navigate(`/runs/new?cloneFromRun=${enc(selected[0])}`), {
            disabled: selected.length !== 1,
            id: 'cloneBtn',
            style: { minWidth: 100 },
            disabledTitle: 'Select one run to clone',
          }),
          archive: action('Archive', () => confirmRuns(false), {
            disabled:
              none ||
              selectedRuns.some(
                (run) => !['Succeeded', 'Failed', 'Error'].includes(run.status?.phase || ''),
              ),
            id: 'archiveRunsBtn',
            disabledTitle: 'Select completed runs to archive',
          }),
        };
  } else if (kind === 'experiments') {
    columns = [
      { label: 'Experiment name', flex: 1, sortKey: 'name', customRenderer: cell },
      { label: 'Description', flex: 2 },
      ...(!archived
        ? [{ label: 'Last 5 runs', flex: 1, sortKey: 'last_run_created_at', customRenderer: cell }]
        : []),
    ];
    rows = experiments
      .filter((exp) => (exp.data?.storageState === 'ARCHIVED') === archived)
      .map((exp) => ({
        id: resourceId(exp),
        name: displayName(exp),
        created: exp.metadata.creationTimestamp,
        sortValues: {
          last_run_created_at:
            runs
              .filter((run) => resourceMatches(exp, run.metadata.labels?.[EXPERIMENT]))
              .map((run) => run.metadata.creationTimestamp || '')
              .sort()
              .at(-1) || '',
        },
        expandState: expanded.includes(resourceId(exp))
          ? ExpandState.EXPANDED
          : ExpandState.COLLAPSED,
        otherFields: [
          link(experimentHref(resourceId(exp)), displayName(exp)),
          description(exp),
          expanded.includes(resourceId(exp)) ? null : (
            <div className={commonCss.flex}>
              {runs
                .filter(
                  (run) =>
                    !isRunArchived(run) && resourceMatches(exp, run.metadata.labels?.[EXPERIMENT]),
                )
                .sort((a, b) =>
                  (b.metadata.creationTimestamp || '').localeCompare(
                    a.metadata.creationTimestamp || '',
                  ),
                )
                .slice(0, 5)
                .map((run) => (
                  <Link
                    key={run.metadata.uid}
                    to={runHref(run)}
                    style={{ marginRight: 8 }}
                    title={displayName(run)}
                  >
                    {statusToIcon(runState(run))}
                  </Link>
                ))}
            </div>
          ),
        ].slice(0, archived ? 2 : 3),
      }));
    actions = archived
      ? {}
      : {
          create: createAction(
            'Create experiment',
            () => navigate('/experiments/new'),
            'newExperimentBtn',
            185,
          ),
          compare: action(
            'Compare runs',
            () => navigate(`/compare?runlist=${selected.map(enc).join(',')}`),
            {
              disabled: selected.length < 2 || selected.length > 5,
              style: { minWidth: 125 },
              id: 'compareBtn',
            },
          ),
          clone: action('Clone run', () => navigate(`/runs/new?cloneFromRun=${enc(selected[0])}`), {
            disabled: selected.length !== 1,
            style: { minWidth: 100 },
            id: 'cloneBtn',
          }),
          archive: action('Archive', () => confirmRuns(false), {
            disabled:
              none ||
              selectedRuns.some(
                (run) => !['Succeeded', 'Failed', 'Error'].includes(run.status?.phase || ''),
              ),
            id: 'archiveRunsBtn',
          }),
        };
  } else if (kind === 'schedules') {
    columns = [
      { label: 'Recurring Run Name', flex: 1.5, sortKey: 'name', customRenderer: cell },
      { label: 'Status', flex: 0.5 },
      { label: 'Trigger', flex: 1 },
      { label: 'Start Time', flex: 1 },
      { label: 'End Time', flex: 1 },
      { label: 'Schedule Status', flex: 0.7 },
      { label: 'Experiment', flex: 1, customRenderer: cell },
      { label: 'Created at', flex: 1, sortKey: 'created_at' },
    ];
    rows = schedules.map((schedule) => ({
      id: schedule.metadata.name,
      name: displayName(schedule),
      created: schedule.metadata.creationTimestamp,
      otherFields: [
        link(`/recurringrun/details/${enc(schedule.metadata.name)}`, displayName(schedule)),
        schedule.spec?.suspend ? 'Disabled' : 'Enabled',
        (schedule.spec?.schedules || []).join(', '),
        '-',
        '-',
        schedule.spec?.suspend ? 'Suspended' : 'Scheduled',
        schedule.spec?.workflowMetadata?.labels?.[EXPERIMENT] || '-',
        formatDateString(schedule.metadata.creationTimestamp),
      ],
    }));
    actions = {
      create: createAction(
        'Create recurring run',
        () => navigate('/runs/new?recurring=1'),
        'createNewRecurringRunBtn',
        195,
      ),
    };
  } else {
    columns = [
      { label: 'Name', flex: 2, sortKey: 'name', customRenderer: cell },
      { label: 'ID', flex: 1.5, sortKey: 'artifact_id' },
      { label: 'Type', flex: 2, sortKey: 'type' },
      { label: 'URI', flex: 1.8, sortKey: 'uri' },
      { label: 'Namespace', flex: 1.2, sortKey: 'namespace' },
      { label: 'Created at', flex: 1.5, sortKey: 'created_at' },
    ];
    rows = (artifacts.data?.items || []).map((entry) => ({
      id: entry.id,
      name: entry.artifact.port,
      sortValues: {
        artifact_id: entry.id,
        type: entry.artifact.type,
        uri: entry.artifact.uri,
        namespace,
      },
      created: entry.run.metadata.creationTimestamp,
      otherFields: [
        link(`/artifacts/${entry.id.split('/').map(enc).join('/')}`, entry.artifact.port),
        entry.id,
        entry.artifact.type,
        entry.artifact.uri,
        namespace,
        formatDateString(entry.run.metadata.creationTimestamp),
      ],
    }));
  }
  if (kind !== 'artifacts')
    actions.refresh = action('Refresh', () => refresh().catch(fail), {
      id: 'refreshBtn',
      tooltip: 'Refresh the list',
    });
  const tabs = kind === 'runs' || kind === 'experiments';
  return (
    <NativePage
      title={title}
      actions={actions}
      error={inventory.error || (kind === 'artifacts' && artifacts.error)}
    >
      <div className={classes(commonCss.page, tabs && padding(20, 't'))}>
        {tabs && (
          <MD2Tabs
            tabs={['Active', 'Archived']}
            selectedTab={archived ? 1 : 0}
            onSwitch={(tab) => {
              setSelected([]);
              navigate(`${tab ? '/archive' : ''}/${kind}`);
            }}
          />
        )}

        {kind === 'artifacts' && artifacts.data?.truncated && (
          <Alert severity='info'>
            This list covers the 50 most recent runs. Older artifacts remain accessible from their
            run.
          </Alert>
        )}
        <div className={classes(commonCss.page, padding(20, 'lr'))}>
          {inventory.pending || (kind === 'artifacts' && artifacts.isPending) ? (
            <CircularProgress aria-label='Loading' size={24} />
          ) : (
            <NativeTable
              key={`${kind}-${archived}-${shared}`}
              rows={rows}
              columns={columns}
              selected={selected}
              select={kind === 'artifacts' || kind === 'experiments' ? undefined : setSelected}
              emptyMessage={
                kind === 'pipelines'
                  ? 'No pipelines found. Click "Upload pipeline" to start.'
                  : kind === 'experiments'
                    ? archived
                      ? 'No archived experiments found.'
                      : 'No experiments found. Click "Create experiment" to start.'
                    : kind === 'runs'
                      ? 'No available runs found.'
                      : kind === 'schedules'
                        ? 'No available recurring runs found.'
                        : 'No artifacts found.'
              }
              filterLabel={
                kind === 'artifacts'
                  ? 'Filter'
                  : `Filter ${kind === 'schedules' ? 'recurring runs' : kind}`
              }
              filterActions={kind === 'pipelines' ? <PipelineMenu /> : undefined}
              toggle={
                kind === 'pipelines' || kind === 'experiments'
                  ? (id) =>
                      setExpanded((current) =>
                        current.includes(id)
                          ? current.filter((value) => value !== id)
                          : [...current, id],
                      )
                  : undefined
              }
              expand={(row) =>
                kind === 'pipelines' ? (
                  <NativeTable
                    rows={versionRows(groups.get(row.id) || [])}
                    columns={versionColumns}
                    filterLabel='Filter pipeline versions'
                  />
                ) : (
                  <NativeTable
                    rows={runRows(
                      runs.filter(
                        (run) =>
                          isRunArchived(run) === archived &&
                          resourceMatches(
                            experiments.find((exp) => resourceId(exp) === row.id)!,
                            run.metadata.labels?.[EXPERIMENT],
                          ),
                      ),
                      versions,
                      experiments,
                    ).map((run) => ({
                      ...run,
                      otherFields: run.otherFields.filter((_, index) => index !== 3),
                    }))}
                    columns={runColumns.filter((column) => column.label !== 'Experiment')}
                    selected={archived ? [] : selected}
                    select={archived ? undefined : setSelected}
                    filterLabel='Filter runs'
                    noFilterBox
                    disableSorting
                    emptyMessage={archived ? 'No archived runs found.' : 'No available runs found.'}
                  />
                )
              }
            />
          )}
        </div>
      </div>
    </NativePage>
  );
}

export function NativePipelineDetails() {
  const { pipelineId: id, versionId } = useParams();
  const { namespace, confirm } = useNativeUi();
  const navigate = useNavigate();
  const inventory = useInventory();
  const [tab, setTab] = useState(0);
  const [selection, setSelection] = useState<LayerFlowElement | null>(null);
  const versions = (inventory.versions.data || [])
    .filter((version) => pipelineId(version) === id)
    .sort((a, b) =>
      (b.metadata.creationTimestamp || '').localeCompare(a.metadata.creationTimestamp || ''),
    );
  const version = versionId
    ? versions.find((version) => resourceMatches(version, versionId))
    : versions[0];
  let view: ReturnType<typeof argoStaticView> | undefined, graphError: unknown;
  try {
    if (version) view = argoStaticView(version as ArgoManifest);
  } catch (error) {
    graphError = error;
  }
  const summaries = versions.map((version) => ({
    pipeline_version_id: version.metadata.name,
    display_name: version.metadata.annotations?.[VERSION_NAME] || version.metadata.name,
    created_at: version.metadata.creationTimestamp,
    description: version.metadata.annotations?.[VERSION_DESCRIPTION] || description(version),
    code_source_url: version.metadata.annotations?.[CODE_SOURCE],
  }));
  const selectedSummary = summaries.find(
    (summary) => summary.pipeline_version_id === version?.metadata.name,
  );
  return (
    <NativePage
      title={
        version ? `${displayName(version)} (${selectedSummary?.display_name})` : id || 'Pipeline'
      }
      breadcrumbs={[{ displayName: 'Pipelines', href: '/pipelines' }]}
      error={inventory.versions.error || graphError}
      actions={{
        run: {
          ...createAction(
            'Create run',
            () => version && navigate(`/runs/new?pipelineVersionId=${enc(version.metadata.name)}`),
            'createNewRunBtn',
            130,
          ),
          disabled: !version,
        },
        upload: createAction(
          'Upload version',
          () => navigate(`/pipeline_versions/new?pipelineId=${enc(id!)}`),
          'createPipelineVersionBtn',
          160,
          false,
        ),
        experiment: createAction(
          'Create experiment',
          () => navigate(`/experiments/new?pipelineId=${enc(id!)}`),
          'newExperimentBtn',
          185,
        ),
        delete: action(
          'Delete',
          () =>
            version &&
            confirm({
              title: 'Delete this pipeline version?',
              content:
                'Existing runs and artifacts remain intact. This version will no longer be available for new runs.',
              action: async () => {
                await deleteNativeResource(namespace, version);
                await inventory.versions.refetch();
                navigate('/pipelines');
              },
            }),
          { id: 'deleteBtn', disabled: !version },
        ),
      }}
    >
      <div className={classes(commonCss.page, padding(20, 't'))}>
        <MD2Tabs tabs={['Graph', 'Pipeline Spec']} selectedTab={tab} onSwitch={setTab} />
        {tab === 0 &&
          (view && version ? (
            <PipelineGraph
              graphId={`pipeline-version:${version.metadata.name}`}
              elements={view.elements}
              resolveLayers={view.resolve}
              selection={selection}
              onSelectionChange={setSelection}
              renderDetails={(selected) => {
                const details = view!.describe(selected.layers, selected.element.id);
                return (
                  <DetailsTable
                    title='Task details'
                    fields={[
                      ['Name', details.task?.name || ''],
                      ['Image', details.template?.container?.image || '-'],
                      ['Command', JSON.stringify(details.template?.container?.command || [])],
                      ['Arguments', JSON.stringify(details.template?.container?.args || [])],
                      ['Inputs', JSON.stringify(details.template?.inputs || {})],
                      ['Outputs', JSON.stringify(details.template?.outputs || {})],
                    ]}
                  />
                );
              }}
            >
              <PipelineVersionCard
                pipeline={{
                  pipeline_id: id!,
                  description: description(version),
                  created_at: version.metadata.creationTimestamp,
                }}
                selectedVersion={selectedSummary}
                versions={summaries}
                handleVersionSelected={async (selected) => {
                  setSelection(null);
                  navigate(`/pipelines/details/${enc(id!)}/version/${enc(selected)}`);
                }}
              />
            </PipelineGraph>
          ) : (
            <div className={padding()}>
              {inventory.versions.isPending
                ? 'Loading pipeline…'
                : 'The selected pipeline version is unavailable.'}
            </div>
          ))}
        {tab === 1 && version && (
          <div className={commonCss.codeEditor} data-testid='spec-ir'>
            <Editor
              value={yaml.dump(version)}
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
    </NativePage>
  );
}
export { default as NativeExperimentDetails } from './NativeExperimentDetails';
export { NativeNewExperiment, NativeNewRun } from './NativeForms';
export { NativeCompare, NativeArtifactDetails, NativeScheduleDetails } from './NativeInspectors';
