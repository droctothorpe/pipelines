/*
 * Copyright 2019 The Kubeflow Authors
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
import { describe, expect, it } from 'vitest';
import { Description } from './Description';

/** Collapse whitespace: inline mode keeps source newlines as text. */
function text(container: HTMLElement): string {
  return (container.textContent || '').replace(/\s+/g, ' ').trim();
}

function expectExternalLink(link: HTMLElement, href: string, text: string): void {
  expect(link.tagName).toBe('A');
  expect(link).toHaveAttribute('href', href);
  expect(link).toHaveAttribute('target', '_blank');
  expect(link).toHaveAttribute('rel', 'noopener');
  expect(link).toHaveTextContent(text);
}

describe('Description', () => {
  describe('When in normal mode', () => {
    it('renders empty string', () => {
      const { container } = render(<Description description='' />);
      expect(container.innerHTML).toBe('<span></span>');
    });

    it('renders pure text', () => {
      const { container } = render(<Description description='this is a line of pure text' />);
      expect(container.innerHTML).toBe('<span>this is a line of pure text</span>');
    });

    it('renders raw link', () => {
      const description = 'https://www.google.com';
      render(<Description description={description} />);
      expectExternalLink(screen.getByRole('link'), description, description);
    });

    it('renders markdown link', () => {
      const description = '[google](https://www.google.com)';
      render(<Description description={description} />);
      expectExternalLink(screen.getByRole('link'), 'https://www.google.com', 'google');
    });

    it('renders paragraphs', () => {
      const description = 'Paragraph 1\n' + '\n' + 'Paragraph 2';
      const { container } = render(<Description description={description} />);
      const paragraphs = container.querySelectorAll('p');
      expect(Array.from(paragraphs).map((p) => p.textContent)).toEqual([
        'Paragraph 1',
        'Paragraph 2',
      ]);
    });

    it('renders markdown list as list', () => {
      const description = `
* abc
* def`;
      render(<Description description={description} />);
      expect(screen.getByRole('list')).toBeInTheDocument();
      expect(screen.getAllByRole('listitem').map((item) => item.textContent)).toEqual([
        'abc',
        'def',
      ]);
    });
  });

  describe('When in inline mode', () => {
    it('renders paragraphs separated by space', () => {
      const description = `
Paragraph 1

Paragraph 2
`;
      const { container } = render(<Description description={description} forceInline={true} />);
      expect(container.querySelector('p')).toBeNull();
      expect(text(container)).toBe('Paragraph 1 Paragraph 2');
    });

    it('renders pure text', () => {
      const { container } = render(
        <Description description='this is a line of pure text' forceInline={true} />,
      );
      expect(container.innerHTML).toBe('<span>this is a line of pure text</span>');
    });

    it('renders raw link', () => {
      const description = 'https://www.google.com';
      render(<Description description={description} forceInline={true} />);
      expectExternalLink(screen.getByRole('link'), description, description);
    });

    it('renders markdown link', () => {
      const description = '[google](https://www.google.com)';
      render(<Description description={description} forceInline={true} />);
      expectExternalLink(screen.getByRole('link'), 'https://www.google.com', 'google');
    });

    it('renders markdown list as pure text with visible bullet markers', () => {
      const description = `
* abc
* def`;
      const { container } = render(<Description description={description} forceInline={true} />);
      expect(screen.queryByRole('list')).toBeNull();
      expect(container.querySelector('em')).toBeNull();
      expect(text(container)).toBe('• abc • def');
    });

    it('renders emphasis text as <em>', () => {
      const { container } = render(<Description description='*abc*' forceInline={true} />);
      const em = container.querySelector('em');
      expect(em).toHaveTextContent('abc');
      expect(container.textContent).toBe('abc');
    });

    it('renders strong text as <strong>', () => {
      const { container } = render(<Description description='**abc**' forceInline={true} />);
      const strong = container.querySelector('strong');
      expect(strong).toHaveTextContent('abc');
      expect(container.textContent).toBe('abc');
    });

    it('renders list markers as visible bullets while preserving emphasis', () => {
      const description = `* item one\n- item two\n+ item three`;
      const { container } = render(<Description description={description} forceInline={true} />);
      expect(screen.queryByRole('list')).toBeNull();
      expect(text(container)).toBe('• item one • item two • item three');
      const { container: emphasized } = render(
        <Description description='* *one* and **two**' forceInline={true} />,
      );
      expect(emphasized.querySelector('em')).toHaveTextContent('one');
      expect(emphasized.querySelector('strong')).toHaveTextContent('two');
      expect(text(emphasized)).toBe('• one and two');
    });
  });
});
