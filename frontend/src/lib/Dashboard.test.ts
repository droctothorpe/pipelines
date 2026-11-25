// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0

import { vi, describe, it, expect, afterEach } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { embedded, useDashboardNamespace } from './Dashboard';

const parent = { postMessage: vi.fn() };
function embed() {
  vi.spyOn(window, 'parent', 'get').mockReturnValue(parent as unknown as Window);
}
function message(data: unknown, options: Partial<MessageEventInit> = {}) {
  act(() => {
    window.dispatchEvent(
      new MessageEvent('message', {
        data,
        origin: window.location.origin,
        source: window.parent as unknown as MessageEventSource,
        ...options,
      }),
    );
  });
}
afterEach(() => {
  vi.restoreAllMocks();
  parent.postMessage.mockClear();
});

describe('useDashboardNamespace', () => {
  it('stays silent and undefined outside an iframe', () => {
    const { result } = renderHook(() => useDashboardNamespace());
    expect(embedded()).toBe(false);
    expect(result.current).toBeUndefined();
    expect(parent.postMessage).not.toHaveBeenCalled();
  });

  it('announces the frame and follows the namespace the dashboard selects', () => {
    embed();
    const { result } = renderHook(() => useDashboardNamespace());
    expect(embedded()).toBe(true);
    expect(parent.postMessage).toHaveBeenCalledWith(
      { type: 'iframe-connected' },
      window.location.origin,
    );
    message({ type: 'parent-connected', value: null });
    expect(result.current).toBeUndefined();
    message({ type: 'namespace-selected', value: 'team-a' });
    expect(result.current).toBe('team-a');
    message({ type: 'all-namespaces', value: ['team-a', 'team-b'] });
    expect(result.current).toBe('team-a');
    message({ type: 'namespace-selected', value: 'team-b' });
    expect(result.current).toBe('team-b');
  });

  it('ignores other origins, other windows and malformed names', () => {
    embed();
    const { result } = renderHook(() => useDashboardNamespace());
    message({ type: 'namespace-selected', value: 'evil' }, { origin: 'https://attacker.example' });
    message({ type: 'namespace-selected', value: 'other' }, { source: null });
    message({ type: 'namespace-selected', value: 'Not A Namespace' });
    message({ type: 'namespace-selected', value: { namespace: 'team' } });
    expect(result.current).toBeUndefined();
  });
});
