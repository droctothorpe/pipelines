/*
 * Copyright 2023 The Kubeflow Authors
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

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { color } from 'src/Css';
import { logger } from 'src/lib/UiUtils';
import { V2RuntimeState } from 'src/lib/NativeViewTypes';
import { statusToIcon } from './StatusV2';

describe('Status', () => {
  // The vitest setup pins TZ=UTC and en-US, so the formatted dates are stable.
  const startDate = new Date('Wed Jan 2 2019 9:10:11 GMT-0800');
  const endDate = new Date('Thu Jan 3 2019 10:11:12 GMT-0800');

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // MUI icons forward data-testid and take their color from style; the custom
  // running/terminated SVG icons paint their color through fill attributes.
  function icon(): SVGSVGElement {
    const svg = document.querySelector('svg');
    if (!svg) throw new Error('No status icon rendered');
    return svg;
  }

  function iconColor(): string | null {
    const svg = icon();
    if (svg.dataset.testid === 'node-status-sign') return svg.style.color;
    const filled = svg.querySelector('[fill]:not([fill="none"])');
    return filled ? filled.getAttribute('fill') : null;
  }

  function expectColor(expected: string): void {
    const actual = iconColor();
    expect(actual).not.toBeNull();
    // jsdom normalizes inline style colors to rgb(); compare both as rgb().
    expect(toRgb(actual!)).toBe(toRgb(expected));
  }

  function toRgb(value: string): string {
    const probe = document.createElement('div');
    probe.style.color = value;
    return probe.style.color;
  }

  async function openTooltip(): Promise<HTMLElement> {
    await userEvent.hover(icon().parentElement as HTMLElement);
    return screen.findByRole('tooltip');
  }

  describe('statusToIcon', () => {
    it('handles an unknown state', async () => {
      const verboseSpy = vi.spyOn(logger, 'verbose').mockImplementation(() => null);
      render(statusToIcon('bad state' as any));
      expectColor(color.inactive);
      expect(await openTooltip()).toHaveTextContent('Unknown status');
      expect(verboseSpy).toHaveBeenLastCalledWith('Unknown state:', 'bad state');
    });

    it('handles an undefined state', async () => {
      const verboseSpy = vi.spyOn(logger, 'verbose').mockImplementation(() => null);
      render(statusToIcon(/* no phase */));
      expectColor(color.inactive);
      expect(await openTooltip()).toHaveTextContent('Unknown status');
      expect(verboseSpy).not.toHaveBeenCalled();
    });

    it('handles FAILED state', async () => {
      render(statusToIcon(V2RuntimeState.FAILED));
      expectColor(color.errorText);
      expect(await openTooltip()).toHaveTextContent('Resource failed to execute');
    });

    it('handles PENDING state', async () => {
      render(statusToIcon(V2RuntimeState.PENDING));
      expectColor(color.weak);
      expect(await openTooltip()).toHaveTextContent('Pending execution');
    });

    it('handles RUNNING state', async () => {
      render(statusToIcon(V2RuntimeState.RUNNING));
      expectColor(color.blue);
      expect(await openTooltip()).toHaveTextContent('Running');
    });

    it('handles CANCELING state', async () => {
      render(statusToIcon(V2RuntimeState.CANCELING));
      expectColor(color.blue);
      expect(await openTooltip()).toHaveTextContent('Run is canceling');
    });

    it('handles SKIPPED state', async () => {
      render(statusToIcon(V2RuntimeState.SKIPPED));
      expectColor(color.inactive);
      expect(await openTooltip()).toHaveTextContent('Execution has been skipped for this resource');
    });

    it('handles SUCCEEDED state', async () => {
      render(statusToIcon(V2RuntimeState.SUCCEEDED));
      expectColor(color.success);
      expect(await openTooltip()).toHaveTextContent('Executed successfully');
    });

    it('handles CANCELED state', async () => {
      render(statusToIcon(V2RuntimeState.CANCELED));
      expectColor(color.terminated);
      expect(await openTooltip()).toHaveTextContent('Run was manually canceled');
    });

    it('displays start and end dates if both are provided', async () => {
      render(statusToIcon(V2RuntimeState.SUCCEEDED, startDate, endDate));
      const tooltip = await openTooltip();
      expect(tooltip).toHaveTextContent(`Start: ${startDate.toLocaleString()}`);
      expect(tooltip).toHaveTextContent(`End: ${endDate.toLocaleString()}`);
    });

    it('does not display a end date if none was provided', async () => {
      render(statusToIcon(V2RuntimeState.SUCCEEDED, startDate));
      const tooltip = await openTooltip();
      expect(tooltip).toHaveTextContent(`Start: ${startDate.toLocaleString()}`);
      expect(tooltip).not.toHaveTextContent('End:');
    });

    it('does not display a start date if none was provided', async () => {
      render(statusToIcon(V2RuntimeState.SUCCEEDED, undefined, endDate));
      const tooltip = await openTooltip();
      expect(tooltip).not.toHaveTextContent('Start:');
      expect(tooltip).toHaveTextContent(`End: ${endDate.toLocaleString()}`);
    });

    it('does not display any dates if neither was provided', async () => {
      render(statusToIcon(V2RuntimeState.SUCCEEDED /* No dates */));
      const tooltip = await openTooltip();
      expect(tooltip).toHaveTextContent('Executed successfully');
      expect(tooltip).not.toHaveTextContent('Start:');
      expect(tooltip).not.toHaveTextContent('End:');
    });

    it('treats a FAILED node whose message is "terminated" as CANCELED', async () => {
      render(statusToIcon(V2RuntimeState.FAILED, undefined, undefined, 'terminated'));
      expectColor(color.terminated);
      expect(await openTooltip()).toHaveTextContent('Run was manually canceled');
    });

    Object.keys(V2RuntimeState).forEach((status) =>
      it('renders an icon with tooltip for phase: ' + status, async () => {
        const verboseSpy = vi.spyOn(logger, 'verbose').mockImplementation(() => null);
        render(statusToIcon(V2RuntimeState[status as keyof typeof V2RuntimeState]));
        expect(icon()).toBeInTheDocument();
        expect(iconColor()).not.toBeNull();
        expect((await openTooltip()).textContent).not.toBe('');
        // Every enumerated state is a known state.
        expect(verboseSpy).not.toHaveBeenCalled();
      }),
    );
  });
});
