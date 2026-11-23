// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { useQuery } from '@tanstack/react-query';
import {
  Alert,
  CircularProgress,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
} from '@mui/material';
import Banner from 'src/components/Banner';
import ConfusionMatrix from './ConfusionMatrix';
import MarkdownViewer from './MarkdownViewer';
import ROCCurve from './ROCCurve';
import { PlotType } from './Viewer';
import {
  argoArtifactUrl,
  argoRequest,
  type ArgoMetadata,
  type ArgoNode,
  type ArgoWorkflow,
} from 'src/lib/Argo';
import {
  buildLegacyViewers,
  parseUiMetadata,
  readBoundedText,
  type LegacyViewer,
} from 'src/lib/NativeUiMetadata';

const SOURCE_LIMIT = 1024 * 1024;

/** The sandbox the typed HTML viewer uses: no scripts, no network, inline styles only. */
export function SandboxedHtml({ html, title }: { html: string; title: string }) {
  return (
    <iframe
      title={title}
      sandbox=''
      style={{ border: 0, width: '100%', height: '100%', minHeight: 400 }}
      srcDoc={`<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'">${html}`}
    />
  );
}

function LegacyTable({ header, rows }: { header: string[]; rows: string[][] }) {
  return (
    <TableContainer style={{ maxWidth: '100%' }}>
      <Table size='small' aria-label='Legacy table'>
        <TableHead>
          <TableRow>
            {header.map((name, i) => (
              <TableCell key={i}>{name}</TableCell>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row, i) => (
            <TableRow key={i}>
              {header.map((_, j) => (
                <TableCell key={j}>{row[j] ?? ''}</TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}

function LegacyViewerView({ viewer, index }: { viewer: LegacyViewer; index: number }) {
  switch (viewer.type) {
    case PlotType.TABLE:
      return <LegacyTable header={viewer.header} rows={viewer.rows} />;
    case PlotType.CONFUSION_MATRIX:
      return <ConfusionMatrix configs={[viewer.config]} />;
    case PlotType.ROC:
      return <ROCCurve configs={[viewer.config]} />;
    case PlotType.MARKDOWN:
      return (
        <MarkdownViewer configs={[{ type: PlotType.MARKDOWN, markdownContent: viewer.content }]} />
      );
    case PlotType.WEB_APP:
      return <SandboxedHtml html={viewer.html} title={`Legacy web app ${index + 1}`} />;
    case PlotType.TENSORBOARD:
      return (
        <Banner
          mode='info'
          message={`TensorBoard viewers are not launched by the native UI; open the logs at ${viewer.source} in your own TensorBoard.`}
        />
      );
  }
}

/**
 * Render the viewers a legacy `mlpipeline-ui-metadata` artifact declares.
 * Sources are inline text or the URI of one of the producing task's own
 * output artifacts, which Argo Server can serve; there is no generic object
 * store read behind this UI.
 */
export function NativeUiMetadata({
  run,
  node,
  artifacts,
  content,
}: {
  run: ArgoWorkflow;
  node: ArgoNode;
  artifacts: ArgoMetadata['artifacts'];
  content: string;
}) {
  const query = useQuery({
    queryKey: ['native', run.metadata.namespace, run.metadata.uid, node.id, 'ui-metadata', content],
    queryFn: () =>
      buildLegacyViewers(parseUiMetadata(content), async (source, storage) => {
        if (storage === 'inline') return source;
        const wanted = source.replace(/\/+$/, '');
        const artifact = artifacts.find((a) => a.uri.replace(/\/+$/, '') === wanted);
        if (!artifact)
          throw new Error(
            `Source ${source} is not an output artifact of this task. Use inline sources or this task's own artifact URIs.`,
          );
        const response = await argoRequest(argoArtifactUrl(run, node, artifact.port));
        return readBoundedText(response, SOURCE_LIMIT);
      }),
  });
  if (query.error) return <Alert severity='error'>{query.error.message}</Alert>;
  if (query.isPending) return <CircularProgress aria-label='Loading visualization' size={24} />;
  const { viewers, errors } = query.data;
  return (
    <div>
      {errors.map((error) => (
        <Alert key={error} severity='warning'>
          {error}
        </Alert>
      ))}
      {!viewers.length && !errors.length && (
        <Banner mode='info' message='The UI metadata file declares no outputs.' />
      )}
      {viewers.map((viewer, i) => (
        <section key={i} aria-label={`${viewer.type} visualization`} style={{ marginBottom: 24 }}>
          <LegacyViewerView viewer={viewer} index={i} />
        </section>
      ))}
    </div>
  );
}
