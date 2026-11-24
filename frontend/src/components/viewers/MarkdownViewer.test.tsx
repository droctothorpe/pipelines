// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import MarkdownViewer, { MarkdownViewerConfig } from './MarkdownViewer';
import { PlotType } from './Viewer';

describe('MarkdownViewer', () => {
  it('does not break on empty data', () => {
    const { container } = render(<MarkdownViewer configs={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders some basic markdown', () => {
    const markdown = '# Title\n[some link here](http://example.com)';
    const config: MarkdownViewerConfig = {
      markdownContent: markdown,
      type: PlotType.MARKDOWN,
    };

    const { container } = render(<MarkdownViewer configs={[config]} />);
    expect(container.firstElementChild).toHaveClass('markdown-viewer');
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Title');
    const link = screen.getByRole('link', { name: 'some link here' });
    expect(link).toHaveAttribute('href', 'http://example.com');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener');
  });

  it('sanitizes the markdown to remove XSS', () => {
    const markdown = `
lower[click me](javascript&#x3a;...)lower
upper[click me](javascript&#X3a;...)upper
plain[click me](javascript:alert(1))plain

<img src=x onerror="alert(1)">
<script>alert(1)</script>
    `;
    const config: MarkdownViewerConfig = {
      markdownContent: markdown,
      type: PlotType.MARKDOWN,
    };

    const { container } = render(<MarkdownViewer configs={[config]} />);
    // Link text still renders, but no javascript: href survives.
    expect(screen.getAllByText('click me')).toHaveLength(3);
    for (const anchor of Array.from(container.querySelectorAll('a'))) {
      expect(anchor.getAttribute('href') ?? '').not.toMatch(/javascript/i);
    }
    // Raw HTML is not parsed: it is shown as text, never as elements.
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('script')).toBeNull();
    expect(container).toHaveTextContent('<script>alert(1)</script>');
  });

  it('returns a user friendly display name', () => {
    expect(MarkdownViewer.prototype.getDisplayName()).toBe('Markdown');
  });

  it('capped at maximum markdown size', () => {
    const config: MarkdownViewerConfig = {
      markdownContent: 'X'.repeat(11),
      type: PlotType.MARKDOWN,
    };

    const maximumMarkdownSize = 10;
    const { getByText, queryByText } = render(
      <MarkdownViewer configs={[config]} maxLength={maximumMarkdownSize} />,
    );
    getByText('This markdown is too large to render completely.');
    getByText('X'.repeat(maximumMarkdownSize));
    expect(queryByText('X'.repeat(11))).toBeNull();
  });
});
