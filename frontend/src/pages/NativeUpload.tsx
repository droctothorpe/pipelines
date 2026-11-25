// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import {
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  FormControlLabel,
  InputAdornment,
  Radio,
} from '@mui/material';
import { classes } from 'typestyle';
import { commonCss, padding } from 'src/Css';
import Input from 'src/atoms/Input';
import BusyButton from 'src/atoms/BusyButton';
import DropzoneArea, { type DropzoneAreaHandle } from 'src/atoms/DropzoneArea';
import NativePage from 'src/components/NativePage';
import NativeTable from 'src/components/NativeTable';
import {
  DocumentationCompilePipeline,
  PIPELINE_PACKAGE_ACCEPT,
  pipelinePackageValidator,
} from 'src/components/PipelinePackage';
import { useNativeUi } from 'src/lib/NativeUiContext';
import { useInventory } from 'src/lib/NativeQueries';
import { createResource, type NativeResource } from 'src/lib/ArgoResources';
import {
  displayName,
  description as resourceDescription,
  pipelineId,
  pipelineHref,
  resourceId,
  deleteNativeResource,
} from 'src/lib/NativeUi';
import { importTemplate } from 'src/lib/NativeImport';

/** Stock NewPipelineVersion form; only the import/identity boundary is native. */
export default function NativeUpload() {
  const { namespace, fail } = useNativeUi();
  const navigate = useNavigate();
  const client = useQueryClient();
  const inventory = useInventory();
  const [search] = useSearchParams();
  const [newPipeline, setNewPipeline] = useState(!search.get('pipelineId'));
  const [name, setName] = useState(''),
    [description, setDescription] = useState('');
  const [existingId, setExistingId] = useState(search.get('pipelineId') || '');
  const [versionName, setVersionName] = useState(''),
    [versionDescription, setVersionDescription] = useState('');
  const [codeSource, setCodeSource] = useState(''),
    [url, setUrl] = useState('');
  const [local, setLocal] = useState(true),
    [file, setFile] = useState<File>();
  const [busy, setBusy] = useState(false),
    [dragging, setDragging] = useState(false);
  const [picker, setPicker] = useState(false),
    [pick, setPick] = useState<string[]>([]);
  const dropzone = useRef<DropzoneAreaHandle>(null);
  const groups = new Map(
    (inventory.versions.data || []).map((version) => [pipelineId(version), version]),
  );
  for (const pipeline of inventory.pipelines.data || []) groups.set(resourceId(pipeline), pipeline);
  const existing = groups.get(existingId);
  const invalid =
    (newPipeline ? !name.trim() : !existing || !versionName.trim()) ||
    (local ? !file : !url.trim());
  async function create() {
    setBusy(true);
    let createdPipeline: NativeResource | undefined;
    try {
      let text: string;
      if (local) {
        if (!file || !/\.ya?ml$/i.test(file.name))
          throw new Error(
            'Choose a compiled WorkflowTemplate YAML file. ZIP and tar packages are not supported.',
          );
        text = await file.text();
      } else {
        const address = new URL(url);
        if (!['http:', 'https:'].includes(address.protocol)) throw new Error('Use an HTTP(S) URL.');
        const response = await fetch(address, { credentials: 'omit' });
        if (!response.ok) throw new Error(`Pipeline download failed (${response.status}).`);
        text = await response.text();
      }
      if (
        newPipeline &&
        [...groups.values()].some((pipeline) => displayName(pipeline) === name.trim())
      )
        throw new Error(
          'This pipeline already exists. Choose "Create a new pipeline version under an existing pipeline".',
        );
      // Validate the package before creating any persistent resource.
      const resource = await importTemplate(text, namespace, {
        pipeline: newPipeline ? 'pending-pipeline' : existingId,
        displayName: newPipeline ? name.trim() : displayName(existing!),
        description: newPipeline ? description : resourceDescription(existing!),
        versionName: versionName || file?.name.replace(/\.ya?ml$/i, '') || name.trim(),
        versionDescription,
        codeSource,
      });
      if (newPipeline) {
        createdPipeline = await createResource(namespace, 'pipelines', {
          apiVersion: 'v1',
          kind: 'ConfigMap',
          metadata: {
            name: `pipeline-${crypto.randomUUID()}`,
            namespace,
            labels: { 'pipelines.kubeflow.org/resource': 'pipeline' },
          },
          data: { displayName: name.trim(), description, shared: 'true' },
        });
        resource.metadata.labels = {
          ...resource.metadata.labels,
          'pipelines.kubeflow.org/pipeline': resourceId(createdPipeline!),
        };
        resource.metadata.name = `version-${crypto.randomUUID()}`;
      }
      const uploaded = await createResource(namespace, 'workflow-templates', resource);
      createdPipeline = undefined;
      await client.invalidateQueries({ queryKey: ['native', namespace] });
      navigate(pipelineHref(uploaded));
    } catch (error) {
      if (createdPipeline) {
        try {
          await deleteNativeResource(namespace, createdPipeline);
        } catch (cleanupError) {
          fail(
            new Error(
              `${error instanceof Error ? error.message : error} The empty pipeline could not be removed: ${cleanupError instanceof Error ? cleanupError.message : cleanupError}`,
            ),
          );
          return;
        }
      }
      fail(error);
    } finally {
      setBusy(false);
    }
  }
  return (
    <NativePage
      title='New Pipeline'
      breadcrumbs={[{ displayName: 'Pipelines', href: '/pipelines' }]}
      error={inventory.versions.error}
    >
      <div className={classes(commonCss.page, padding(20, 'lr'))}>
        <div className={classes(commonCss.scrollContainer, padding(20, 'lr'))}>
          <div className={padding(10, 't')}>Upload pipeline or pipeline version.</div>
          <div className={classes(commonCss.flex, padding(10, 'b'))}>
            <FormControlLabel
              id='createNewPipelineBtn'
              label='Create a new pipeline'
              checked={newPipeline}
              control={<Radio color='primary' />}
              onChange={() => setNewPipeline(true)}
            />
            <FormControlLabel
              id='createPipelineVersionUnderExistingPipelineBtn'
              label='Create a new pipeline version under an existing pipeline'
              checked={!newPipeline}
              control={<Radio color='primary' />}
              onChange={() => setNewPipeline(false)}
            />
          </div>
          {newPipeline ? (
            <>
              <div>Upload pipeline with the specified package.</div>
              <Input
                id='newPipelineName'
                value={name}
                required
                label='Pipeline Name'
                variant='outlined'
                onChange={(event) => setName(event.target.value)}
                autoFocus
              />
              <Input
                id='pipelineDescription'
                value={description}
                label='Pipeline Description'
                variant='outlined'
                onChange={(event) => setDescription(event.target.value)}
              />
            </>
          ) : (
            <>
              <div>Upload pipeline version with the specified package.</div>
              <Input
                value={existing ? displayName(existing) : ''}
                required
                label='Pipeline'
                variant='outlined'
                InputProps={{
                  readOnly: true,
                  endAdornment: (
                    <InputAdornment position='end'>
                      <Button
                        color='secondary'
                        id='choosePipelineBtn'
                        onClick={() => setPicker(true)}
                        style={{ padding: '3px 5px', margin: 0 }}
                      >
                        Choose
                      </Button>
                    </InputAdornment>
                  ),
                }}
              />
              <Input
                id='pipelineVersionName'
                label='Pipeline Version Name'
                required
                onChange={(event) => setVersionName(event.target.value)}
                value={versionName}
                autoFocus
                variant='outlined'
              />
              <Input
                id='pipelineVersionDescription'
                label='Pipeline Version Description'
                value={versionDescription}
                onChange={(event) => setVersionDescription(event.target.value)}
                variant='outlined'
              />
            </>
          )}
          {local ? (
            <div className={padding(10, 'b')}>
              Choose a pipeline package file from your computer, and give the pipeline a unique
              name.
              <br />
              You can also drag and drop the file here.
            </div>
          ) : (
            <div className={padding(10, 'b')}>URL must be publicly accessible.</div>
          )}
          <DocumentationCompilePipeline />
          <div className={classes(commonCss.flex, padding(10, 'b'))}>
            <FormControlLabel
              id='localPackageBtn'
              label='Upload a file'
              checked={local}
              control={<Radio color='primary' />}
              onChange={() => setLocal(true)}
            />
            <DropzoneArea
              id='dropZone'
              onDrop={(files) => {
                setFile(files[0]);
                if (!name) setName(files[0].name.replace(/\.ya?ml$/i, ''));
                setDragging(false);
              }}
              onDropRejected={() =>
                fail(
                  new Error(
                    'Choose a supported pipeline package. Native execution accepts compiled WorkflowTemplate YAML.',
                  ),
                )
              }
              onDragEnter={() => setDragging(true)}
              onDragLeave={() => setDragging(false)}
              accept={PIPELINE_PACKAGE_ACCEPT}
              validator={pipelinePackageValidator}
              disabled={!local}
              style={{ position: 'relative' }}
              ref={dropzone}
              inputProps={{ tabIndex: -1 }}
            >
              {dragging && (
                <div
                  style={{
                    position: 'absolute',
                    inset: 0,
                    border: '2px dashed #aaa',
                    background: '#eee',
                    zIndex: 2,
                    textAlign: 'center',
                    padding: '2.5em 0',
                  }}
                >
                  Drop files..
                </div>
              )}
              <Input
                data-testid='uploadFileInput'
                value={file?.name || ''}
                required
                label='File'
                variant='outlined'
                disabled={!local}
                InputProps={{
                  readOnly: true,
                  style: { maxWidth: 2000, width: 455 },
                  endAdornment: (
                    <InputAdornment position='end'>
                      <Button
                        color='secondary'
                        onClick={() => dropzone.current?.open()}
                        style={{ padding: '3px 5px', margin: 0, whiteSpace: 'nowrap' }}
                        disabled={!local}
                      >
                        Choose file
                      </Button>
                    </InputAdornment>
                  ),
                }}
              />
            </DropzoneArea>
          </div>
          <div className={classes(commonCss.flex, padding(10, 'b'))}>
            <FormControlLabel
              id='remotePackageBtn'
              label='Import by url'
              checked={!local}
              control={<Radio color='primary' />}
              onChange={() => setLocal(false)}
            />
            <Input
              id='pipelinePackageUrl'
              label='Package Url'
              multiline
              onChange={(event) => setUrl(event.target.value)}
              value={url}
              variant='outlined'
              disabled={local}
              style={{ maxWidth: 2000, width: 465 }}
            />
          </div>
          <Input
            id='pipelineVersionCodeSource'
            label='Code Source'
            multiline
            onChange={(event) => setCodeSource(event.target.value)}
            value={codeSource}
            variant='outlined'
          />
          <div className={commonCss.flex}>
            <BusyButton
              id='createNewPipelineOrVersionBtn'
              disabled={!!invalid}
              busy={busy}
              className={commonCss.buttonAction}
              title='Create'
              onClick={create}
            />
            <Button id='cancelNewPipelineOrVersionBtn' onClick={() => navigate('/pipelines')}>
              Cancel
            </Button>
          </div>
        </div>
      </div>
      <Dialog open={picker} onClose={() => setPicker(false)} fullWidth maxWidth='md'>
        <DialogTitle>Choose a pipeline</DialogTitle>
        <DialogContent style={{ minHeight: 300, display: 'flex' }}>
          <NativeTable
            rows={[...groups].map(([id, entry]) => ({
              id,
              name: displayName(entry),
              otherFields: [displayName(entry), resourceDescription(entry)],
            }))}
            columns={[{ label: 'Pipeline name', sortKey: 'name' }, { label: 'Description' }]}
            selected={pick}
            select={(ids) => setPick(ids.slice(-1))}
            filterLabel='Filter pipelines'
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPicker(false)}>Cancel</Button>
          <Button
            disabled={pick.length !== 1}
            onClick={() => {
              setExistingId(pick[0]);
              setPicker(false);
            }}
          >
            Use this pipeline
          </Button>
        </DialogActions>
      </Dialog>
    </NativePage>
  );
}
