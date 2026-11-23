// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it, vi } from 'vitest';
import { PlotType } from 'src/components/viewers/Viewer';
import {
  buildLegacyViewers,
  isLegacyUiMetadata,
  parseCsvRows,
  parseUiMetadata,
} from './NativeUiMetadata';

describe('legacy ui-metadata routing', () => {
  it('recognizes the stock artifact name in its v1 and v2 spellings', () => {
    expect(isLegacyUiMetadata('mlpipeline-ui-metadata')).toBe(true);
    expect(isLegacyUiMetadata('mlpipeline_ui_metadata')).toBe(true);
    expect(isLegacyUiMetadata('MLPipeline UI Metadata')).toBe(true);
    expect(isLegacyUiMetadata('report')).toBe(false);
  });

  it('requires an outputs array', () => {
    expect(() => parseUiMetadata('{"version": 1}')).toThrow('"outputs" array');
    expect(() => parseUiMetadata('not json')).toThrow('Could not parse');
    expect(parseUiMetadata('{"outputs": []}')).toEqual([]);
  });

  it('parses quoted CSV fields with commas, quotes and CRLF line ends', () => {
    expect(parseCsvRows('a,"b, c","say ""hi"""\r\n1,2,3\n\n')).toEqual([
      ['a', 'b, c', 'say "hi"'],
      ['1', '2', '3'],
    ]);
  });

  it('builds every stock viewer and isolates malformed entries', async () => {
    const read = vi.fn(async (source: string, storage?: string) =>
      storage === 'inline' ? source : 'model,accuracy\nbaseline,0.81\ntuned,0.94\n',
    );
    const { viewers, errors } = await buildLegacyViewers(
      [
        { type: 'table', format: 'csv', header: ['model', 'accuracy'], source: 's3://b/table' },
        {
          type: 'confusion_matrix',
          format: 'csv',
          schema: [{ name: 'target' }, { name: 'predicted' }, { name: 'count' }],
          labels: ['neg', 'pos'],
          storage: 'inline',
          source: 'neg,neg,3\nneg,pos,1\npos,neg,1\npos,pos,5\n',
        },
        {
          type: 'roc',
          format: 'csv',
          schema: [{ name: 'fpr' }, { name: 'tpr' }, { name: 'thresholds' }],
          storage: 'inline',
          source: '0,0,1\n0.1,0.9,0.5\n1,1,0\n',
        },
        { type: 'markdown', storage: 'inline', source: '## Summary' },
        { type: 'web-app', storage: 'inline', source: '<h1>App</h1>' },
        { type: 'tensorboard', source: 's3://b/logs' },
        { type: 'table', format: 'csv', source: 's3://b/table' },
        { type: 'vega', source: 'x' },
      ],
      read,
    );
    expect(viewers.map((v) => v.type)).toEqual([
      PlotType.TABLE,
      PlotType.CONFUSION_MATRIX,
      PlotType.ROC,
      PlotType.MARKDOWN,
      PlotType.WEB_APP,
      PlotType.TENSORBOARD,
    ]);
    expect(viewers[0]).toMatchObject({
      header: ['model', 'accuracy'],
      rows: [
        ['model', 'accuracy'],
        ['baseline', '0.81'],
        ['tuned', '0.94'],
      ],
    });
    expect(viewers[1]).toMatchObject({
      config: {
        axes: ['target', 'predicted'],
        labels: ['neg', 'pos'],
        data: [
          [3, 1],
          [1, 5],
        ],
      },
    });
    expect(viewers[2]).toMatchObject({
      config: {
        data: [
          { label: '1', x: 0, y: 0 },
          { label: '0.5', x: 0.1, y: 0.9 },
          { label: '0', x: 1, y: 1 },
        ],
      },
    });
    expect(viewers[5]).toMatchObject({ source: 's3://b/logs' });
    expect(errors).toEqual([
      'Output 7 (table): Malformed metadata, property "header" is required.',
      'Output 8 (vega): Unknown plot type: vega',
    ]);
    expect(read).toHaveBeenCalledWith('s3://b/table', undefined);
  });

  it('rejects confusion matrices whose rows do not cover the labels', async () => {
    const { viewers, errors } = await buildLegacyViewers(
      [
        {
          type: 'confusion_matrix',
          schema: [{ name: 'a' }, { name: 'b' }, { name: 'n' }],
          labels: ['x', 'y'],
          storage: 'inline',
          source: 'x,x,1\n',
        },
      ],
      async (s) => s,
    );
    expect(viewers).toEqual([]);
    expect(errors[0]).toContain('Data dimensions 1 do not match the number of labels passed 2');
  });
});
