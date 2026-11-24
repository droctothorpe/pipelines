// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router';
import { useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, Button, CircularProgress } from '@mui/material';
import { classes } from 'typestyle';
import { commonCss, padding } from 'src/Css';
import MD2Tabs from 'src/atoms/MD2Tabs';
import Separator from 'src/atoms/Separator';
import NativePage from 'src/components/NativePage';
import DetailsTable from 'src/components/DetailsTable';
import NativeTable from 'src/components/NativeTable';
import CompareTable from 'src/components/CompareTable';
import CollapseButtonSingle from 'src/components/CollapseButtonSingle';
import { NativeArtifactPreview } from 'src/components/viewers/NativeArtifactPreview';
import { NativeClassificationMetrics } from 'src/components/viewers/NativeClassificationMetrics';
import MarkdownViewer from 'src/components/viewers/MarkdownViewer';
import { NativeUiMetadata, SandboxedHtml } from 'src/components/viewers/NativeUiMetadata';
import { PlotType } from 'src/components/viewers/Viewer';
import { useNativeUi } from 'src/lib/NativeUiContext';
import { useInventory } from 'src/lib/NativeQueries';
import {
  getArgoMetadata,
  hasArgoMetadata,
  argoArtifactUrl,
  argoRequest,
  type ArgoWorkflow,
  type ArgoNode,
} from 'src/lib/Argo';
import {
  displayName,
  description,
  getUiRun,
  downloadArtifact,
  deleteNativeResource,
  EXPERIMENT,
  experimentHref,
  resourceId,
  resourceMatches,
  enc,
} from 'src/lib/NativeUi';
import { formatDateString } from 'src/lib/UiUtils';
import { isLegacyUiMetadata, readBoundedText } from 'src/lib/NativeUiMetadata';
import { setScheduleSuspended } from 'src/lib/ArgoResources';
import { scheduleTrigger } from 'src/lib/NativeScheduling';
import type { NativeResource } from 'src/lib/ArgoResources';
import { action, runColumns, runRows } from './NativePages';

