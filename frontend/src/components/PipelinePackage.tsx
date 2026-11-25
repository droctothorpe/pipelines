// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { padding } from 'src/Css';
import { ExternalLink } from 'src/atoms/ExternalLink';

export const PIPELINE_PACKAGE_ACCEPT = { 'application/yaml': ['.yaml', '.yml'] };
export function pipelinePackageValidator(file: File) {
  return /\.ya?ml$/i.test(file.name)
    ? null
    : {
        code: 'invalid-extension',
        message: 'Choose a compiled native WorkflowTemplate YAML file.',
      };
}
export function DocumentationCompilePipeline() {
  return (
    <div className={padding(10, 'b')}>
      For expected file format, refer to{' '}
      <ExternalLink href='https://www.kubeflow.org/docs/components/pipelines/v2/compile-a-pipeline/'>
        Compile Pipeline Documentation
      </ExternalLink>
      .
    </div>
  );
}
