// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import Input from './Input';

describe('Input', () => {
  const handleChange = vi.fn();
  const value = 'some input value';

  it('renders with the right styles by default', () => {
    render(<Input onChange={handleChange} value={value} variant='outlined' />);
    const input = screen.getByDisplayValue(value);
    const root = input.closest('.MuiFormControl-root') as HTMLElement;
    expect(root).toHaveStyle({ height: '40px', maxWidth: '600px', width: '100%' });
    expect(root).toHaveAttribute('spellcheck', 'false');
    expect(input.closest('.MuiOutlinedInput-root')).not.toBeNull();
  });

  it('accepts height and width as prop overrides', () => {
    render(
      <Input height={123} width={456} onChange={handleChange} value={value} variant='outlined' />,
    );
    const root = screen.getByDisplayValue(value).closest('.MuiFormControl-root');
    expect(root).toHaveStyle({ height: '123px', maxWidth: '600px', width: '456px' });
  });
});
