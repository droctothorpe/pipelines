// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import Banner from './Banner';

describe('Banner', () => {
  it('defaults to error mode', () => {
    render(<Banner message={'Some message'} />);
    expect(screen.getByText('Some message')).toBeInTheDocument();
    expect(screen.getByTestId('ErrorIcon')).toBeInTheDocument();
    expect(screen.queryByTestId('WarningIcon')).toBeNull();
    expect(screen.queryByTestId('InfoIcon')).toBeNull();
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('uses error mode when instructed', () => {
    render(<Banner message={'Some message'} mode={'error'} />);
    expect(screen.getByTestId('ErrorIcon')).toBeInTheDocument();
    expect(screen.queryByRole('link')).toBeNull();
  });

  it('uses warning mode when instructed', () => {
    render(<Banner message={'Some message'} mode={'warning'} />);
    expect(screen.getByTestId('WarningIcon')).toBeInTheDocument();
    expect(screen.queryByTestId('ErrorIcon')).toBeNull();
  });

  it('uses info mode when instructed', () => {
    render(<Banner message={'Some message'} mode={'info'} />);
    expect(screen.getByTestId('InfoIcon')).toBeInTheDocument();
    expect(screen.queryByTestId('ErrorIcon')).toBeNull();
  });

  it('shows "Details" button and has dialog when there is additional info', () => {
    render(<Banner message={'Some message'} additionalInfo={'More info'} />);
    expect(screen.getByRole('button', { name: 'Details' })).toBeInTheDocument();
    // The dialog is mounted closed until Details is clicked.
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.queryByText('More info')).toBeNull();
  });

  it('shows "Refresh" button when passed a refresh function', () => {
    render(
      <Banner
        message={'Some message'}
        refresh={() => {
          /* do nothing */
        }}
      />,
    );
    expect(screen.getByRole('button', { name: 'Refresh' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Details' })).toBeNull();
  });

  it('does not show "Refresh" button if mode is "info"', () => {
    render(<Banner message={'Some message'} mode={'info'} refresh={() => undefined} />);
    expect(screen.queryByRole('button', { name: 'Refresh' })).toBeNull();
  });

  it('shows troubleshooting link instructed by prop', () => {
    render(<Banner message='Some message' mode='error' showTroubleshootingGuideLink={true} />);
    expect(screen.getByRole('link', { name: 'Troubleshooting guide' })).toHaveAttribute(
      'href',
      'https://www.kubeflow.org/docs/pipelines/troubleshooting',
    );
  });

  it('does not show troubleshooting link if warning', () => {
    render(<Banner message='Some message' mode='warning' showTroubleshootingGuideLink={true} />);
    expect(screen.queryByRole('link', { name: 'Troubleshooting guide' })).toBeNull();
  });

  it('opens details dialog when button is clicked', () => {
    render(<Banner message='hello' additionalInfo='world' />);
    fireEvent.click(screen.getByRole('button', { name: 'Details' }));
    const dialog = screen.getByRole('dialog');
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveTextContent('An error occurred');
    expect(dialog).toHaveTextContent('world');
  });

  it('closes details dialog when cancel button is clicked', async () => {
    render(<Banner message='hello' additionalInfo='world' />);
    fireEvent.click(screen.getByRole('button', { name: 'Details' }));
    const dismissButton = screen.getByRole('button', { name: 'Dismiss' });
    fireEvent.click(dismissButton);
    await waitFor(
      () => {
        expect(screen.queryByRole('dialog')).toBeNull();
      },
      { timeout: 10000 },
    );
  }, 15000);

  it('calls refresh callback', () => {
    const spy = vi.fn();
    render(<Banner message='hello' refresh={spy} />);
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    expect(spy).toHaveBeenCalled();
  });
});
