// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
/**
 * The Kubeflow central dashboard embeds applications in an iframe and tells
 * them the selected namespace over postMessage. This is the client side of
 * kubeflow/dashboard's centraldashboard `library.js`: announce the frame, then
 * follow `namespace-selected`. Stock loads that library from the dashboard; the
 * protocol is three message types, so the native UI speaks it directly.
 */
import { useEffect, useState } from 'react';

const APP_CONNECTED = 'iframe-connected';
const NAMESPACE_SELECTED = 'namespace-selected';
const NAMESPACE_LABEL = /^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$/;

/** Whether another page, such as the dashboard, hosts this one. */
export function embedded(): boolean {
  try {
    return window.parent !== window;
  } catch {
    return true;
  }
}

/** The namespace the hosting dashboard selected; undefined until it says. */
export function useDashboardNamespace(): string | undefined {
  const [namespace, setNamespace] = useState<string>();
  useEffect(() => {
    if (!embedded()) return;
    const onMessage = (event: MessageEvent) => {
      // Only the same-origin host that embeds this frame may choose a namespace.
      if (event.source !== window.parent || event.origin !== window.location.origin) return;
      const data = event.data as { type?: unknown; value?: unknown } | null;
      if (
        data?.type === NAMESPACE_SELECTED &&
        typeof data.value === 'string' &&
        NAMESPACE_LABEL.test(data.value)
      ) {
        setNamespace(data.value);
      }
      // `all-namespaces` has no native meaning: every resource is namespaced,
      // so the last selection stays.
    };
    window.addEventListener('message', onMessage);
    window.parent.postMessage({ type: APP_CONNECTED }, window.location.origin);
    return () => window.removeEventListener('message', onMessage);
  }, []);
  return namespace;
}
