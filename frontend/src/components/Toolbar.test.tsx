// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import * as React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import HelpIcon from '@mui/icons-material/Help';
import InfoIcon from '@mui/icons-material/Info';
import { commonCss } from '../Css';
import Toolbar, { ToolbarActionMap } from './Toolbar';

const action1 = vi.fn();
const action2 = vi.fn();
const actions: ToolbarActionMap = {
  action1: {
    action: action1,
    disabledTitle: 'test disabled title',
    icon: HelpIcon,
    id: 'test id',
    title: 'test title',
    tooltip: 'test tooltip',
  },
  action2: {
    action: action2,
    disabled: true,
    disabledTitle: 'test disabled title2',
    icon: InfoIcon,
    id: 'test id2',
    title: 'test title2',
    tooltip: 'test tooltip2',
  },
};

const breadcrumbs = [
  {
    displayName: 'test display name',
    href: '/some/test/path',
  },
  {
    displayName: 'test display name2',
    href: '/some/test/path2',
  },
];

const navigate = vi.fn();

function renderWithRouter(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

describe('Toolbar', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window.history, 'length', 'get').mockReturnValue(2);
  });

  afterEach(() => vi.restoreAllMocks());

  it('navigates Back through the native navigation function', () => {
    renderWithRouter(
      <Toolbar breadcrumbs={breadcrumbs} actions={{}} navigate={navigate} pageTitle='' />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(navigate).toHaveBeenCalledWith(-1);
  });

  it('disables Back when the browser has no previous entry', () => {
    vi.spyOn(window.history, 'length', 'get').mockReturnValue(1);
    renderWithRouter(
      <Toolbar breadcrumbs={breadcrumbs} actions={{}} navigate={navigate} pageTitle='' />,
    );
    expect(screen.getByRole('button', { name: 'Back' })).toBeDisabled();
  });

  it('renders nothing when there are no breadcrumbs or actions', () => {
    const { container } = render(
      <Toolbar breadcrumbs={[]} actions={{}} navigate={navigate} pageTitle='' />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders without breadcrumbs and a string page title', () => {
    renderWithRouter(
      <Toolbar
        breadcrumbs={[]}
        actions={actions}
        navigate={navigate}
        pageTitle='test page title'
      />,
    );
    expect(screen.getByTestId('page-title')).toHaveTextContent('test page title');
    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Back' })).toBeNull();
    expect(screen.getByRole('button', { name: 'test title' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'test title2' })).toBeDisabled();
  });

  it('renders without breadcrumbs and a component page title', () => {
    const { container } = renderWithRouter(
      <Toolbar
        breadcrumbs={[]}
        actions={actions}
        navigate={navigate}
        pageTitle={<div id='myComponent'>test page title</div>}
      />,
    );
    const title = container.querySelector('#myComponent');
    expect(title).toHaveTextContent('test page title');
    expect(screen.getByTestId('page-title')).toContainElement(title as HTMLElement);
  });

  it('renders without breadcrumbs and one action', () => {
    const singleAction = {
      action1: {
        action: action1,
        disabledTitle: 'test disabled title',
        icon: HelpIcon,
        id: 'test id',
        title: 'test title',
        tooltip: 'test tooltip',
      },
    };
    renderWithRouter(
      <Toolbar
        breadcrumbs={[]}
        actions={singleAction}
        navigate={navigate}
        pageTitle='test page title'
      />,
    );
    const buttons = screen.getAllByRole('button');
    expect(buttons).toHaveLength(1);
    expect(buttons[0]).toHaveTextContent('test title');
    expect(buttons[0]).toHaveAttribute('id', 'test id');
    expect(buttons[0]).toContainElement(screen.getByTestId('HelpIcon'));
  });

  it('renders without actions and one breadcrumb', () => {
    renderWithRouter(
      <Toolbar
        breadcrumbs={[breadcrumbs[0]]}
        actions={{}}
        navigate={navigate}
        pageTitle='test page title'
      />,
    );
    const links = screen.getAllByRole('link');
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveTextContent('test display name');
    expect(links[0]).toHaveAttribute('href', '/some/test/path');
    expect(screen.queryByTestId('ChevronRightIcon')).toBeNull();
    expect(screen.getAllByRole('button')).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Back' })).toBeEnabled();
  });

  it('renders without actions, one breadcrumb, and a page name', () => {
    renderWithRouter(
      <Toolbar
        breadcrumbs={[breadcrumbs[0]]}
        actions={{}}
        navigate={navigate}
        pageTitle='test page title'
      />,
    );
    expect(screen.getByRole('link', { name: 'test display name' })).toBeInTheDocument();
    expect(screen.getByTestId('page-title')).toHaveTextContent('test page title');
    expect(screen.getByTestId('page-title')).not.toHaveAttribute('title');
  });

  it('renders without breadcrumbs and two actions', () => {
    renderWithRouter(
      <Toolbar
        breadcrumbs={[]}
        actions={actions}
        navigate={navigate}
        pageTitle='test page title'
      />,
    );
    const buttons = screen.getAllByRole('button');
    expect(buttons.map((button) => button.textContent)).toEqual(['test title', 'test title2']);
    expect(buttons.map((button) => button.id)).toEqual(['test id', 'test id2']);
    expect(buttons[0]).toBeEnabled();
    expect(buttons[1]).toBeDisabled();
    expect(screen.getByTestId('HelpIcon')).toBeInTheDocument();
    expect(screen.getByTestId('InfoIcon')).toBeInTheDocument();
  });

  it('fires the right action function when button is clicked', () => {
    renderWithRouter(
      <Toolbar
        breadcrumbs={[]}
        actions={actions}
        navigate={navigate}
        pageTitle='test page title'
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'test title' }));
    expect(action1).toHaveBeenCalled();
    expect(action2).not.toHaveBeenCalled();
  });

  it('renders outlined action buttons', () => {
    const outlinedActions = {
      action1: {
        action: vi.fn(),
        id: 'test outlined id',
        outlined: true,
        title: 'test outlined title',
        tooltip: 'test outlined tooltip',
      },
    };

    renderWithRouter(
      <Toolbar
        breadcrumbs={breadcrumbs}
        actions={outlinedActions}
        pageTitle=''
        navigate={navigate}
      />,
    );
    const button = screen.getByRole('button', { name: 'test outlined title' });
    expect(button).toHaveAttribute('id', 'test outlined id');
    expect(button).toHaveClass('MuiButton-textPrimary');
    expect(button).not.toHaveClass(commonCss.buttonAction);
  });

  it('renders primary action buttons', () => {
    const primaryActions = {
      action1: {
        action: vi.fn(),
        id: 'test primary id',
        primary: true,
        title: 'test primary title',
        tooltip: 'test primary tooltip',
      },
    };

    renderWithRouter(
      <Toolbar
        breadcrumbs={breadcrumbs}
        actions={primaryActions}
        pageTitle=''
        navigate={navigate}
      />,
    );
    const button = screen.getByRole('button', { name: 'test primary title' });
    expect(button).toHaveAttribute('id', 'test primary id');
    expect(button).toHaveClass(commonCss.buttonAction);
    expect(button).toHaveClass('MuiButton-textSecondary');
  });

  it('renders primary action buttons without outline, even if outline is true', () => {
    const outlinedPrimaryActions = {
      action1: {
        action: vi.fn(),
        id: 'test id',
        outlined: true,
        primary: true,
        title: 'test title',
        tooltip: 'test tooltip',
      },
    };

    renderWithRouter(
      <Toolbar
        breadcrumbs={breadcrumbs}
        actions={outlinedPrimaryActions}
        pageTitle=''
        navigate={navigate}
      />,
    );
    const button = screen.getByRole('button', { name: 'test title' });
    expect(button).toHaveClass(commonCss.buttonAction);
    expect(button).toHaveClass('MuiButton-textSecondary');
    expect(button).not.toHaveClass('MuiButton-textPrimary');
  });

  it('renders with two breadcrumbs and two actions', () => {
    renderWithRouter(
      <Toolbar breadcrumbs={breadcrumbs} actions={actions} pageTitle='' navigate={navigate} />,
    );
    const links = screen.getAllByRole('link');
    expect(links.map((link) => link.textContent)).toEqual([
      'test display name',
      'test display name2',
    ]);
    expect(links.map((link) => link.getAttribute('href'))).toEqual([
      '/some/test/path',
      '/some/test/path2',
    ]);
    expect(screen.getAllByTestId('ChevronRightIcon')).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Back' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'test title' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'test title2' })).toBeDisabled();
    expect(screen.getByTestId('page-title')).toHaveTextContent('');
  });
});
