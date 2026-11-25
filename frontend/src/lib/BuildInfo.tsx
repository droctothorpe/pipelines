// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { createContext } from 'react';
import type { BuildInfo } from './NativeViewTypes';
// No healthz or KFP backend provider is mounted. This is presentation metadata only.
export const BuildInfoContext = createContext<BuildInfo | undefined>(undefined);
