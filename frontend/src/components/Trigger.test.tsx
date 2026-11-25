// Copyright 2026 The Kubeflow Authors
// SPDX-License-Identifier: Apache-2.0
import { fireEvent, render, screen } from '@testing-library/react';
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';
import Trigger from './Trigger';

const PARAMS_DEFAULT = {
  catchup: true,
  maxConcurrentRuns: '10',
};
const PERIODIC_DEFAULT = {
  end_time: undefined,
  interval_second: (60 * 60).toString(),
  start_time: undefined,
};
const CRON_DEFAULT = { cron: '0 0 * * * ?', end_time: undefined, start_time: undefined };

async function selectOption(selectElement: HTMLElement, optionText: string): Promise<void> {
  fireEvent.mouseDown(selectElement);
  const option = await screen.findByRole('option', { name: optionText });
  fireEvent.click(option);
}

function getTriggerTypeSelect(): HTMLElement {
  return screen.getByRole('combobox', { name: /trigger type/i });
}

function getIntervalCategorySelect(): HTMLElement {
  const comboboxes = screen.getAllByRole('combobox');
  return comboboxes[1];
}

describe('Trigger', () => {
  const NOW = new Date(2018, 11, 21, 7, 53);

  beforeAll(() => {
    // Only fake Date so MUI's transitions and RTL's findBy* polling keep real timers.
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(NOW);
  });

  afterAll(() => {
    vi.useRealTimers();
  });

  function getIntervalValueInput(): HTMLInputElement {
    return screen.getByRole('spinbutton') as HTMLInputElement;
  }

  function getDayButtons(): HTMLElement[] {
    return ['S', 'M', 'T', 'W', 'T', 'F', 'S'].map(
      (_, i) => screen.getAllByRole('button').filter((b) => b.classList.contains('MuiFab-root'))[i],
    );
  }

  it('renders periodic schedule controls for initial render', () => {
    render(<Trigger />);
    expect(getTriggerTypeSelect()).toHaveTextContent('Periodic');
    expect(screen.getByDisplayValue('10')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Has start date' })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Has end date' })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Catchup' })).toBeChecked();
    expect(screen.getByLabelText('Start date')).toHaveValue('2018-12-21');
    expect(screen.getByLabelText('Start time')).toHaveValue('07:53');
    expect(screen.getByLabelText('End date')).toHaveValue('2018-12-28');
    expect(screen.getByLabelText('End time')).toHaveValue('07:53');
    expect(getIntervalValueInput()).toHaveValue(1);
    expect(getIntervalCategorySelect()).toHaveTextContent('Hours');
    expect(screen.queryByLabelText('cron expression')).toBeNull();
    expect(screen.queryByText('On:')).toBeNull();
  });

  it('renders periodic schedule controls if the trigger type is CRON', async () => {
    render(<Trigger />);
    await selectOption(getTriggerTypeSelect(), 'Cron');
    expect(getTriggerTypeSelect()).toHaveTextContent('Cron');
    expect(screen.queryByRole('spinbutton')).toBeNull();
    expect(getIntervalCategorySelect()).toHaveTextContent('Hour');
    expect(
      screen.getByRole('checkbox', { name: /allow editing cron expression/i }),
    ).not.toBeChecked();
    const cronInput = screen.getByLabelText('cron expression');
    expect(cronInput).toBeDisabled();
    expect(cronInput).toHaveValue('0 0 * * * ?');
    expect(
      screen.getByText('Note: Start and end dates/times are handled outside of cron.'),
    ).toBeInTheDocument();
    expect(screen.queryByText('On:')).toBeNull();
  });

  it('renders week days if the trigger type is CRON and interval is weekly', async () => {
    render(<Trigger />);
    await selectOption(getTriggerTypeSelect(), 'Cron');
    await selectOption(getIntervalCategorySelect(), 'Week');
    expect(screen.getByText('On:')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'All' })).toBeChecked();
    const days = getDayButtons();
    expect(days.map((d) => d.textContent)).toEqual(['S', 'M', 'T', 'W', 'T', 'F', 'S']);
    days.forEach((d) => expect(d).toHaveClass('MuiFab-primary'));
    expect(screen.getByLabelText('cron expression')).toHaveValue('0 0 0 ? * *');
  });

  it('renders all week days enabled', async () => {
    render(<Trigger />);
    await selectOption(getTriggerTypeSelect(), 'Cron');
    await selectOption(getIntervalCategorySelect(), 'Week');
    // Every day starts enabled, so toggling "All" clears them all; toggling again re-enables all.
    fireEvent.click(screen.getByRole('checkbox', { name: 'All' }));
    expect(screen.getByRole('checkbox', { name: 'All' })).not.toBeChecked();
    getDayButtons().forEach((d) => expect(d).toHaveClass('MuiFab-secondary'));
    fireEvent.click(screen.getByRole('checkbox', { name: 'All' }));
    expect(screen.getByRole('checkbox', { name: 'All' })).toBeChecked();
    getDayButtons().forEach((d) => expect(d).toHaveClass('MuiFab-primary'));
    expect(screen.getByLabelText('cron expression')).toHaveValue('0 0 0 ? * *');
  });

  it('enables a single day on click', async () => {
    render(<Trigger />);
    await selectOption(getTriggerTypeSelect(), 'Cron');
    await selectOption(getIntervalCategorySelect(), 'Week');
    fireEvent.click(screen.getByRole('button', { name: 'M' }));
    fireEvent.click(screen.getByRole('button', { name: 'W' }));
    const days = getDayButtons();
    expect(days.map((d) => d.classList.contains('MuiFab-primary'))).toEqual([
      true,
      false,
      true,
      false,
      true,
      true,
      true,
    ]);
    expect(screen.getByRole('checkbox', { name: 'All' })).not.toBeChecked();
    expect(screen.getByLabelText('cron expression')).toHaveValue('0 0 0 ? * 0,2,4,5,6');
  });

  describe('max concurrent run', () => {
    it('shows error message if the input is invalid (non-integer)', () => {
      render(<Trigger />);
      const maxConcurrencyParam = screen.getByDisplayValue('10');
      fireEvent.change(maxConcurrencyParam, { target: { value: '10a' } });
      screen.getByText('Invalid input. The maximum concurrent runs should be a positive integer.');
    });

    it('shows error message if the input is invalid (negative integer)', () => {
      render(<Trigger />);
      const maxConcurrencyParam = screen.getByDisplayValue('10');
      fireEvent.change(maxConcurrencyParam, { target: { value: '-10' } });
      screen.getByText('Invalid input. The maximum concurrent runs should be a positive integer.');
    });
  });

  describe('interval trigger', () => {
    it('builds an every-hour trigger by default', () => {
      const spy = vi.fn();
      render(<Trigger onChange={spy} />);

      expect(spy).toHaveBeenLastCalledWith({
        ...PARAMS_DEFAULT,
        trigger: {
          periodic_schedule: PERIODIC_DEFAULT,
        },
      });
    });

    it('builds trigger with a start time if the checkbox is checked', () => {
      const spy = vi.fn();
      render(<Trigger onChange={spy} />);
      fireEvent.click(screen.getByRole('checkbox', { name: 'Has start date' }));
      const now = new Date(2018, 11, 21, 7, 53);
      expect(spy).toHaveBeenLastCalledWith({
        ...PARAMS_DEFAULT,
        trigger: {
          periodic_schedule: { ...PERIODIC_DEFAULT, start_time: now },
        },
      });
    });

    it('builds trigger with the entered start date/time', () => {
      const spy = vi.fn();
      render(<Trigger onChange={spy} />);
      fireEvent.click(screen.getByRole('checkbox', { name: 'Has start date' }));
      fireEvent.change(screen.getByLabelText('Start date'), {
        target: { value: '2018-11-23' },
      });
      fireEvent.change(screen.getByLabelText('Start time'), {
        target: { value: '08:35' },
      });
      expect(spy).toHaveBeenLastCalledWith({
        ...PARAMS_DEFAULT,
        trigger: {
          periodic_schedule: {
            ...PERIODIC_DEFAULT,
            start_time: new Date(2018, 10, 23, 8, 35),
          },
        },
      });
    });

    it('builds trigger without the entered start date if no time is entered', () => {
      const spy = vi.fn();
      render(<Trigger onChange={spy} />);
      fireEvent.click(screen.getByRole('checkbox', { name: 'Has start date' }));
      fireEvent.change(screen.getByLabelText('Start date'), {
        target: { value: '2018-11-23' },
      });
      fireEvent.change(screen.getByLabelText('Start time'), {
        target: { value: '' },
      });
      expect(spy).toHaveBeenLastCalledWith({
        ...PARAMS_DEFAULT,
        trigger: {
          periodic_schedule: PERIODIC_DEFAULT,
        },
      });
    });

    it('builds trigger without the entered start time if no date is entered', () => {
      const spy = vi.fn();
      render(<Trigger onChange={spy} />);
      fireEvent.click(screen.getByRole('checkbox', { name: 'Has start date' }));
      fireEvent.change(screen.getByLabelText('Start date'), {
        target: { value: '' },
      });
      fireEvent.change(screen.getByLabelText('Start time'), {
        target: { value: '11:33' },
      });
      expect(spy).toHaveBeenLastCalledWith({
        ...PARAMS_DEFAULT,
        trigger: {
          periodic_schedule: PERIODIC_DEFAULT,
        },
      });
    });

    it('builds trigger with a date if both start and end checkboxes are checked', () => {
      const spy = vi.fn();
      render(<Trigger onChange={spy} />);
      fireEvent.click(screen.getByRole('checkbox', { name: 'Has start date' }));
      fireEvent.click(screen.getByRole('checkbox', { name: 'Has end date' }));
      const now = new Date(2018, 11, 21, 7, 53);
      const oneWeekLater = new Date(2018, 11, 28, 7, 53);
      expect(spy).toHaveBeenLastCalledWith({
        ...PARAMS_DEFAULT,
        trigger: {
          periodic_schedule: { ...PERIODIC_DEFAULT, end_time: oneWeekLater, start_time: now },
        },
      });
    });

    it('resets trigger to no start date if it is added then removed', () => {
      const spy = vi.fn();
      render(<Trigger onChange={spy} />);
      fireEvent.click(screen.getByRole('checkbox', { name: 'Has start date' }));
      fireEvent.click(screen.getByRole('checkbox', { name: 'Has start date' }));
      expect(spy).toHaveBeenLastCalledWith({
        ...PARAMS_DEFAULT,
        trigger: {
          periodic_schedule: PERIODIC_DEFAULT,
        },
      });
    });

    it('Show invalid start date/time format message if date has wrong format.', async () => {
      render(<Trigger />);
      fireEvent.click(screen.getByRole('checkbox', { name: 'Has start date' }));

      // jsdom sanitizes type="date" inputs, rejecting non-YYYY-MM-DD values.
      // Temporarily switch to type="text" so the invalid value reaches handleChange.
      const startDateInput = screen.getByLabelText('Start date') as HTMLInputElement;
      startDateInput.type = 'text';
      fireEvent.change(startDateInput, {
        target: { value: 'this_is_not_valid_date_format' },
      });
      expect(
        await screen.findByText("Invalid start date or time, start time won't be set"),
      ).toBeInTheDocument();

      fireEvent.change(screen.getByLabelText('Start date'), {
        target: { value: '2021-01-01' },
      });
      expect(
        screen.queryByText("Invalid start date or time, start time won't be set"),
      ).not.toBeInTheDocument();
    });

    it('Hide invalid start date/time format message if start time checkbox is not selected.', async () => {
      render(<Trigger />);
      fireEvent.click(screen.getByRole('checkbox', { name: 'Has start date' }));

      const startDateInput = screen.getByLabelText('Start date') as HTMLInputElement;
      startDateInput.type = 'text';
      fireEvent.change(startDateInput, {
        target: { value: 'this_is_not_valid_date_format' },
      });
      expect(
        await screen.findByText("Invalid start date or time, start time won't be set"),
      ).toBeInTheDocument();

      fireEvent.click(screen.getByRole('checkbox', { name: 'Has start date' }));
      expect(
        screen.queryByText("Invalid start date or time, start time won't be set"),
      ).not.toBeInTheDocument();
    });

    it('Show invalid end date/time format message if date has wrong format.', async () => {
      render(<Trigger />);
      fireEvent.click(screen.getByRole('checkbox', { name: 'Has end date' }));

      const endTimeInput = screen.getByLabelText('End time') as HTMLInputElement;
      endTimeInput.type = 'text';
      fireEvent.change(endTimeInput, {
        target: { value: 'this_is_not_valid_time_format' },
      });
      expect(
        await screen.findByText("Invalid end date or time, end time won't be set"),
      ).toBeInTheDocument();

      fireEvent.change(screen.getByLabelText('End time'), {
        target: { value: '11:22' },
      });
      expect(
        screen.queryByText("Invalid end date or time, end time won't be set"),
      ).not.toBeInTheDocument();
    });

    it('Hide invalid end date/time format message if start time checkbox is not selected.', async () => {
      render(<Trigger />);
      fireEvent.click(screen.getByRole('checkbox', { name: 'Has end date' }));

      const endTimeInput = screen.getByLabelText('End time') as HTMLInputElement;
      endTimeInput.type = 'text';
      fireEvent.change(endTimeInput, {
        target: { value: 'this_is_not_valid_date_format' },
      });
      expect(
        await screen.findByText("Invalid end date or time, end time won't be set"),
      ).toBeInTheDocument();

      fireEvent.click(screen.getByRole('checkbox', { name: 'Has end date' }));
      expect(
        screen.queryByText("Invalid end date or time, end time won't be set"),
      ).not.toBeInTheDocument();
    });

    it('builds trigger with a weekly interval', async () => {
      const spy = vi.fn();
      render(<Trigger onChange={spy} />);
      await selectOption(getIntervalCategorySelect(), 'Weeks');
      expect(spy).toHaveBeenLastCalledWith({
        ...PARAMS_DEFAULT,
        trigger: {
          periodic_schedule: {
            ...PERIODIC_DEFAULT,
            interval_second: (7 * 24 * 60 * 60).toString(),
          },
        },
      });
    });

    it('builds trigger with an every-three-months interval', async () => {
      const spy = vi.fn();
      render(<Trigger onChange={spy} />);
      await selectOption(getIntervalCategorySelect(), 'Months');
      fireEvent.change(screen.getByRole('spinbutton'), { target: { value: 3 } });
      expect(spy).toHaveBeenLastCalledWith({
        ...PARAMS_DEFAULT,
        trigger: {
          periodic_schedule: {
            ...PERIODIC_DEFAULT,
            interval_second: (3 * 30 * 24 * 60 * 60).toString(),
          },
        },
      });
    });

    it('builds trigger with the specified max concurrency setting', () => {
      const spy = vi.fn();
      render(<Trigger onChange={spy} />);
      fireEvent.change(screen.getByDisplayValue('10'), { target: { value: '3' } });
      expect(spy).toHaveBeenLastCalledWith({
        ...PARAMS_DEFAULT,
        maxConcurrentRuns: '3',
        trigger: {
          periodic_schedule: PERIODIC_DEFAULT,
        },
      });
    });

    it('builds trigger with the specified catchup setting', () => {
      const spy = vi.fn();
      render(<Trigger onChange={spy} />);
      fireEvent.click(screen.getByRole('checkbox', { name: 'Catchup' }));
      expect(spy).toHaveBeenLastCalledWith({
        ...PARAMS_DEFAULT,
        catchup: false,
        trigger: {
          periodic_schedule: PERIODIC_DEFAULT,
        },
      });
    });

    it('inits with cloned initial props', () => {
      const spy = vi.fn();
      const startTime = new Date('2020-01-01T23:53:00.000Z');
      render(
        <Trigger
          onChange={spy}
          initialProps={{
            maxConcurrentRuns: '3',
            catchup: false,
            trigger: {
              periodic_schedule: {
                interval_second: '' + 60 * 60 * 3,
                start_time: startTime.toISOString() as any,
              },
            },
          }}
        />,
      );
      expect(spy).toHaveBeenLastCalledWith({
        catchup: false,
        maxConcurrentRuns: '3',
        trigger: {
          periodic_schedule: {
            end_time: undefined,
            interval_second: '10800',
            start_time: startTime,
          },
        },
      });
    });
  });

  describe('cron', () => {
    it('builds a 1-hour cron trigger by default', async () => {
      const spy = vi.fn();
      render(<Trigger onChange={spy} />);
      await selectOption(getTriggerTypeSelect(), 'Cron');
      expect(spy).toHaveBeenLastCalledWith({
        ...PARAMS_DEFAULT,
        trigger: {
          cron_schedule: CRON_DEFAULT,
        },
      });
    });

    it('builds a 1-hour cron trigger with specified start date', async () => {
      const spy = vi.fn();
      render(<Trigger onChange={spy} />);
      await selectOption(getTriggerTypeSelect(), 'Cron');
      fireEvent.click(screen.getByRole('checkbox', { name: 'Has start date' }));
      fireEvent.change(screen.getByLabelText('Start date'), {
        target: { value: '2018-03-23' },
      });
      expect(spy).toHaveBeenLastCalledWith({
        ...PARAMS_DEFAULT,
        trigger: {
          cron_schedule: {
            ...CRON_DEFAULT,
            start_time: new Date(2018, 2, 23, 7, 53),
            cron: '0 53 * * * ?',
          },
        },
      });
    });

    it('builds a daily cron trigger with specified end date/time', async () => {
      const spy = vi.fn();
      render(<Trigger onChange={spy} />);
      await selectOption(getTriggerTypeSelect(), 'Cron');
      fireEvent.click(screen.getByRole('checkbox', { name: 'Has end date' }));
      await selectOption(getIntervalCategorySelect(), 'Day');
      const oneWeekLater = new Date(2018, 11, 28, 7, 53);
      expect(spy).toHaveBeenLastCalledWith({
        ...PARAMS_DEFAULT,
        trigger: {
          cron_schedule: { ...CRON_DEFAULT, end_time: oneWeekLater, cron: '0 0 0 * * ?' },
        },
      });
    });

    it('builds a weekly cron trigger that runs every Monday, Friday, and Saturday', async () => {
      const spy = vi.fn();
      render(<Trigger onChange={spy} />);
      await selectOption(getTriggerTypeSelect(), 'Cron');
      await selectOption(getIntervalCategorySelect(), 'Week');

      fireEvent.click(screen.getByRole('checkbox', { name: 'All' }));
      fireEvent.click(screen.getByRole('button', { name: 'M' }));
      fireEvent.click(screen.getByRole('button', { name: 'F' }));
      // Two "S" buttons exist (Sun, Sat); pick the second = Saturday
      fireEvent.click(screen.getAllByRole('button', { name: 'S' })[1]);
      expect(spy).toHaveBeenLastCalledWith({
        ...PARAMS_DEFAULT,
        trigger: {
          cron_schedule: { ...CRON_DEFAULT, cron: '0 0 0 ? * 1,5,6' },
        },
      });
    });

    it('builds a cron with the manually specified cron string, even if days are toggled', async () => {
      const spy = vi.fn();
      render(<Trigger onChange={spy} />);
      await selectOption(getTriggerTypeSelect(), 'Cron');
      await selectOption(getIntervalCategorySelect(), 'Week');

      fireEvent.click(screen.getByRole('checkbox', { name: 'All' }));
      fireEvent.click(screen.getByRole('button', { name: 'M' }));
      fireEvent.click(screen.getByRole('button', { name: 'F' }));
      // Two "S" buttons exist (Sun, Sat); pick the second = Saturday
      fireEvent.click(screen.getAllByRole('button', { name: 'S' })[1]);

      fireEvent.click(screen.getByRole('checkbox', { name: /allow editing cron expression/i }));
      fireEvent.change(screen.getByLabelText('cron expression'), {
        target: { value: 'oops this will break!' },
      });
      expect(spy).toHaveBeenLastCalledWith({
        ...PARAMS_DEFAULT,
        trigger: {
          cron_schedule: { ...CRON_DEFAULT, cron: 'oops this will break!' },
        },
      });
    });

    it('inits with cloned initial props', () => {
      const spy = vi.fn();
      const startTime = new Date('2020-01-01T00:00:00.000Z');
      const endTime = new Date('2020-01-02T01:02:00.000Z');
      render(
        <Trigger
          onChange={spy}
          initialProps={{
            maxConcurrentRuns: '4',
            catchup: true,
            trigger: {
              cron_schedule: {
                cron: '0 0 0 ? * 1,5,6',
                start_time: startTime.toISOString() as any,
                end_time: endTime.toISOString() as any,
              },
            },
          }}
        />,
      );
      expect(spy).toHaveBeenLastCalledWith({
        catchup: true,
        maxConcurrentRuns: '4',
        trigger: {
          cron_schedule: {
            cron: '0 0 0 ? * 1,5,6',
            start_time: startTime,
            end_time: endTime,
          },
        },
      });
    });
  });
});
