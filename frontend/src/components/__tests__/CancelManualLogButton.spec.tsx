/**
 * Vitest spec for the CancelManualLogButton.
 *
 * The button is attached to each unreconciled manual-trade card in the
 * Reconciliation tab.  Contract pinned here:
 *
 *   * renders the destructive secondary "Cancel Log" button initially
 *   * carries advisory data-attrs (data-advisory-only=true,
 *     data-execution-permission=false)
 *   * opens an inline confirmation alertdialog with the safety blurb
 *   * confirm flow calls cancelManualTradeLog with the trade id and a
 *     duplicate-log reason that includes the no-broker disclaimer
 *   * success invokes onCancelled with the trade id
 *   * API failure preserves the card and surfaces an error
 *   * Keep-log dismiss path resets the dialog without calling the API
 */
// @ts-ignore
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { vi } from 'vitest';

// @ts-ignore
declare const describe: any;
// @ts-ignore
declare const it: any;
// @ts-ignore
declare const expect: any;
// @ts-ignore
declare const beforeEach: any;

vi.mock('@/lib/apiClient', () => ({
  cancelManualTradeLog: vi.fn(),
}));

import { cancelManualTradeLog } from '@/lib/apiClient';
import { CancelManualLogButton } from '@/components/CancelManualLogButton';

const mockCancel = cancelManualTradeLog as unknown as ReturnType<typeof vi.fn>;

describe('CancelManualLogButton', () => {
  beforeEach(() => {
    mockCancel.mockReset();
  });

  it('renders the destructive Cancel Log button with safety attrs', () => {
    render(<CancelManualLogButton tradeId="MT_abc" ticker="ICICIBANK.NS" />);
    const btn = screen.getByTestId('cancel-log-btn');
    expect(btn).toBeTruthy();
    expect(btn.getAttribute('data-advisory-only')).toBe('true');
    expect(btn.getAttribute('data-execution-permission')).toBe('false');
    expect(btn.textContent).toMatch(/cancel log/i);
    const row = screen.getByTestId('cancel-log-row');
    expect(row.getAttribute('data-trade-id')).toBe('MT_abc');
    // The idle row exposes the "local log only / no broker call" copy.
    expect(row.textContent?.toLowerCase()).toMatch(/no broker call/);
    expect(row.textContent?.toLowerCase()).toMatch(/record-keeping/);
  });

  it('opens the inline confirmation dialog with the safety blurb', () => {
    render(<CancelManualLogButton tradeId="MT_abc" />);
    fireEvent.click(screen.getByTestId('cancel-log-btn'));
    const dialog = screen.getByTestId('cancel-log-confirm');
    expect(dialog.getAttribute('role')).toBe('alertdialog');
    expect(dialog.getAttribute('data-advisory-only')).toBe('true');
    expect(dialog.getAttribute('data-execution-permission')).toBe('false');
    const blob = (dialog.textContent ?? '').toLowerCase();
    expect(blob).toMatch(/only cancels the local record/);
    expect(blob).toMatch(/does not call a broker/);
    expect(blob).toMatch(/does not cancel any broker order/);
    expect(blob).toMatch(/broker api: not called/);
    expect(screen.getByTestId('cancel-log-keep-btn').textContent).toMatch(
      /keep log/i,
    );
    expect(screen.getByTestId('cancel-log-confirm-btn').textContent).toMatch(
      /yes, cancel local log/i,
    );
  });

  it('Keep log dismisses without calling the API', () => {
    render(<CancelManualLogButton tradeId="MT_abc" />);
    fireEvent.click(screen.getByTestId('cancel-log-btn'));
    fireEvent.click(screen.getByTestId('cancel-log-keep-btn'));
    expect(mockCancel).not.toHaveBeenCalled();
    // Back to the idle row.
    expect(screen.getByTestId('cancel-log-btn')).toBeTruthy();
  });

  it('confirm calls cancelManualTradeLog with the trade id and notifies parent', async () => {
    mockCancel.mockResolvedValueOnce({
      status: 'cancelled',
      reconciliation_status: 'CANCELLED_DUPLICATE',
      broker_api_called: false,
      ai_execution_count: 0,
    });
    const onCancelled = vi.fn();
    render(
      <CancelManualLogButton tradeId="MT_xyz" onCancelled={onCancelled} />,
    );
    fireEvent.click(screen.getByTestId('cancel-log-btn'));
    fireEvent.click(screen.getByTestId('cancel-log-confirm-btn'));
    await waitFor(() => expect(mockCancel).toHaveBeenCalledTimes(1));
    const [tradeId, body] = mockCancel.mock.calls[0];
    expect(tradeId).toBe('MT_xyz');
    expect(body.reason.toLowerCase()).toMatch(/duplicate manual log/);
    expect(body.reason.toLowerCase()).toMatch(/broker api not called/);
    expect(body.reason.toLowerCase()).toMatch(/ai executions = 0/);
    await waitFor(() => expect(onCancelled).toHaveBeenCalledWith('MT_xyz'));
  });

  it('on API failure, keeps the card and surfaces an error', async () => {
    mockCancel.mockRejectedValueOnce(new Error('HTTP 500'));
    const onCancelled = vi.fn();
    render(
      <CancelManualLogButton tradeId="MT_err" onCancelled={onCancelled} />,
    );
    fireEvent.click(screen.getByTestId('cancel-log-btn'));
    fireEvent.click(screen.getByTestId('cancel-log-confirm-btn'));
    await waitFor(() =>
      expect(screen.getByTestId('cancel-log-error')).toBeTruthy(),
    );
    const err = screen.getByTestId('cancel-log-error').textContent ?? '';
    expect(err.toLowerCase()).toMatch(/could not cancel/);
    expect(err.toLowerCase()).toMatch(/kept/);
    expect(onCancelled).not.toHaveBeenCalled();
    // Still in the confirmation dialog so the operator can retry / dismiss.
    expect(screen.getByTestId('cancel-log-confirm')).toBeTruthy();
  });

  it('never emits forbidden broker / order-execution copy', () => {
    render(<CancelManualLogButton tradeId="MT_safe" ticker="ICICIBANK.NS" />);
    fireEvent.click(screen.getByTestId('cancel-log-btn'));
    const blob = (
      screen.getByTestId('cancel-log-confirm').textContent ?? ''
    ).toLowerCase();
    expect(blob).not.toMatch(/place order/);
    expect(blob).not.toMatch(/submit order/);
    expect(blob).not.toMatch(/cancel broker order/);
    expect(blob).not.toMatch(/auto[- ]trade/);
    expect(blob).not.toMatch(/broker connected/);
    expect(blob).not.toMatch(/ai[- ]approved/);
  });
});
