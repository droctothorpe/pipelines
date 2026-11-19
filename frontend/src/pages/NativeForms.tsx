// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogActions,
  FormControlLabel,
  InputAdornment,
  Radio,
  Tooltip,
} from '@mui/material';
import { classes } from 'typestyle';
import { commonCss, padding, fontsize } from 'src/Css';
import { ExternalLink } from 'src/atoms/ExternalLink';
import { HelpButton } from 'src/atoms/HelpButton';
import Input from 'src/atoms/Input';
import BusyButton from 'src/atoms/BusyButton';
import NativePage from 'src/components/NativePage';
import NativeTable from 'src/components/NativeTable';
import Toolbar from 'src/components/Toolbar';
import AddIcon from '@mui/icons-material/Add';
import { formatDateString } from 'src/lib/UiUtils';
import { useNativeUi } from 'src/lib/NativeUiContext';
import { useInventory } from 'src/lib/NativeQueries';
import { createResource, submitRun, type NativeResource } from 'src/lib/ArgoResources';
import {
  description as resourceDescription,
  DISPLAY_NAME,
  DESCRIPTION,
  EXPERIMENT,
  displayName,
  pipelineId,
  getUiRun,
  runHref,
  enc,
} from 'src/lib/NativeUi';

export function NativeNewExperiment() {
  const { namespace, fail } = useNativeUi();
  const navigate = useNavigate();
  const client = useQueryClient();
  const [name, setName] = useState(''),
    [description, setDescription] = useState(''),
    [busy, setBusy] = useState(false);
  return (
    <NativePage
      title='New experiment'
      breadcrumbs={[{ displayName: 'Experiments', href: '/experiments' }]}
    >
      <div className={classes(commonCss.page, padding(20, 'lr'))}>
        <div className={classes(commonCss.scrollContainer, padding(20, 'lr'))}>
          <div className={commonCss.header}>Experiment details</div>
          <div style={{ fontSize: fontsize.small }}>
            Think of an Experiment as a space that contains the history of all pipelines and their
            associated runs
          </div>
          <Input
            id='experimentName'
            label='Experiment name'
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
            autoFocus
            variant='outlined'
          />
          <Input
            id='experimentDescription'
            label='Description'
            multiline
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            variant='outlined'
          />
          <div className={commonCss.flex}>
            <BusyButton
              id='createExperimentBtn'
              title='Next'
              className={commonCss.buttonAction}
              disabled={!name.trim()}
              busy={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  const resource: NativeResource = {
                    apiVersion: 'v1',
                    kind: 'ConfigMap',
                    metadata: {
                      name: `experiment-${crypto.randomUUID().slice(0, 12)}`,
                      namespace,
                      labels: { 'pipelines.kubeflow.org/resource': 'experiment' },
                    },
                    data: { displayName: name.trim(), description },
                  };
                  await createResource(namespace, 'experiments', resource);
                  await client.invalidateQueries({
                    queryKey: ['native', namespace, 'experiments'],
                  });
                  navigate(
                    `/runs/new?experimentId=${enc(resource.metadata.name)}&firstRunInExperiment=1`,
                  );
                } catch (error) {
                  fail(error);
                } finally {
                  setBusy(false);
                }
              }}
            />
            <Button id='cancelNewExperimentBtn' onClick={() => navigate('/experiments')}>
              Cancel
            </Button>
            <div style={{ color: 'red' }}>{!name.trim() ? 'Experiment name is required' : ''}</div>
          </div>
        </div>
      </div>
    </NativePage>
  );
}

function Choose({
  label,
  value,
  disabled,
  open,
}: {
  label: string;
  value: string;
  disabled?: boolean;
  open: () => void;
}) {
  return (
    <Input
      label={label}
      value={value}
      required
      variant='outlined'
      InputProps={{
        readOnly: true,
        endAdornment: (
          <InputAdornment position='end'>
            <Button
              color='secondary'
              disabled={disabled}
              onClick={open}
              style={{ padding: '3px 5px', margin: 0, whiteSpace: 'nowrap' }}
            >
              Choose
            </Button>
          </InputAdornment>
        ),
      }}
    />
  );
}

