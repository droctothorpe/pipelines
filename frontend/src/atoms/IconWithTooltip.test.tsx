// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { render, screen } from '@testing-library/react';
import TestIcon from '@mui/icons-material/Help';
import { describe, expect, it } from 'vitest';
import IconWithTooltip from './IconWithTooltip';

describe('IconWithTooltip', () => {
  it('renders without height or weight', () => {
    render(<IconWithTooltip Icon={TestIcon} iconColor='green' tooltip='test icon tooltip' />);
    const icon = screen.getByTestId('HelpIcon');
    expect(icon).toHaveStyle({ color: 'rgb(0, 128, 0)', height: '16px', width: '16px' });
    expect(icon).toHaveAttribute('aria-label', 'test icon tooltip');
  });

  it('renders with height and weight', () => {
    render(
      <IconWithTooltip
        Icon={TestIcon}
        height={20}
        width={20}
        iconColor='green'
        tooltip='test icon tooltip'
      />,
    );
    expect(screen.getByTestId('HelpIcon')).toHaveStyle({
      color: 'rgb(0, 128, 0)',
      height: '20px',
      width: '20px',
    });
  });
});
