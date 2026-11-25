// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import NativeParameterInput from './NativeParameterInput';

it('keeps None, empty and literal null strings distinct', () => {
  const onChange = vi.fn();
  const view = render(
    <NativeParameterInput
      name='value'
      kind='NullableString'
      value='null'
      required={false}
      onChange={onChange}
    />,
  );
  expect(screen.getByRole('checkbox', { name: 'Use None for value' })).toBeChecked();
  expect(screen.getByLabelText('value')).toBeDisabled();
  fireEvent.click(screen.getByRole('checkbox', { name: 'Use None for value' }));
  expect(onChange).toHaveBeenLastCalledWith('""');
  view.rerender(
    <NativeParameterInput
      name='value'
      kind='NullableString'
      value='""'
      required={false}
      onChange={onChange}
    />,
  );
  fireEvent.change(screen.getByLabelText('value'), { target: { value: 'null' } });
  expect(onChange).toHaveBeenLastCalledWith('"null"');
  fireEvent.click(screen.getByRole('checkbox', { name: 'Use None for value' }));
  expect(onChange).toHaveBeenLastCalledWith('null');
});

it('does not change ordinary string parameter editing', () => {
  const onChange = vi.fn();
  render(
    <NativeParameterInput
      name='text'
      kind='String'
      value='hello'
      required={false}
      onChange={onChange}
    />,
  );
  expect(screen.queryByRole('checkbox')).toBeNull();
  fireEvent.change(screen.getByLabelText('text'), { target: { value: 'null' } });
  expect(onChange).toHaveBeenLastCalledWith('null');
});
