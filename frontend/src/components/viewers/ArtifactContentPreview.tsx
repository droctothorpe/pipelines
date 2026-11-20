// Copyright 2026 The Kubeflow Authors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

import { Table, TableBody, TableCell, TableContainer, TableHead, TableRow } from '@mui/material';
import Banner from 'src/components/Banner';
import DetailsTable from 'src/components/DetailsTable';
import type {
  DatasetPreview,
  ModelPreview,
  ModelPreviewValue,
  PreviewScalar,
} from 'src/lib/v2/ArtifactContentPreview';

function displayCell(value: PreviewScalar): string {
  return value === '' ? '""' : String(value);
}

export function DatasetPreviewTable({ preview }: { preview: DatasetPreview }) {
  const { columns, rows, sample, total_rows, total_columns } = preview;
  return (
    <section aria-label='Dataset preview'>
      <h3>Dataset preview{preview.format ? ` (${preview.format})` : ''}</h3>
      <p role='status'>
        Showing {rows.length} of {total_rows ?? 'unknown'} rows; {columns.length} of{' '}
        {total_columns ?? 'unknown'} columns. Sample: {sample.method}.
      </p>
      {sample.rows_omitted ? (
        <Banner
          mode='info'
          message='Row values were intentionally omitted by the producer. This is a schema-only preview.'
        />
      ) : rows.length === 0 ? (
        <Banner
          mode='info'
          message={total_rows === 0 ? 'Dataset is empty.' : 'No sample rows were recorded.'}
        />
      ) : null}
      {(sample.rows_truncated ||
        sample.columns_truncated ||
        sample.values_truncated ||
        sample.redacted) && (
        <p>
          {sample.rows_truncated && 'Only sampled rows are shown. '}
          {sample.columns_truncated && 'Some columns are not included. '}
          {sample.values_truncated && 'Some values were shortened. '}
          {sample.redacted && 'The producer redacted sample values.'}
        </p>
      )}
      <TableContainer style={{ maxWidth: '100%' }}>
        <Table size='small' aria-label='Dataset sample'>
          <TableHead>
            <TableRow>
              {columns.map((column, index) => (
                <TableCell key={index} scope='col' style={{ verticalAlign: 'top' }}>
                  {column.name}
                  <br />
                  <small>{column.dtype}</small>
                </TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((row, index) => (
              <TableRow key={index}>
                {row.map((cell, columnIndex) => (
                  <TableCell
                    key={columnIndex}
                    style={{
                      minWidth: 100,
                      maxWidth: 300,
                      overflowWrap: 'anywhere',
                      whiteSpace: 'pre-wrap',
                    }}
                  >
                    {displayCell(cell)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </section>
  );
}

function ModelEntries({
  title,
  entries,
}: {
  title: string;
  entries: Record<string, ModelPreviewValue>;
}) {
  const names = Object.keys(entries).sort();
  return (
    <>
      <h4>{title}</h4>
      {names.length ? (
        <TableContainer>
          <Table
            size='small'
            aria-label={title}
            sx={{
              tableLayout: 'fixed',
              '& th, & td': {
                overflowWrap: 'anywhere',
                whiteSpace: 'pre-wrap',
                verticalAlign: 'top',
              },
            }}
          >
            <TableHead>
              <TableRow>
                <TableCell scope='col' style={{ width: '40%' }}>
                  Name
                </TableCell>
                <TableCell scope='col'>Recorded value</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {names.map((name) => (
                <TableRow key={name}>
                  <TableCell component='th' scope='row'>
                    {name}
                  </TableCell>
                  <TableCell>{JSON.stringify(entries[name])}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      ) : (
        <p>Not recorded.</p>
      )}
    </>
  );
}

export function ModelPreviewSummary({ preview }: { preview: ModelPreview }) {
  return (
    <section aria-label='Model preview'>
      <h3>Model preview</h3>
      <DetailsTable
        fields={[
          ['Framework', preview.framework?.name || 'Not recorded'],
          ['Framework version', preview.framework?.version || 'Not recorded'],
          ['Estimator class', preview.estimator_class || 'Not recorded'],
        ]}
      />
      <p>Producer-recorded configuration and structural facts, not learned weights.</p>
      <ModelEntries title='Recorded hyperparameters' entries={preview.hyperparameters} />
      <ModelEntries title='Structural information' entries={preview.structure} />
      {preview.notes.map((note, index) => (
        <p key={index}>{note}</p>
      ))}
    </section>
  );
}
