// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { PlotType } from 'src/components/viewers/Viewer';
import type { ConfusionMatrixConfig } from 'src/components/viewers/ConfusionMatrix';
import type { ROCCurveConfig } from 'src/components/viewers/ROCCurve';

/**
 * Stock's legacy visualization contract: an output artifact whose name
 * normalizes to `mlpipeline-ui-metadata` holds `{"outputs": [...]}` entries
 * that select a viewer. Stock v2 still routes it; this keeps that routing with
 * the viewers in this tree.
 */
export const LEGACY_UI_METADATA = 'mlpipeline-ui-metadata';

export const isLegacyUiMetadata = (port: string) =>
  port.replace(/[\W_]/g, '-').toLowerCase() === LEGACY_UI_METADATA;

export interface UiMetadataOutput {
  type: string;
  source?: string;
  storage?: string;
  format?: string;
  header?: string[];
  labels?: string[];
  schema?: Array<{ name?: string; type?: string }>;
}

export type LegacyViewer =
  | { type: PlotType.TABLE; header: string[]; rows: string[][] }
  | { type: PlotType.CONFUSION_MATRIX; config: ConfusionMatrixConfig }
  | { type: PlotType.ROC; config: ROCCurveConfig }
  | { type: PlotType.MARKDOWN; content: string }
  | { type: PlotType.WEB_APP; html: string }
  | { type: PlotType.TENSORBOARD; source: string };

/** Content of `source`: inline text, or a read of the location it names. */
export type SourceReader = (source: string, storage?: string) => Promise<string>;

export function parseUiMetadata(text: string): UiMetadataOutput[] {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (error) {
    throw new Error(`Could not parse the UI metadata file: ${(error as Error).message}`, {
      cause: error,
    });
  }
  const outputs = (parsed as { outputs?: unknown })?.outputs;
  if (!Array.isArray(outputs))
    throw new Error('The UI metadata file needs an "outputs" array of viewer entries.');
  return outputs as UiMetadataOutput[];
}

/** Rows of an RFC 4180 CSV document; quoted fields may hold commas, quotes and newlines. */
export function parseCsvRows(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = '';
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (quoted) {
      if (char === '"' && text[i + 1] === '"') {
        field += '"';
        i++;
      } else if (char === '"') quoted = false;
      else field += char;
    } else if (char === '"') quoted = true;
    else if (char === ',') {
      row.push(field);
      field = '';
    } else if (char === '\n' || char === '\r') {
      if (char === '\r' && text[i + 1] === '\n') i++;
      row.push(field);
      rows.push(row);
      row = [];
      field = '';
    } else field += char;
  }
  if (field || row.length) {
    row.push(field);
    rows.push(row);
  }
  return rows.filter((cells) => cells.some((cell) => cell.trim()));
}

function required<T>(value: T | undefined, name: string): T {
  if (value === undefined || value === null || value === '')
    throw new Error(`Malformed metadata, property "${name}" is required.`);
  return value;
}

function schemaNames(schema: UiMetadataOutput['schema']): string[] {
  if (!Array.isArray(schema))
    throw new Error('"schema" must be an array of {"name": string, "type": string} objects.');
  return schema.map((field) => {
    if (!field?.name)
      throw new Error('Each item in the "schema" array must contain a "name" field.');
    return field.name;
  });
}

async function buildViewer(output: UiMetadataOutput, read: SourceReader): Promise<LegacyViewer> {
  const source = () => read(required(output.source, 'source'), output.storage);
  switch (output.type) {
    case PlotType.TABLE: {
      const header = required(output.header, 'header');
      if (required(output.format, 'format') !== 'csv')
        throw new Error(`Unsupported table format: ${output.format}`);
      const rows = parseCsvRows((await source()).trim()).map((r) => r.map((c) => c.trim()));
      return { type: PlotType.TABLE, header, rows };
    }
    case PlotType.CONFUSION_MATRIX: {
      const labels = required(output.labels, 'labels');
      const columns = schemaNames(required(output.schema, 'schema'));
      const rows = parseCsvRows((await source()).trim());
      if (labels.length ** 2 !== rows.length)
        throw new Error(
          `Data dimensions ${rows.length} do not match the number of labels passed ${labels.length}`,
        );
      const index = new Map(labels.map((label, i) => [label, i]));
      const data = labels.map(() => new Array<number>(labels.length).fill(0));
      for (const [x, y, count] of rows) {
        const i = index.get(x.trim());
        const j = index.get(y.trim());
        if (i === undefined || j === undefined)
          throw new Error(`Confusion matrix row names a label outside "labels": ${x}, ${y}`);
        data[i][j] = Number.parseInt(count, 10);
      }
      return {
        type: PlotType.CONFUSION_MATRIX,
        config: { type: PlotType.CONFUSION_MATRIX, axes: columns.slice(0, 2), data, labels },
      };
    }
    case PlotType.ROC: {
      const columns = schemaNames(required(output.schema, 'schema'));
      const fpr = columns.indexOf('fpr');
      const tpr = columns.indexOf('tpr');
      const threshold = columns.findIndex((name) => name.startsWith('threshold'));
      if (fpr < 0 || tpr < 0 || threshold < 0)
        throw new Error('Malformed schema, expected columns named "fpr", "tpr" and "threshold".');
      const data = parseCsvRows((await source()).trim()).map((row) => ({
        label: (row[threshold] || '').trim(),
        x: +row[fpr],
        y: +row[tpr],
      }));
      return { type: PlotType.ROC, config: { type: PlotType.ROC, data } };
    }
    case PlotType.MARKDOWN:
      return { type: PlotType.MARKDOWN, content: await source() };
    case PlotType.WEB_APP:
      return { type: PlotType.WEB_APP, html: await source() };
    case PlotType.TENSORBOARD:
      return { type: PlotType.TENSORBOARD, source: required(output.source, 'source') };
    default:
      throw new Error(`Unknown plot type: ${output.type}`);
  }
}

/** Build every viewer the metadata asks for; one bad entry does not hide the others. */
export async function buildLegacyViewers(outputs: UiMetadataOutput[], read: SourceReader) {
  const results = await Promise.allSettled(outputs.map((output) => buildViewer(output, read)));
  const viewers: LegacyViewer[] = [];
  const errors: string[] = [];
  results.forEach((result, i) => {
    if (result.status === 'fulfilled') viewers.push(result.value);
    else errors.push(`Output ${i + 1} (${outputs[i]?.type}): ${(result.reason as Error).message}`);
  });
  return { viewers, errors };
}

/** Read a response as text, refusing to buffer more than `limit` bytes. */
export async function readBoundedText(response: Response, limit: number): Promise<string> {
  const reader = response.body?.getReader();
  if (!reader) return '';
  const decoder = new TextDecoder();
  let text = '',
    size = 0;
  try {
    while (true) {
      const result = await reader.read();
      if (result.done) break;
      size += result.value.byteLength;
      if (size > limit)
        throw new Error(
          `Artifact exceeds the ${Math.round(limit / 1024 / 1024)} MiB preview limit. Download it instead.`,
        );
      text += decoder.decode(result.value, { stream: true });
    }
    return text + decoder.decode();
  } finally {
    await reader.cancel();
  }
}
