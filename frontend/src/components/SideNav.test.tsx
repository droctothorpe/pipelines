// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import * as React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LocalStorage, LocalStorageKey } from '../lib/LocalStorage';
import { BuildInfoContext } from '../lib/BuildInfo';
import { ExternalLinks, RoutePage } from './Router';
import EnhancedSideNav, { css, SideNav } from './SideNav';

const wideWidth = 1000;
const narrowWidth = 200;

const defaultProps = {
  gkeMetadata: {},
  buildInfo: {
    apiServerCommitHash: '0a7b9e38f2b9bcdef4bbf3234d971e1635b50cd5',
    apiServerTagName: '1.0.0',
    apiServerReady: true,
    buildDate: 'Tue Oct 23 14:23:53 UTC 2018',
    frontendCommitHash: '302e93ce99099173f387c7e0635476fe1b69ea98',
    frontendTagName: '1.0.0-rc1',
  },
};

// Native detail routes that stock named through RoutePage constants.
const pages = {
  pipelineDetails: `${RoutePage.PIPELINES}/details/pipeline-1`,
  experimentDetails: `${RoutePage.EXPERIMENTS}/details/experiment-1`,
  newExperiment: `${RoutePage.EXPERIMENTS}/new`,
  runDetails: `${RoutePage.RUNS}/details/run-1`,
  newRun: `${RoutePage.RUNS}/new`,
  recurringRunDetails: '/recurringrun/details/schedule-1',
};

const navButtons = ['Pipelines', 'Experiments', 'Runs', 'Recurring Runs', 'Artifacts'];

function isCollapsed(): boolean {
  const root = screen.getByTestId('sideNav');
  return root.classList.contains(css.collapsedRoot);
}

function renderSideNav(
  page: string,
  overrides: Partial<React.ComponentProps<typeof SideNav>> = {},
) {
  const ref = React.createRef<SideNav>();
  const props = {
    ...defaultProps,
    ...overrides,
    page,
  } as React.ComponentProps<typeof SideNav>;
  const renderResult = render(
    <MemoryRouter>
      <SideNav ref={ref} {...props} />
    </MemoryRouter>,
  );
  if (!ref.current) {
    throw new Error('SideNav instance not available');
  }
  return { renderResult, instance: ref.current };
}

/** Asserts exactly one navigation button carries the active styling. */
function expectActive(name: string): void {
  for (const label of navButtons) {
    const button = screen.getByRole('button', { name: label });
    if (label === name) {
      expect(button).toHaveClass(css.active);
    } else {
      expect(button).not.toHaveClass(css.active);
    }
  }
}

function expectNoneActive(): void {
  for (const label of navButtons) {
    expect(screen.getByRole('button', { name: label })).not.toHaveClass(css.active);
  }
}