export function NativeArtifactContent({
  run,
  node,
  port,
}: {
  run: ArgoWorkflow;
  node: ArgoNode;
  port: string;
}) {
  const { fail } = useNativeUi();
  const [tab, setTab] = useState(0);
  const metadata = useQuery({
    queryKey: ['native', run.metadata.namespace, run.metadata.uid, node.id, 'metadata'],
    queryFn: ({ signal }) => getArgoMetadata(run, node, signal),
    enabled: !!hasArgoMetadata(node),
  });
  const artifact = metadata.data?.artifacts.find((artifact) => artifact.port === port);
  const structured =
    artifact?.type.startsWith('system.Dataset@') || artifact?.type.startsWith('system.Model@');
  const preview = useQuery({
    queryKey: ['native', run.metadata.namespace, run.metadata.uid, node.id, port, 'preview'],
    enabled: tab === 1 && !!artifact && !structured && !artifact.type.includes('Metrics'),
    queryFn: async ({ signal }) => {
      const response = await argoRequest(argoArtifactUrl(run, node, port), signal);
      // Stream with a hard bound rather than downloading a large model into browser memory.
      return readBoundedText(response, 1024 * 1024);
    },
  });
  return (
    <div className={commonCss.page}>
      <MD2Tabs tabs={['Artifact Info', 'Visualization']} selectedTab={tab} onSwitch={setTab} />
      {metadata.error && <Alert severity='error'>{metadata.error.message}</Alert>}
      {tab === 0 && (
        <div className={classes(commonCss.scrollContainer, padding(20))}>
          <DetailsTable
            title='Artifact details'
            valueComponent={({ value }) => <>{value}</>}
            fields={[
              ['Name', port],
              ['Type', artifact?.type || 'Artifact'],
              ['URI', artifact?.uri || '-'],
              [
                'Producer run',
                artifact ? (
                  <Link
                    className={commonCss.link}
                    to={`/runs/details/${enc(artifact.producer.run)}`}
                  >
                    {artifact.producer.run}
                  </Link>
                ) : (
                  '-'
                ),
              ],
              ['Producer task', artifact?.producer.task || '-'],
            ]}
          />
          <Button onClick={() => downloadArtifact(run, node, port).catch(fail)}>Download</Button>
          {artifact && (
            <DetailsTable
              title='Metadata'
              fields={Object.entries(artifact.metadata).map(([name, value]) => [
                name,
                typeof value === 'string' ? value : JSON.stringify(value),
              ])}
            />
          )}
        </div>
      )}
      {tab === 1 && (
        <div className={classes(commonCss.page, padding(20))}>
          {artifact?.type.includes('ClassificationMetrics') ? (
            <NativeClassificationMetrics name={port} metadata={artifact.metadata} />
          ) : artifact?.type.includes('Metrics') ? (
            <DetailsTable
              title='Metrics'
              fields={Object.entries(artifact.metadata).map(([name, value]) => [
                name,
                typeof value === 'string' ? value : JSON.stringify(value),
              ])}
            />
          ) : structured && artifact ? (
            <NativeArtifactPreview run={run} node={node} artifact={artifact} />
          ) : preview.error ? (
            <Alert severity='error'>{preview.error.message}</Alert>
          ) : preview.isPending ? (
            <CircularProgress aria-label='Loading visualization' size={24} />
          ) : isLegacyUiMetadata(port) ? (
            <NativeUiMetadata
              run={run}
              node={node}
              artifacts={metadata.data?.artifacts || []}
              content={preview.data || ''}
            />
          ) : artifact?.type.includes('Markdown') ? (
            <MarkdownViewer
              configs={[{ type: PlotType.MARKDOWN, markdownContent: preview.data || '' }]}
            />
          ) : artifact?.type.includes('HTML') ? (
            <SandboxedHtml html={preview.data || ''} title='Artifact visualization' />
          ) : (
            <pre style={{ whiteSpace: 'pre-wrap', overflow: 'auto' }}>{preview.data}</pre>
          )}
        </div>
      )}
    </div>
  );
}
export function NativeArtifactDetails() {
  const { runId = '', nodeId = '', port = '' } = useParams();
  const { namespace } = useNativeUi();
  const run = useQuery({
    queryKey: ['native', namespace, 'run', runId],
    queryFn: ({ signal }) => getUiRun(namespace, runId, signal),
  });
  const node = run.data?.status?.nodes?.[nodeId];
  return (
    <NativePage
      title={port}
      breadcrumbs={[{ displayName: 'Artifacts', href: '/artifacts' }]}
      error={run.error}
    >
      <div className={classes(commonCss.page, padding(20, 't'))}>
        {run.data && node ? (
          <NativeArtifactContent run={run.data} node={node} port={port} />
        ) : (
          <div className={padding()}>
            {run.isPending ? 'Loading artifact…' : 'Artifact producer task not found.'}
          </div>
        )}
      </div>
    </NativePage>
  );
}
export function NativeCompare() {
  const [search] = useSearchParams();
  const { namespace } = useNativeUi();
  const client = useQueryClient();
  const ids = [...new Set((search.get('runlist') || '').split(',').filter(Boolean))];
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const results = useQueries({
    queries: (ids.length > 10 ? [] : ids).map((id) => ({
      queryKey: ['native', namespace, 'comparison', id],
      queryFn: async ({ signal }: { signal: AbortSignal }) => {
        const run = await getUiRun(namespace, id, signal);
        const metadata = await Promise.all(
          Object.values(run.status?.nodes || {})
            .filter(hasArgoMetadata)
            .map(async (node) => ({
              name: node.displayName,
              metadata: await getArgoMetadata(run, node, signal),
            })),
        );
        return {
          run,
          metrics: Object.fromEntries(
            metadata.flatMap((item) =>
              Object.entries(item.metadata.metrics).map(([key, value]) => [
                `${item.name} / ${key}`,
                String(value),
              ]),
            ),
          ),
        };
      },
    })),
  });
  const entries = results.flatMap((result) => (result.data ? [result.data] : []));
  const parameterKeys = [
    ...new Set(
      entries.flatMap(
        (entry) => entry.run.spec.arguments?.parameters?.map((parameter) => parameter.name) || [],
      ),
    ),
  ];
  const metricKeys = [...new Set(entries.flatMap((entry) => Object.keys(entry.metrics)))];
  return (
    <NativePage
      title='Compare runs'
      breadcrumbs={[{ displayName: 'Experiments', href: '/experiments' }]}
      error={
        ids.length > 10
          ? new Error('Compare up to ten runs at a time.')
          : results.find((result) => result.error)?.error
      }
      actions={{
        expand: action('Expand all', () => setCollapsed({})),
        collapse: action('Collapse all', () =>
          setCollapsed({ 'Run overview': true, Parameters: true, Metrics: true }),
        ),
        refresh: action(
          'Refresh',
          () => void client.invalidateQueries({ queryKey: ['native', namespace] }),
        ),
      }}
    >
      <div className={classes(commonCss.page, padding(20, 'lrt'))} style={{ overflow: 'auto' }}>
        {results.some((result) => result.isPending) && (
          <CircularProgress aria-label='Loading comparison' size={24} />
        )}
        {['Run overview', 'Parameters', 'Metrics'].map((section) => (
          <div key={section}>
            <CollapseButtonSingle
              sectionName={section}
              collapseSection={!!collapsed[section]}
              collapseSectionUpdate={(value) =>
                setCollapsed((current) => ({ ...current, [section]: value }))
              }
            />
            {!collapsed[section] &&
              (section === 'Run overview' ? (
                <NativeTable
                  rows={runRows(
                    entries.map((entry) => ({ ...entry.run, live: !entry.run.archived })),
                    [],
                    [],
                  )}
                  columns={runColumns}
                  filterLabel='Filter runs'
                />
              ) : (
                <CompareTable
                  xLabels={entries.map((entry) => displayName(entry.run))}
                  yLabels={section === 'Parameters' ? parameterKeys : metricKeys}
                  rows={(section === 'Parameters' ? parameterKeys : metricKeys).map((key) =>
                    entries.map((entry) =>
                      section === 'Parameters'
                        ? entry.run.spec.arguments?.parameters?.find(
                            (parameter) => parameter.name === key,
                          )?.value || '-'
                        : entry.metrics[key] || '-',
                    ),
                  )}
                />
              ))}
            <Separator orientation='vertical' />
          </div>
        ))}
      </div>
    </NativePage>
  );
}
const scheduleWindow = (schedule: NativeResource) => {
  const trigger = scheduleTrigger(schedule).trigger;
  return trigger?.cron_schedule || trigger?.periodic_schedule;
};

