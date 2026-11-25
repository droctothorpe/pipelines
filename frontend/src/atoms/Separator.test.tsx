// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import Separator from './Separator';

describe('Separator', () => {
  it('renders with the right styles by default', () => {
    const { container } = render(<Separator />);
    const separator = container.firstElementChild as HTMLElement;
    expect(separator.tagName).toBe('SPAN');
    expect(separator).toHaveStyle({ display: 'inline-block', minWidth: '10px', width: '10px' });
  });

  it('renders with the specified orientation', () => {
    const { container } = render(<Separator orientation='vertical' />);
    const separator = container.firstElementChild as HTMLElement;
    expect(separator).toHaveStyle({
      display: 'block',
      flexShrink: '0',
      height: '10px',
      minHeight: '10px',
    });
  });

  it('renders with the specified units', () => {
    const { container } = render(<Separator units={123} />);
    expect(container.firstElementChild).toHaveStyle({ minWidth: '123px', width: '123px' });
  });
});
