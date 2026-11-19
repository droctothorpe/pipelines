// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import {
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Paper,
  Tooltip,
} from '@mui/material';
import PopOutIcon from '@mui/icons-material/OpenInNew';
import { classes, stylesheet } from 'typestyle';
import { color, commonCss, padding } from 'src/Css';
import NativePage from 'src/components/NativePage';
import NativeTable from 'src/components/NativeTable';
import Toolbar from 'src/components/Toolbar';
import MD2Tabs from 'src/atoms/MD2Tabs';
import { useInventory } from 'src/lib/NativeQueries';
import { useNativeUi } from 'src/lib/NativeUiContext';
import { EXPERIMENT, displayName, description, enc } from 'src/lib/NativeUi';
import { action, createAction, runColumns, runRows } from './NativePages';

// The original ExperimentDetails card styles and two-level toolbar layout.
const css = stylesheet({
  card: {
    border: '1px solid #ddd',
    borderRadius: 8,
    height: 70,
    marginRight: 24,
    padding: '12px 20px 13px 24px',
  },
  cardActive: { border: `1px solid ${color.success}` },
  cardBtn: {
    $nest: { '&:hover': { backgroundColor: 'initial' } },
    color: color.theme,
    fontSize: 12,
    minHeight: 16,
    paddingLeft: 0,
    marginRight: 0,
  },
  cardContent: { color: color.secondaryText, fontSize: 16, lineHeight: '28px' },
  cardRow: {
    borderBottom: `1px solid ${color.lightGrey}`,
    display: 'flex',
    flexFlow: 'row',
    minHeight: 120,
  },
  cardTitle: {
    color: color.strong,
    display: 'flex',
    fontSize: 12,
    fontWeight: 'bold',
    height: 20,
    justifyContent: 'space-between',
    marginBottom: 6,
  },
  popOutIcon: { color: color.secondaryText, margin: -2, minWidth: 0, padding: 3 },
  recurringRunsActive: { color: '#0d652d' },
  recurringRunsCard: { width: 270 },
  recurringRunsDialog: { minWidth: 600 },
  runStatsCard: { width: 270 },
});
export default function NativeExperimentDetails() {
  const { experimentId = '' } = useParams();
  const { fail } = useNativeUi();
  const navigate = useNavigate();
  const inventory = useInventory();
  const [tab, setTab] = useState(0),
    [selected, setSelected] = useState<string[]>([]);
  const [manager, setManager] = useState(false),
    [readMore, setReadMore] = useState(false);
  const experiment = inventory.experiments.data?.find((exp) => exp.metadata.name === experimentId);
  const schedules = (inventory.schedules.data || []).filter(
    (schedule) => schedule.spec?.workflowMetadata?.labels?.[EXPERIMENT] === experimentId,
  );
  const active = schedules.filter((schedule) => !schedule.spec?.suspend).length;
  const text = experiment ? description(experiment) : '';
  const rows = runRows(
    (inventory.runs.data || []).filter(
      (run) =>
        run.metadata.labels?.[EXPERIMENT] === experimentId && (tab === 0 ? run.live : !run.live),
    ),
    inventory.versions.data || [],
    inventory.experiments.data || [],
  ).map((row) => ({ ...row, otherFields: row.otherFields.filter((_, index) => index !== 3) }));
  return (
    <NativePage
      title={experiment ? displayName(experiment) : experimentId}
      breadcrumbs={[{ displayName: 'Experiments', href: '/experiments' }]}
      error={inventory.error}
      actions={{
        refresh: action('Refresh', () => inventory.runs.refetch().catch(fail), {
          id: 'refreshBtn',
        }),
        archive: action('Archive', () => {}, {
          id: 'archiveBtn',
          disabled: true,
          disabledTitle:
            'Native experiment ConfigMaps do not support archival. Runs can be archived individually.',
        }),
      }}
    >
      <div className={classes(commonCss.page, padding(20, 'lrt'))}>
        {experiment && (
          <div className={commonCss.page}>
            <div className={css.cardRow}>
              <Paper
                id='recurringRunsCard'
                className={classes(css.card, css.recurringRunsCard, !!active && css.cardActive)}
                elevation={0}
              >
                <div>
                  <div className={css.cardTitle}>
                    <span>Recurring run configs</span>
                    <Button
                      className={css.cardBtn}
                      id='manageExperimentRecurringRunsBtn'
                      disableRipple
                      onClick={() => setManager(true)}
                    >
                      Manage
                    </Button>
                  </div>
                  <div className={classes(css.cardContent, !!active && css.recurringRunsActive)}>
                    {active} active
                  </div>
                </div>
              </Paper>
              <Paper
                id='experimentDescriptionCard'
                className={classes(css.card, css.runStatsCard)}
                elevation={0}
              >
                <div className={css.cardTitle}>
                  <span>Experiment description</span>
                  <Button
                    id='expandExperimentDescriptionBtn'
                    onClick={() => setReadMore(true)}
                    className={classes(css.popOutIcon, 'popOutButton')}
                  >
                    <Tooltip title='Read more'>
                      <PopOutIcon style={{ fontSize: 18 }} />
                    </Tooltip>
                  </Button>
                </div>
                {text
                  .split('\n')
                  .slice(0, 2)
                  .map((line, i) => (
                    <div
                      key={i}
                      style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                    >
                      {line}
                    </div>
                  ))}
                {text.split('\n').length > 2 ? '...' : ''}
              </Paper>
            </div>
            <Toolbar
              pageTitle='Runs'
              topLevelToolbar={false}
              breadcrumbs={[]}
              actions={{
                create: createAction(
                  'Create run',
                  () => navigate(`/runs/new?experimentId=${enc(experimentId)}`),
                  'createNewRunBtn',
                  130,
                ),
                recurring: createAction(
                  'Create recurring run',
                  () => navigate(`/runs/new?experimentId=${enc(experimentId)}&recurring=1`),
                  'createNewRecurringRunBtn',
                  195,
                  false,
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
                clone: action(
                  'Clone run',
                  () => navigate(`/runs/new?cloneFromRun=${enc(selected[0])}`),
                  { disabled: selected.length !== 1, style: { minWidth: 100 }, id: 'cloneBtn' },
                ),
              }}
            />
            <div className={classes(commonCss.page, padding(20, 't'))}>
              <MD2Tabs
                tabs={['Active', 'Archived']}
                selectedTab={tab}
                onSwitch={(value) => {
                  setTab(value);
                  setSelected([]);
                }}
              />
              <NativeTable
                rows={rows}
                columns={runColumns.filter((column) => column.label !== 'Experiment')}
                selected={selected}
                select={setSelected}
                filterLabel='Filter runs'
                emptyMessage='No available runs found.'
              />
            </div>
          </div>
        )}
      </div>
      <Dialog open={readMore} onClose={() => setReadMore(false)}>
        <DialogTitle>Experiment description</DialogTitle>
        <DialogContent className={commonCss.prewrap}>{text}</DialogContent>
        <DialogActions>
          <Button onClick={() => setReadMore(false)}>OK</Button>
        </DialogActions>
      </Dialog>
      <Dialog
        open={manager}
        onClose={() => setManager(false)}
        classes={{ paper: css.recurringRunsDialog }}
      >
        <DialogTitle>Recurring run configs</DialogTitle>
        <DialogContent style={{ minHeight: 250, display: 'flex' }}>
          <NativeTable
            rows={schedules.map((schedule) => ({
              id: schedule.metadata.name,
              name: displayName(schedule),
              otherFields: [
                <Link
                  className={commonCss.link}
                  to={`/recurringrun/details/${enc(schedule.metadata.name)}`}
                >
                  {displayName(schedule)}
                </Link>,
                schedule.spec?.suspend ? 'Disabled' : 'Enabled',
              ],
            }))}
            columns={[
              { label: 'Recurring Run Name', customRenderer: ({ value }) => <>{value}</> },
              { label: 'Status' },
            ]}
            filterLabel='Filter recurring runs'
            emptyMessage='No available recurring runs found.'
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setManager(false)}>Close</Button>
        </DialogActions>
      </Dialog>
    </NativePage>
  );
}
