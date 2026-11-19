// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { createContext, useContext } from 'react';
export interface Confirmation {
  title: string;
  content: string;
  action: () => Promise<unknown>;
}
export const NativeUiContext = createContext<{
  namespace: string;
  fail: (error: unknown) => void;
  confirm: (confirmation: Confirmation) => void;
}>({ namespace: 'argo', fail: () => {}, confirm: () => {} });
export const useNativeUi = () => useContext(NativeUiContext);