export function NativeNewRun() {
  const { namespace, fail } = useNativeUi();
  const navigate = useNavigate();
  const [search] = useSearchParams();
  const inventory = useInventory();
  const client = useQueryClient();
  const [versionName, setVersionName] = useState(search.get('pipelineVersionId') || '');
  const [experimentName, setExperimentName] = useState(search.get('experimentId') || '');
  const [customName, setCustomName] = useState<string>();
  const [description, setDescription] = useState<string>();
  const [parameters, setParameters] = useState<Record<string, string>>({});
  const [account, setAccount] = useState<string>();
  const [recurring, setRecurring] = useState(search.get('recurring') === '1');
  const [customCron, setCron] = useState<string>(),
    [customTimezone, setTimezone] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [picker, setPicker] = useState<'Pipeline' | 'Pipeline Version' | 'Experiment'>();
  const [pick, setPick] = useState<string[]>([]);
  const cloneId = search.get('cloneFromRun');
  const cloneScheduleId = search.get('cloneFromRecurringRun');
  const cloneSchedule = inventory.schedules.data?.find(
    (schedule) => schedule.metadata.name === cloneScheduleId,
  );
  const cron = customCron ?? cloneSchedule?.spec?.schedules?.[0] ?? '0 * * * *';
  const timezone = customTimezone ?? cloneSchedule?.spec?.timezone ?? 'UTC';
  const clone = useQuery({
    queryKey: ['native', namespace, 'run', cloneId],
    queryFn: ({ signal }) => getUiRun(namespace, cloneId!, signal),
    enabled: !!cloneId,
  });
  const versions = inventory.versions.data || [];
  const version = versions.find(
    (version) =>
      version.metadata.name ===
      (versionName ||
        clone.data?.spec.workflowTemplateRef?.name ||
        cloneSchedule?.spec?.workflowSpec?.workflowTemplateRef?.name),
  );
  const experiment = inventory.experiments.data?.find(
    (exp) =>
      exp.metadata.name ===
      (experimentName ||
        clone.data?.metadata.labels?.[EXPERIMENT] ||
        cloneSchedule?.spec?.workflowMetadata?.labels?.[EXPERIMENT]),
  );
  const name =
    customName ??
    (clone.data
      ? `Clone of ${displayName(clone.data)}`
      : cloneSchedule
        ? `Clone of ${displayName(cloneSchedule)}`
        : version
          ? `Run of ${displayName(version)}`
          : '');
  const clonedParameters: Array<{ name: string; value?: string }> =
    clone.data?.spec.arguments?.parameters ||
    cloneSchedule?.spec?.workflowSpec?.arguments?.parameters ||
    [];
  const serviceAccount =
    account ??
    clone.data?.spec.serviceAccountName ??
    cloneSchedule?.spec?.workflowSpec?.serviceAccountName ??
    version?.spec?.serviceAccountName ??
    '';
  const runDescription =
    description ??
    clone.data?.metadata.annotations?.[DESCRIPTION] ??
    cloneSchedule?.metadata.annotations?.[DESCRIPTION] ??
    '';
  const specs: Array<{ name: string; value?: string }> = version?.spec?.arguments?.parameters || [];
  const values = Object.fromEntries(
    specs.map((parameter) => [
      parameter.name,
      parameters[parameter.name] ??
        clonedParameters.find((value) => value.name === parameter.name)?.value ??
        parameter.value ??
        '',
    ]),
  );
  const invalid =
    !version ||
    !name.trim() ||
    specs.some((parameter) => parameter.value === undefined && !values[parameter.name]);
  const unique = new Map(versions.map((version) => [pipelineId(version), version]));
  const choices =
    picker === 'Experiment'
      ? inventory.experiments.data || []
      : picker === 'Pipeline Version'
        ? versions.filter((entry) => pipelineId(entry) === pipelineId(version!))
        : [...unique.values()];
  const start = async () => {
    if (!version) return;
    setBusy(true);
    try {
      if (recurring) {
        const resource: NativeResource = {
          apiVersion: 'argoproj.io/v1alpha1',
          kind: 'CronWorkflow',
          metadata: {
            name: `schedule-${crypto.randomUUID().slice(0, 12)}`,
            namespace,
            labels: version.metadata.labels,
            annotations: { [DISPLAY_NAME]: name, [DESCRIPTION]: runDescription },
          },
          spec: {
            schedules: [cron],
            timezone,
            suspend: true,
            concurrencyPolicy: 'Forbid',
            workflowMetadata: {
              labels: {
                ...version.metadata.labels,
                ...(experiment ? { [EXPERIMENT]: experiment.metadata.name } : {}),
              },
            },
            workflowSpec: {
              workflowTemplateRef: { name: version.metadata.name },
              ...(serviceAccount ? { serviceAccountName: serviceAccount } : {}),
              arguments: {
                parameters: Object.entries(values).map(([name, value]) => ({ name, value })),
              },
            },
          },
        };
        await createResource(namespace, 'cron-workflows', resource);
        await client.invalidateQueries({ queryKey: ['native', namespace] });
        navigate(`/recurringrun/details/${enc(resource.metadata.name)}`);
      } else {
        const run = await submitRun(
          namespace,
          version,
          values,
          experiment?.metadata.name || '',
          name,
          runDescription,
          serviceAccount,
        );
        await client.invalidateQueries({ queryKey: ['native', namespace, 'runs'] });
        navigate(runHref(run));
      }
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  };
  return (
    <NativePage
      title={
        cloneScheduleId
          ? 'Clone a recurring run'
          : cloneId
            ? 'Clone a run'
            : recurring
              ? 'Start a recurring run'
              : 'Start a new run'
      }
      breadcrumbs={[{ displayName: 'Runs', href: '/runs' }]}
      error={inventory.error || clone.error}
    >
      <div className={classes(commonCss.page, padding(20, 'lr'))}>
        <div className={commonCss.scrollContainer}>
          <div className={commonCss.header}>Run details</div>
          <Choose
            label='Pipeline'
            value={version ? displayName(version) : ''}
            open={() => {
              setPick([]);
              setPicker('Pipeline');
            }}
          />
          {recurring && (
            <Tooltip title='Native schedules pin a WorkflowTemplate version. Upload a new schedule to change versions.'>
              <FormControlLabel
                control={<Checkbox checked={false} disabled color='primary' />}
                label='Always use the latest pipeline version'
              />
            </Tooltip>
          )}
          <Choose
            label='Pipeline Version'
            value={version?.metadata.name || ''}
            disabled={!version}
            open={() => {
              setPick([]);
              setPicker('Pipeline Version');
            }}
          />
          <Input
            label={recurring ? 'Recurring run config name' : 'Run name'}
            required
            onChange={(event) => setCustomName(event.target.value)}
            autoFocus
            value={name}
            variant='outlined'
          />
          <Input
            label='Description'
            multiline
            onChange={(event) => setDescription(event.target.value)}
            value={runDescription}
            variant='outlined'
          />
          <div>This run will be associated with the following experiment</div>
          <Choose
            label='Experiment'
            value={experiment ? displayName(experiment) : ''}
            open={() => {
              setPick([]);
              setPicker('Experiment');
            }}
          />
          <div>
            This run will use the following Kubernetes service account.{' '}
            <HelpButton
              helpText={
                <div>
                  Note, the service account needs{' '}
                  <ExternalLink href='https://argoproj.github.io/argo-workflows/workflow-rbac/'>
                    minimum permissions required by argo workflows
                  </ExternalLink>{' '}
                  and extra permissions the specific task requires.
                </div>
              }
            />
          </div>
          <Input
            label='Service Account'
            value={serviceAccount}
            onChange={(event) => setAccount(event.target.value)}
            variant='outlined'
          />
          <div className={commonCss.header}>Run Type</div>
          <FormControlLabel
            id='oneOffToggle'
            label='One-off'
            control={<Radio color='primary' />}
            checked={!recurring}
            onChange={() => setRecurring(false)}
          />
          <FormControlLabel
            id='recurringToggle'
            label='Recurring'
            control={<Radio color='primary' />}
            checked={recurring}
            onChange={() => setRecurring(true)}
          />
          {recurring && (
            <>
              <div className={commonCss.header}>Run trigger</div>
              <div>Choose a method by which new runs will be triggered</div>
              <Input
                label='Cron schedule'
                required
                value={cron}
                onChange={(event) => setCron(event.target.value)}
                variant='outlined'
              />
              <Input
                label='Timezone'
                value={timezone}
                onChange={(event) => setTimezone(event.target.value)}
                variant='outlined'
              />
              <p>
                New recurring runs are disabled until you enable them. Overlapping runs are
                forbidden.
              </p>
            </>
          )}
          <div className={commonCss.header}>Pipeline Root</div>
          <div>
            Pipeline Root represents an artifact repository, refer to{' '}
            <ExternalLink href='https://www.kubeflow.org/docs/components/pipelines/concepts/pipeline-root/'>
              Pipeline Root Documentation
            </ExternalLink>
            .
          </div>
          <Tooltip title='The artifact repository is configured in the native WorkflowTemplate and Argo controller.'>
            <FormControlLabel
              label='Custom Pipeline Root'
              control={<Checkbox checked={false} disabled color='primary' />}
            />
          </Tooltip>
          <div className={commonCss.header}>Run parameters</div>
          <div>
            {version
              ? specs.length
                ? 'Specify parameters required by the pipeline'
                : 'This pipeline has no parameters'
              : 'Parameters will appear after you select a pipeline'}
          </div>
          {specs.map((parameter) => (
            <Input
              key={parameter.name}
              label={parameter.name}
              required={parameter.value === undefined}
              value={values[parameter.name]}
              onChange={(event) =>
                setParameters((current) => ({ ...current, [parameter.name]: event.target.value }))
              }
              variant='outlined'
            />
          ))}
          <div className={classes(commonCss.flex, padding(20, 'tb'))}>
            <BusyButton
              id='startNewRunBtn'
              title='Start'
              className={commonCss.buttonAction}
              busy={busy}
              disabled={invalid || (recurring && !cron.trim())}
              onClick={start}
            />
            <Button id='exitNewRunPageBtn' onClick={() => navigate('/runs')}>
              Cancel
            </Button>
          </div>
        </div>
      </div>
      <Dialog
        open={!!picker}
        onClose={() => setPicker(undefined)}
        PaperProps={{ style: { maxWidth: 1200, minWidth: 680, width: 'calc(100% - 120px)' } }}
      >
        <DialogContent>
          <Toolbar
            pageTitle={
              picker === 'Experiment'
                ? 'Choose an experiment'
                : picker === 'Pipeline Version'
                  ? 'Choose a pipeline version'
                  : 'Choose a pipeline'
            }
            breadcrumbs={[]}
            actions={
              picker === 'Experiment'
                ? {
                    create: {
                      title: 'Create new experiment',
                      tooltip: 'Create new experiment',
                      icon: AddIcon,
                      action: () => navigate('/experiments/new'),
                    },
                  }
                : {}
            }
          />
          <NativeTable
            radio
            rows={choices.map((choice) => ({
              id: choice.metadata.name,
              name: picker === 'Pipeline Version' ? choice.metadata.name : displayName(choice),
              created: choice.metadata.creationTimestamp,
              otherFields: [
                picker === 'Pipeline Version' ? choice.metadata.name : displayName(choice),
                resourceDescription(choice),
                formatDateString(choice.metadata.creationTimestamp),
              ],
            }))}
            columns={[
              {
                label:
                  picker === 'Experiment'
                    ? 'Experiment name'
                    : picker === 'Pipeline Version'
                      ? 'Version name'
                      : 'Pipeline name',
                sortKey: 'name',
                flex: picker === 'Pipeline Version' ? 2 : 1,
              },
              { label: 'Description', flex: picker === 'Pipeline Version' ? 1 : 2 },
              {
                label: picker === 'Experiment' ? 'Created at' : 'Uploaded on',
                sortKey: 'created_at',
                flex: 1,
              },
            ]}
            selected={pick}
            select={(ids) => setPick(ids.slice(-1))}
            filterLabel={`Filter ${picker?.toLowerCase()}s`}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPicker(undefined)}>Cancel</Button>
          <Button
            disabled={pick.length !== 1}
            onClick={() => {
              if (picker === 'Experiment') setExperimentName(pick[0]);
              else {
                setVersionName(pick[0]);
                setParameters({});
              }
              setPicker(undefined);
            }}
          >
            Use this {picker?.toLowerCase()}
          </Button>
        </DialogActions>
      </Dialog>
    </NativePage>
  );
}
