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

import { fireEvent, render, screen } from '@testing-library/react';
import { forceRenderStyles, getStyles } from 'typestyle';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { logger } from '../lib/UiUtils';
import MD2Tabs from './MD2Tabs';

describe('MD2Tabs', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  /** The typestyle class only the active tab carries, with its rendered rule. */
  function activeRule(active: HTMLElement, inactive: HTMLElement): string {
    const extra = Array.from(active.classList).filter((name) => !inactive.classList.contains(name));
    expect(extra).toHaveLength(1);
    const match = getStyles().match(new RegExp(`\\.${extra[0]}\\{([^}]*)\\}`));
    expect(match).not.toBeNull();
    return match![1];
  }

  it('renders with the right styles by default', () => {
    const { container } = render(<MD2Tabs tabs={['tab1', 'tab2']} selectedTab={0} />);
    forceRenderStyles();
    const root = container.firstElementChild as HTMLElement;
    const indicator = root.firstElementChild as HTMLElement;
    expect(getComputedStyle(root).position).toBe('relative');
    expect(getComputedStyle(root).whiteSpace).toBe('nowrap');
    expect(getComputedStyle(indicator).position).toBe('absolute');
    expect(getComputedStyle(indicator).borderBottom).toMatch(/^3px solid /);
    expect(getComputedStyle(indicator).transition).toBe('width 0.3s, left 0.3s');
    const buttons = screen.getAllByRole('button');
    expect(buttons.map((button) => button.textContent)).toEqual(['tab1', 'tab2']);
    const rule = activeRule(buttons[0], buttons[1]);
    expect(rule).toContain('font-weight:bold');
    expect(rule).toMatch(/color:#1a73e8 !important/);
  });

  it('does not throw when clicking an unselected tab without onSwitch handler', () => {
    render(<MD2Tabs tabs={['tab1', 'tab2']} selectedTab={0} />);
    expect(() => fireEvent.click(screen.getByRole('button', { name: 'tab2' }))).not.toThrow();
  });

  it('calls the onSwitch function if an unselected button is clicked', () => {
    const switchHandler = vi.fn();
    render(<MD2Tabs tabs={['tab1', 'tab2']} selectedTab={0} onSwitch={switchHandler} />);
    fireEvent.click(screen.getByRole('button', { name: 'tab2' }));
    expect(switchHandler).toHaveBeenCalledWith(1);
  });

  it('does not call the onSwitch function if the already selected button is clicked', () => {
    const switchHandler = vi.fn();
    render(<MD2Tabs tabs={['tab1', 'tab2']} selectedTab={1} onSwitch={switchHandler} />);
    fireEvent.click(screen.getByRole('button', { name: 'tab2' }));
    expect(switchHandler).not.toHaveBeenCalled();
  });

  it('gracefully handles an out of bound selectedTab value', () => {
    const errorSpy = vi.spyOn(logger, 'error').mockImplementation(() => {});
    render(<MD2Tabs tabs={['tab1', 'tab2']} selectedTab={100} />);
    forceRenderStyles();
    expect(errorSpy).toHaveBeenCalledWith('Out of bound index passed for selected tab');
    // Falls back to the first tab as the active one.
    const buttons = screen.getAllByRole('button');
    expect(activeRule(buttons[0], buttons[1])).toContain('font-weight:bold');
  });

  it('centers the indicator under each selected label when switching tabs', () => {
    vi.useFakeTimers();
    const tabs = ['Graph', 'Detail', 'Pipeline Spec'];
    const { container, rerender } = render(<MD2Tabs tabs={tabs} selectedTab={0} />);
    const root = container.firstElementChild as HTMLElement;
    const indicator = root.firstElementChild as HTMLElement;
    vi.spyOn(root, 'getBoundingClientRect').mockReturnValue({ left: 220 } as DOMRect);
    const labelBounds = [
      { left: 255, width: 40.96875 },
      { left: 338.96875, width: 38.609375 },
      { left: 419.578125, width: 90.71875 },
    ];
    tabs.forEach((tab, index) => {
      vi.spyOn(screen.getByText(tab), 'getBoundingClientRect').mockReturnValue(
        labelBounds[index] as DOMRect,
      );
    });

    tabs.forEach((_, selectedTab) => {
      rerender(<MD2Tabs tabs={tabs} selectedTab={selectedTab} />);
      vi.runOnlyPendingTimers();
      const { left, width } = labelBounds[selectedTab];
      const indicatorLeft = parseFloat(indicator.style.left);
      const indicatorWidth = parseFloat(indicator.style.width);
      expect(indicatorWidth).toBe(width + 5);
      expect(indicatorLeft + indicatorWidth / 2).toBe(left - 220 + width / 2);
    });
  });

  it('recalculates indicator styles when props are updated', () => {
    vi.useFakeTimers();
    const updateSpy = vi.spyOn(MD2Tabs.prototype as any, '_updateIndicator');
    const { rerender } = render(<MD2Tabs tabs={['tab1', 'tab2']} selectedTab={0} />);
    vi.runOnlyPendingTimers();
    rerender(<MD2Tabs tabs={['tab1', 'tab2']} selectedTab={1} />);
    vi.runOnlyPendingTimers();
    expect(updateSpy.mock.calls.length).toBeGreaterThanOrEqual(2);
  });
});
