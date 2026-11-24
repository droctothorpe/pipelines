/*
 * Copyright 2018 The Kubeflow Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * https://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import * as React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { commonCss } from '../Css';
import DetailsTable, { css } from './DetailsTable';

vi.mock('./Editor', () => ({
  default: ({ value }: { value: string }) => <pre data-testid='Editor'>{value}</pre>,
}));

/** Read each rendered row as [key, value text, rendered-as-json]. */
function rows(container: HTMLElement): Array<[string, string, boolean]> {
  return Array.from(container.querySelectorAll(`.${css.row}`)).map((row) => {
    const key = row.querySelector(`.${css.key}`) as HTMLElement;
    const editor = row.querySelector('[data-testid="Editor"]');
    const value = editor ?? (row.querySelector(`.${css.valueText}`) as HTMLElement);
    return [key.textContent || '', value.textContent || '', editor !== null];
  });
}

describe('DetailsTable', () => {
  it('shows no rows', () => {
    const { container } = render(<DetailsTable fields={[]} />);
    expect(rows(container)).toEqual([]);
    expect(container.querySelector(`.${commonCss.header2}`)).toBeNull();
    expect(container.innerHTML).toBe('<div></div>');
  });

  it('shows one row', () => {
    const { container } = render(<DetailsTable fields={[['key', 'value']]} />);
    expect(rows(container)).toEqual([['key', 'value', false]]);
    expect(container.querySelector(`.${commonCss.header2}`)).toBeNull();
  });

  it('shows a row with a title', () => {
    const { container } = render(<DetailsTable title='some title' fields={[['key', 'value']]} />);
    const title = container.querySelector(`.${commonCss.header2}`);
    expect(title).toHaveTextContent('some title');
    expect(title?.nextElementSibling).toContainElement(screen.getByText('key'));
    expect(rows(container)).toEqual([['key', 'value', false]]);
  });

  it('shows key and value for large values', () => {
    const value = `Lorem Ipsum is simply dummy text of the printing and typesetting
      industry. Lorem Ipsum has been the industry's standard dummy text ever
      since the 1500s, when an unknown printer took a galley of type and
      scrambled it to make a type specimen book. It has survived not only five
      centuries, but also the leap into electronic typesetting, remaining
      essentially unchanged. It was popularised in the 1960s with the release
      of Letraset sheets containing Lorem Ipsum passages, and more recently
      with desktop publishing software like Aldus PageMaker including versions
      of Lorem Ipsum.`;
    const { container } = render(<DetailsTable fields={[['key', value]]} />);
    expect(rows(container)).toEqual([['key', value, false]]);
  });

  it('shows key and value in row', () => {
    const { container } = render(<DetailsTable fields={[['key', 'value']]} />);
    const row = container.querySelector(`.${css.row}`) as HTMLElement;
    expect(row.children).toHaveLength(2);
    expect(row.children[0]).toHaveClass(css.key);
    expect(row.children[0]).toHaveTextContent('key');
    expect(row.children[1]).toHaveClass(css.valueText);
    expect(row.children[1]).toHaveTextContent('value');
  });

  it('shows key and JSON value in row', () => {
    const { container } = render(
      <DetailsTable fields={[['key', JSON.stringify([{ jsonKey: 'jsonValue' }])]]} />,
    );
    expect(rows(container)).toEqual([
      ['key', JSON.stringify([{ jsonKey: 'jsonValue' }], null, 2), true],
    ]);
  });

  it('does render arrays as JSON', () => {
    const { container } = render(<DetailsTable fields={[['key', '[]']]} />);
    expect(rows(container)).toEqual([['key', '[]', true]]);
  });

  it('does render empty object as JSON', () => {
    const { container } = render(<DetailsTable fields={[['key', '{}']]} />);
    expect(rows(container)).toEqual([['key', '{}', true]]);
  });

  it('does not render nulls as JSON', () => {
    const { container } = render(<DetailsTable fields={[['key', 'null']]} />);
    expect(rows(container)).toEqual([['key', 'null', false]]);
  });

  it('does not render numbers as JSON', () => {
    const { container } = render(<DetailsTable fields={[['key', '10']]} />);
    expect(rows(container)).toEqual([['key', '10', false]]);
  });

  it('does not render strings as JSON', () => {
    const { container } = render(<DetailsTable fields={[['key', '"some string"']]} />);
    expect(rows(container)).toEqual([['key', '"some string"', false]]);
  });

  it('does not render booleans as JSON', () => {
    const { container } = render(
      <DetailsTable
        fields={[
          ['key1', 'true'],
          ['key2', 'false'],
        ]}
      />,
    );
    expect(rows(container)).toEqual([
      ['key1', 'true', false],
      ['key2', 'false', false],
    ]);
  });

  it('shows keys and values for multiple rows', () => {
    const { container } = render(
      <DetailsTable
        fields={[
          ['key1', 'value1'],
          ['key2', JSON.stringify([{ jsonKey: 'jsonValue2' }])],
          ['key3', 'value3'],
          ['key4', 'value4'],
          ['key5', JSON.stringify({ jsonKey: { nestedJsonKey: 'jsonValue' } })],
          ['key6', 'value6'],
          ['key6', 'value7'],
          ['key', { key: 'foobar', bucket: 'bucket', endpoint: 's3.amazonaws.com' }],
        ]}
      />,
    );
    expect(rows(container)).toEqual([
      ['key1', 'value1', false],
      ['key2', JSON.stringify([{ jsonKey: 'jsonValue2' }], null, 2), true],
      ['key3', 'value3', false],
      ['key4', 'value4', false],
      ['key5', JSON.stringify({ jsonKey: { nestedJsonKey: 'jsonValue' } }, null, 2), true],
      ['key6', 'value6', false],
      ['key6', 'value7', false],
      // Non-string values fall back to string coercion without a valueComponent.
      ['key', '[object Object]', false],
    ]);
  });

  it('does render values with the provided valueComponent', () => {
    const ValueComponent: React.FC<any> = ({ value, ...rest }) => (
      <a data-testid='value-component' {...rest}>
        {JSON.stringify(value)}
      </a>
    );
    const { getByTestId } = render(
      <DetailsTable
        fields={[['key2', { key: 'foobar', bucket: 'bucket', endpoint: 's3.amazonaws.com' }]]}
        valueComponent={ValueComponent}
        valueComponentProps={{ extraprop: 'extra' }}
      />,
    );
    const rendered = getByTestId('value-component');
    expect(rendered.tagName).toBe('A');
    expect(rendered).toHaveAttribute('extraprop', 'extra');
    expect(rendered).toHaveTextContent(
      '{"key":"foobar","bucket":"bucket","endpoint":"s3.amazonaws.com"}',
    );
    expect(rendered.parentElement).toHaveClass(css.valueText);
  });
});