describe('SideNav', () => {
  it('keeps namespace transfer out of the sidebar', () => {
    renderSideNav(RoutePage.PIPELINES);
    expect(screen.queryByRole('link', { name: 'Export / Import' })).not.toBeInTheDocument();
    expect(screen.queryByText(/transfer/i)).not.toBeInTheDocument();
  });

  let localStorageHasKeySpy: ReturnType<typeof vi.spyOn>;
  let localStorageIsCollapsedSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    localStorage.clear();
    localStorageHasKeySpy = vi.spyOn(LocalStorage, 'hasKey').mockImplementation(() => false);
    localStorageIsCollapsedSpy = vi
      .spyOn(LocalStorage, 'isNavbarCollapsed')
      .mockImplementation(() => false);
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    (window as any).innerWidth = wideWidth;
  });

  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
    (window as any).innerWidth = wideWidth;
  });

  it('renders expanded state', async () => {
    localStorageHasKeySpy.mockImplementationOnce(() => false);
    (window as any).innerWidth = wideWidth;
    renderSideNav(RoutePage.PIPELINES);
    await waitFor(() => expect(isCollapsed()).toBe(false));

    for (const label of navButtons) {
      const button = screen.getByRole('button', { name: label });
      expect(button).not.toHaveClass(css.collapsedButton);
      expect(screen.getByText(label)).not.toHaveClass(css.collapsedLabel);
    }
    // MUI tooltips label the links with their titles.
    expect(screen.getByRole('link', { name: 'Pipeline List' })).toHaveAttribute(
      'href',
      RoutePage.PIPELINES,
    );
    expect(screen.getByRole('link', { name: 'Experiment List' })).toHaveAttribute(
      'href',
      RoutePage.EXPERIMENTS,
    );
    expect(screen.getByRole('link', { name: 'Runs List' })).toHaveAttribute('href', RoutePage.RUNS);
    expect(screen.getByRole('link', { name: 'Recurring Runs List' })).toHaveAttribute(
      'href',
      RoutePage.RECURRING_RUNS,
    );
    expect(screen.getByRole('link', { name: 'Artifacts List' })).toHaveAttribute(
      'href',
      RoutePage.ARTIFACTS,
    );
    expect(screen.getByRole('link', { name: 'Github Repo' })).toHaveAttribute(
      'href',
      ExternalLinks.GITHUB,
    );
    expect(screen.getByRole('link', { name: 'Report an Issue' })).toHaveAttribute(
      'href',
      ExternalLinks.GITHUB_ISSUE,
    );
    expect(screen.getByTestId('chevron-toggle')).not.toHaveClass(css.collapsedChevron);
    expect(screen.getByText('Version:').parentElement?.parentElement).toHaveClass(css.infoVisible);
  });

  it('renders sidebar nav buttons without primary button styling', async () => {
    const { renderResult } = renderSideNav(RoutePage.PIPELINES);
    await waitFor(() => expect(isCollapsed()).toBe(false));

    const pipelinesButton = renderResult.getByRole('button', { name: 'Pipelines' });
    const docsButton = renderResult.getByRole('button', { name: 'Documentation' });
    const docsLink = docsButton.closest('a');

    expect(pipelinesButton).toHaveClass('MuiButton-textInherit');
    expect(pipelinesButton).not.toHaveClass('MuiButton-textPrimary');
    expect(docsButton).toHaveClass('MuiButton-textInherit');
    expect(docsButton).not.toHaveClass('MuiButton-textPrimary');
    expect(docsLink).toHaveAttribute('href', ExternalLinks.DOCUMENTATION);
    expect(docsLink).toHaveAttribute('target', '_blank');
    expect(docsLink).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('renders collapsed state', async () => {
    localStorageHasKeySpy.mockImplementationOnce(() => false);
    (window as any).innerWidth = narrowWidth;
    renderSideNav(RoutePage.PIPELINES);
    await waitFor(() => expect(isCollapsed()).toBe(true));

    for (const label of navButtons) {
      expect(screen.getByRole('button', { name: label })).toHaveClass(css.collapsedButton);
      expect(screen.getByText(label)).toHaveClass(css.collapsedLabel);
    }
    expect(screen.getByTestId('chevron-toggle')).toHaveClass(css.collapsedChevron);
    expect(screen.getByText('Version:').parentElement?.parentElement).toHaveClass(css.infoHidden);
  });

  it('renders Pipelines as active page', async () => {
    renderSideNav(RoutePage.PIPELINES);
    await waitFor(() => expect(isCollapsed()).toBe(false));
    expectActive('Pipelines');
  });

  it('renders Pipelines as active when on PipelineDetails page', async () => {
    renderSideNav(pages.pipelineDetails);
    await waitFor(() => expect(isCollapsed()).toBe(false));
    expectActive('Pipelines');
  });

  it('renders Pipelines as active when on the shared pipelines page', async () => {
    renderSideNav(RoutePage.PIPELINES_SHARED);
    await waitFor(() => expect(isCollapsed()).toBe(false));
    expectActive('Pipelines');
  });

  it('renders experiments as active page', async () => {
    renderSideNav(RoutePage.EXPERIMENTS);
    await waitFor(() => expect(isCollapsed()).toBe(false));
    expectActive('Experiments');
  });

  it('renders experiments as active when on ExperimentDetails page', async () => {
    renderSideNav(pages.experimentDetails);
    await waitFor(() => expect(isCollapsed()).toBe(false));
    expectActive('Experiments');
  });

  it('renders experiments as active page when on NewExperiment page', async () => {
    renderSideNav(pages.newExperiment);
    await waitFor(() => expect(isCollapsed()).toBe(false));
    expectActive('Experiments');
  });

  it('renders experiments as active page when on the archived experiments page', async () => {
    renderSideNav(RoutePage.ARCHIVED_EXPERIMENTS);
    await waitFor(() => expect(isCollapsed()).toBe(false));
    expectActive('Experiments');
  });

  it('renders runs as active page when on Compare page', async () => {
    renderSideNav(RoutePage.COMPARE);
    await waitFor(() => expect(isCollapsed()).toBe(false));
    expectActive('Runs');
  });

  it('renders runs as active page when on AllRuns page', async () => {
    renderSideNav(RoutePage.RUNS);
    await waitFor(() => expect(isCollapsed()).toBe(false));
    expectActive('Runs');
  });

  it('renders runs as active page when on RunDetails page', async () => {
    renderSideNav(pages.runDetails);
    await waitFor(() => expect(isCollapsed()).toBe(false));
    expectActive('Runs');
  });

  it('renders runs as active page when on the archived runs page', async () => {
    renderSideNav(RoutePage.ARCHIVED_RUNS);
    await waitFor(() => expect(isCollapsed()).toBe(false));
    expectActive('Runs');
  });

  it('renders runs as active page when on NewRun page', async () => {
    renderSideNav(pages.newRun);
    await waitFor(() => expect(isCollapsed()).toBe(false));
    expectActive('Runs');
  });

  it('renders recurring runs as active page', async () => {
    renderSideNav(RoutePage.RECURRING_RUNS);
    await waitFor(() => expect(isCollapsed()).toBe(false));
    expectActive('Recurring Runs');
  });

  it('renders recurring runs as active page when on RecurringRunDetails page', async () => {
    renderSideNav(pages.recurringRunDetails);
    await waitFor(() => expect(isCollapsed()).toBe(false));
    expectActive('Recurring Runs');
  });

  it('renders artifacts as active page', async () => {
    renderSideNav(RoutePage.ARTIFACTS);
    await waitFor(() => expect(isCollapsed()).toBe(false));
    expectActive('Artifacts');
  });

  it('renders no active page for unknown routes', async () => {
    renderSideNav('/does-not-exist');
    await waitFor(() => expect(isCollapsed()).toBe(false));
    expectNoneActive();
  });

  it('show jupyterhub link if accessible', () => {
    const { instance } = renderSideNav(RoutePage.COMPARE);
    expect(screen.queryByText('Notebooks')).not.toBeInTheDocument();
    act(() => {
      instance.setState({ jupyterHubAvailable: true });
    });
    expect(screen.getByRole('button', { name: 'Notebooks' })).toBeInTheDocument();
    const notebooks = screen.getByRole('link', { name: 'Open Jupyter Notebook' });
    expect(notebooks).toHaveAttribute('href', '/hub/');
    expect(notebooks).toHaveAttribute('target', '_blank');
  });

  it('collapses if collapse state is true localStorage', async () => {
    localStorageIsCollapsedSpy.mockImplementation(() => true);
    localStorageHasKeySpy.mockImplementation(() => true);
    (window as any).innerWidth = wideWidth;
    renderSideNav(RoutePage.COMPARE);
    await waitFor(() => expect(isCollapsed()).toBe(true));
  });

  it('expands if collapse state is false in localStorage', async () => {
    localStorageIsCollapsedSpy.mockImplementationOnce(() => false);
    localStorageHasKeySpy.mockImplementationOnce(() => true);
    renderSideNav(RoutePage.COMPARE);
    await waitFor(() => expect(isCollapsed()).toBe(false));
  });

  it('collapses if no collapse state in localStorage, and window is too narrow', async () => {
    localStorageIsCollapsedSpy.mockImplementationOnce(() => false);
    localStorageHasKeySpy.mockImplementationOnce(() => false);
    (window as any).innerWidth = narrowWidth;
    renderSideNav(RoutePage.COMPARE);
    await waitFor(() => expect(isCollapsed()).toBe(true));
  });

  it('expands if no collapse state in localStorage, and window is wide', async () => {
    localStorageIsCollapsedSpy.mockImplementationOnce(() => false);
    localStorageHasKeySpy.mockImplementationOnce(() => false);
    (window as any).innerWidth = wideWidth;
    renderSideNav(RoutePage.COMPARE);
    await waitFor(() => expect(isCollapsed()).toBe(false));
  });

  it('collapses if no collapse state in localStorage, and window goes from wide to narrow', async () => {
    localStorageIsCollapsedSpy.mockImplementationOnce(() => false);
    localStorageHasKeySpy.mockImplementationOnce(() => false);
    (window as any).innerWidth = wideWidth;
    renderSideNav(RoutePage.COMPARE);
    await waitFor(() => expect(isCollapsed()).toBe(false));

    act(() => {
      (window as any).innerWidth = narrowWidth;
      window.dispatchEvent(new Event('resize'));
    });
    await waitFor(() => expect(isCollapsed()).toBe(true));
  });

  it('expands if no collapse state in localStorage, and window goes from narrow to wide', async () => {
    localStorageIsCollapsedSpy.mockImplementationOnce(() => false);
    localStorageHasKeySpy.mockImplementationOnce(() => false);
    (window as any).innerWidth = narrowWidth;
    renderSideNav(RoutePage.COMPARE);
    await waitFor(() => expect(isCollapsed()).toBe(true));

    act(() => {
      (window as any).innerWidth = wideWidth;
      window.dispatchEvent(new Event('resize'));
    });
    await waitFor(() => expect(isCollapsed()).toBe(false));
  });

  it('saves state in localStorage if chevron is clicked', async () => {
    localStorageIsCollapsedSpy.mockImplementationOnce(() => false);
    localStorageHasKeySpy.mockImplementationOnce(() => false);
    const spy = vi.spyOn(LocalStorage, 'saveNavbarCollapsed');

    (window as any).innerWidth = narrowWidth;
    renderSideNav(RoutePage.COMPARE);
    await waitFor(() => expect(isCollapsed()).toBe(true));

    fireEvent.click(screen.getByTestId('chevron-toggle'));
    expect(spy).toHaveBeenCalledWith(false);
  });

  it('labels the chevron toggle with the action it performs', async () => {
    renderSideNav(RoutePage.PIPELINES);
    await waitFor(() => expect(isCollapsed()).toBe(false));

    fireEvent.click(screen.getByRole('button', { name: 'Collapse navigation' }));
    await waitFor(() => expect(isCollapsed()).toBe(true));
    expect(screen.getByRole('button', { name: 'Expand navigation' })).toBeInTheDocument();
  });

  it('does not collapse if collapse state is saved in localStorage, and window resizes', async () => {
    localStorageIsCollapsedSpy.mockImplementation(() => false);
    localStorageHasKeySpy.mockImplementation(() => true);

    (window as any).innerWidth = wideWidth;
    renderSideNav(RoutePage.COMPARE);
    await waitFor(() => expect(isCollapsed()).toBe(false));

    act(() => {
      (window as any).innerWidth = narrowWidth;
      window.dispatchEvent(new Event('resize'));
    });
    await waitFor(() => expect(isCollapsed()).toBe(false));
  });

  it('populates the display build information using the default props', () => {
    const { instance } = renderSideNav(RoutePage.PIPELINES);
    const buildInfo = defaultProps.buildInfo;

    const version = screen.getByRole('link', { name: buildInfo.apiServerTagName });
    expect(version).toHaveAttribute(
      'href',
      'https://www.github.com/kubeflow/pipelines/commit/' + buildInfo.apiServerCommitHash,
    );
    expect(version).toHaveAttribute('target', '_blank');
    expect(screen.getByText('Version:')).toBeInTheDocument();
    expect(screen.queryByText('Cluster name:')).not.toBeInTheDocument();

    expect((instance as any)._getBuildInfo()).toEqual({
      tagName: buildInfo.apiServerTagName,
      commitHash: buildInfo.apiServerCommitHash.substring(0, 7),
      commitUrl:
        'https://www.github.com/kubeflow/pipelines/commit/' + buildInfo.apiServerCommitHash,
      date: new Date(buildInfo.buildDate).toLocaleDateString(),
    });
  });

  it('reads build information from the BuildInfoContext in the default export', () => {
    render(
      <MemoryRouter>
        <BuildInfoContext.Provider value={{ frontendTagName: '2.0.0', frontendCommitHash: 'abc' }}>
          <EnhancedSideNav page={RoutePage.PIPELINES} />
        </BuildInfoContext.Provider>
      </MemoryRouter>,
    );
    expect(screen.getByRole('link', { name: '2.0.0' })).toHaveAttribute(
      'href',
      'https://www.github.com/kubeflow/pipelines/commit/abc',
    );
  });

  it('display the correct GKE metadata', () => {
    const clusterName = 'some-cluster-name';
    const projectId = 'some-project-id';
    const gkeMetadata = { clusterName, projectId };

    const newProps = {
      ...defaultProps,
      gkeMetadata,
      buildInfo: {},
    };

    renderSideNav(RoutePage.PIPELINES, newProps);
    expect(screen.getByText('Cluster name:')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: clusterName })).toHaveAttribute(
      'href',
      `https://console.cloud.google.com/kubernetes/list?project=${projectId}&filter=name:${clusterName}`,
    );
    expect(screen.getByRole('link', { name: 'unknown' })).toHaveAttribute(
      'href',
      'https://www.github.com/kubeflow/pipelines',
    );
  });

  it('displays the frontend tag name if the api server hash is not returned', () => {
    const newProps = {
      ...defaultProps,
      buildInfo: {
        apiServerReady: true,
        buildDate: 'Tue Oct 23 14:23:53 UTC 2018',
        frontendCommitHash: '302e93ce99099173f387c7e0635476fe1b69ea98',
        frontendTagName: '1.0.0',
      },
    };

    const { instance } = renderSideNav(RoutePage.PIPELINES, newProps);
    expect((instance as any)._getBuildInfo()).toEqual(
      expect.objectContaining({
        commitHash: newProps.buildInfo.frontendCommitHash.substring(0, 7),
        tagName: newProps.buildInfo.frontendTagName,
      }),
    );
    expect(screen.getByRole('link', { name: '1.0.0' })).toBeInTheDocument();
  });

  it('uses the frontend commit hash for the link URL if the api server hash is not returned', () => {
    const newProps = {
      ...defaultProps,
      buildInfo: {
        apiServerReady: true,
        buildDate: 'Tue Oct 23 14:23:53 UTC 2018',
        frontendCommitHash: '302e93ce99099173f387c7e0635476fe1b69ea98',
      },
    };

    const { instance } = renderSideNav(RoutePage.PIPELINES, newProps);
    expect((instance as any)._getBuildInfo()).toEqual(
      expect.objectContaining({
        commitUrl:
          'https://www.github.com/kubeflow/pipelines/commit/' +
          newProps.buildInfo.frontendCommitHash,
      }),
    );
  });

  it("displays 'unknown' if the frontend and api server tag names/commit hashes are not returned", () => {
    const newProps = {
      ...defaultProps,
      buildInfo: {
        apiServerReady: true,
        buildDate: 'Tue Oct 23 14:23:53 UTC 2018',
      },
    };

    const { instance } = renderSideNav(RoutePage.PIPELINES, newProps);
    expect((instance as any)._getBuildInfo()).toEqual(
      expect.objectContaining({
        commitHash: 'unknown',
        tagName: 'unknown',
      }),
    );
    expect(screen.getByRole('link', { name: 'unknown' })).toBeInTheDocument();
  });

  it('links to the github repo root if the frontend and api server commit hashes are not returned', () => {
    const newProps = {
      ...defaultProps,
      buildInfo: {
        apiServerReady: true,
        buildDate: 'Tue Oct 23 14:23:53 UTC 2018',
      },
    };

    const { instance } = renderSideNav(RoutePage.PIPELINES, newProps);
    expect((instance as any)._getBuildInfo()).toEqual(
      expect.objectContaining({
        commitUrl: 'https://www.github.com/kubeflow/pipelines',
      }),
    );
  });

  it("displays 'unknown' if the date is not returned", () => {
    const newProps = {
      ...defaultProps,
      buildInfo: {
        apiServerCommitHash: '0a7b9e38f2b9bcdef4bbf3234d971e1635b50cd5',
        apiServerReady: true,
        frontendCommitHash: '302e93ce99099173f387c7e0635476fe1b69ea98',
      },
    };

    const { instance } = renderSideNav(RoutePage.PIPELINES, newProps);
    expect((instance as any)._getBuildInfo()).toEqual(
      expect.objectContaining({
        date: 'unknown',
      }),
    );
  });

  it('auto-collapses on first load when localStorage key is missing and window is narrow', async () => {
    localStorageHasKeySpy.mockRestore();
    localStorageIsCollapsedSpy.mockRestore();
    localStorage.removeItem(LocalStorageKey.navbarCollapsed);
    (window as any).innerWidth = narrowWidth;

    renderSideNav(RoutePage.COMPARE);
    await waitFor(() => expect(isCollapsed()).toBe(true));
  });
});