export function NativeScheduleDetails() {
  const { scheduleId = '' } = useParams();
  const { namespace, fail, confirm } = useNativeUi();
  const navigate = useNavigate();
  const inventory = useInventory();
  const schedule = inventory.schedules.data?.find((schedule) =>
    resourceMatches(schedule, scheduleId),
  );
  const experiment = inventory.experiments.data?.find((experiment) =>
    resourceMatches(experiment, schedule?.spec?.workflowMetadata?.labels?.[EXPERIMENT]),
  );
  const toggle = async (suspend: boolean) => {
    if (!schedule) return;
    try {
      await setScheduleSuspended(namespace, schedule, suspend);
      await inventory.schedules.refetch();
    } catch (error) {
      fail(error);
    }
  };
  return (
    <NativePage
      title={schedule ? displayName(schedule) : scheduleId || 'Recurring run'}
      breadcrumbs={
        experiment
          ? [
              { displayName: 'Experiments', href: '/experiments' },
              {
                displayName: displayName(experiment),
                href: experimentHref(resourceId(experiment)),
              },
            ]
          : [{ displayName: 'All runs', href: '/runs' }]
      }
      error={inventory.error}
      actions={{
        clone: action(
          'Clone recurring run',
          () => navigate(`/runs/new?cloneFromRecurringRun=${enc(scheduleId)}&recurring=1`),
          { id: 'cloneRecurringRunBtn', disabled: !schedule },
        ),
        refresh: action('Refresh', () => void inventory.schedules.refetch(), { id: 'refreshBtn' }),
        enable: action('Enable', () => void toggle(false), {
          disabled: !schedule || !schedule.spec?.suspend,
        }),
        disable: action('Disable', () => void toggle(true), {
          disabled: !schedule || !!schedule.spec?.suspend,
        }),
        delete: action(
          'Delete',
          () =>
            schedule &&
            confirm({
              title: 'Delete this recurring run config?',
              content: 'Already submitted runs and artifacts remain intact.',
              action: async () => {
                await deleteNativeResource(namespace, schedule);
                await inventory.schedules.refetch();
                navigate('/recurringruns');
              },
            }),
          { disabled: !schedule, id: 'deleteBtn' },
        ),
      }}
    >
      <div className={classes(commonCss.page, padding(20, 'lr'))}>
        {schedule && (
          <div className={commonCss.scrollContainer}>
            <div className={padding(20)}>
              <DetailsTable
                title='Recurring run details'
                fields={[
                  ['Description', description(schedule)],
                  ['Created at', formatDateString(schedule.metadata.creationTimestamp)],
                ]}
              />
              <DetailsTable
                title='Run triggers'
                fields={[
                  ['Enabled', schedule.spec?.suspend ? 'Disabled' : 'Enabled'],
                  [
                    'Trigger',
                    `${(schedule.spec?.schedules || []).join(', ')} (${schedule.spec?.timezone || 'UTC'})`,
                  ],
                  [
                    'Max. concurrent runs',
                    schedule.spec?.concurrencyPolicy === 'Forbid'
                      ? '1'
                      : schedule.spec?.concurrencyPolicy || 'Allow',
                  ],
                  ['Catchup', String(scheduleTrigger(schedule).catchup)],
                  ['Start time', formatDateString(scheduleWindow(schedule)?.start_time) ?? ''],
                  ['End time', formatDateString(scheduleWindow(schedule)?.end_time) ?? ''],
                ]}
              />
              <DetailsTable
                title='Run parameters'
                fields={(schedule.spec?.workflowSpec?.arguments?.parameters || []).map(
                  (parameter: { name: string; value?: string }) => [
                    parameter.name,
                    parameter.value || '',
                  ],
                )}
              />
            </div>
          </div>
        )}
      </div>
    </NativePage>
  );
}
