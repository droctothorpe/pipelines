// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { HelpButton } from './HelpButton';

describe('HelpButton', () => {
  it('gives the icon-only button an accessible name', () => {
    render(<HelpButton helpText='Some help text' />);
    expect(screen.getByRole('button', { name: 'Help' })).toBeInTheDocument();
  });
});
