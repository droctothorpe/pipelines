// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { render, screen } from '@testing-library/react';
import TestIcon from '@mui/icons-material/Help';
import { describe, expect, it } from 'vitest';
import BusyButton from './BusyButton';

describe('BusyButton', () => {
  it('renders with just a title', () => {
    render(<BusyButton title='test busy button' />);
    const button = screen.getByRole('button', { name: 'test busy button' });
    expect(button).toBeEnabled();
    expect(button).toHaveClass('MuiButton-textSecondary');
    expect(button.querySelector('svg')).toBeNull();
    expect(screen.queryByRole('progressbar')).toBeNull();
  });

  it('renders with a title and icon', () => {
    render(<BusyButton title='test busy button' icon={TestIcon} />);
    const button = screen.getByRole('button', { name: 'test busy button' });
    expect(button).toContainElement(screen.getByTestId('HelpIcon'));
    expect(screen.queryByRole('progressbar')).toBeNull();
  });

  it('renders with a title and icon, and busy', () => {
    render(<BusyButton title='test busy button' icon={TestIcon} busy={true} />);
    const button = screen.getByRole('button', { name: 'test busy button' });
    expect(button).toBeDisabled();
    expect(button).toContainElement(screen.getByTestId('HelpIcon'));
    expect(button).toContainElement(screen.getByRole('progressbar'));
  });

  it('renders disabled', () => {
    render(<BusyButton title='test busy button' icon={TestIcon} disabled={true} />);
    expect(screen.getByRole('button', { name: 'test busy button' })).toBeDisabled();
    expect(screen.queryByRole('progressbar')).toBeNull();
  });

  it('renders a primary outlined buton', () => {
    render(<BusyButton title='test busy button' outlined={true} />);
    const button = screen.getByRole('button', { name: 'test busy button' });
    expect(button).toHaveClass('MuiButton-textPrimary');
    expect(button).not.toHaveClass('MuiButton-textSecondary');
  });
});
