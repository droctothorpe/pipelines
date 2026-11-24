// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import CollapseButtonSingle from './CollapseButtonSingle';

describe('CollapseButtonSingle', () => {
  const collapseSectionUpdateSpy = vi.fn();

  it('Collapes an expanded section when clicked', () => {
    render(
      <CollapseButtonSingle
        collapseSection={false}
        collapseSectionUpdate={collapseSectionUpdateSpy}
        sectionName='testSection'
      />,
    );

    fireEvent.click(screen.getByText('testSection'));
    expect(collapseSectionUpdateSpy).toHaveBeenCalledWith(true);
  });

  it('Expands a collapsed section when clicked', () => {
    render(
      <CollapseButtonSingle
        collapseSection={true}
        collapseSectionUpdate={collapseSectionUpdateSpy}
        sectionName='testSection'
      />,
    );

    fireEvent.click(screen.getByText('testSection'));
    expect(collapseSectionUpdateSpy).toHaveBeenCalledWith(false);
  });
});
