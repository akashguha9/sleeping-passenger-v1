/**
 * Vitest spec for the Manual Trade Log "AI model used" field.
 *
 * Contract pinned here:
 *   - the visible input renders with the operator-facing placeholder
 *   - submitting forwards ai_model_used to the API payload
 *   - omitting the field still submits (empty string)
 *   - the field is trimmed at the UI boundary (real trim happens
 *     server-side, but the client also forwards .trim() so the value
 *     the backend sees never has stray whitespace)
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
  postManualTrade: vi.fn().mockResolvedValue({ trade_id: 'MT_X' }),
}));

import { postManualTrade } from '@/lib/apiClient';
import { ManualTradeLogForm } from '@/components/ManualTradeLogForm';

const postMock = postManualTrade as unknown as ReturnType<typeof vi.fn>;

function fillRequired() {
  fireEvent.change(screen.getByPlaceholderText('FABRIC_BTC'), { target: { value: 'EVT_X' } });
  fireEvent.change(screen.getByPlaceholderText('BTC'), { target: { value: 'AAPL' } });
  fireEvent.change(screen.getByPlaceholderText('10'), { target: { value: '10' } });
  fireEvent.change(screen.getByPlaceholderText('182.50'), { target: { value: '180' } });
  fireEvent.change(screen.getByPlaceholderText(/human reasoning/), {
    target: { value: 'follow-through on AAPL prior pivot' },
  });
}

beforeEach(() => {
  postMock.mockReset();
  postMock.mockResolvedValue({ trade_id: 'MT_X' });
});

describe('ManualTradeLogForm AI model used field', () => {
  it('renders the AI model used input with operator-facing placeholder', () => {
    render(<ManualTradeLogForm />);
    const input = screen.getByTestId('manual-trade-ai-model-used-input') as HTMLInputElement;
    expect(input).toBeTruthy();
    expect(input.placeholder).toMatch(/GPT-5\.5/);
    expect(input.placeholder).toMatch(/Claude Code/);
    expect(input.placeholder).toMatch(/Grok/);
    expect(input.placeholder).toMatch(/Human-only/);
  });

  it('forwards ai_model_used in the API payload', async () => {
    render(<ManualTradeLogForm />);
    fillRequired();
    const aiInput = screen.getByTestId('manual-trade-ai-model-used-input') as HTMLInputElement;
    fireEvent.change(aiInput, { target: { value: 'Claude Code' } });
    fireEvent.click(screen.getByRole('button', { name: /Log Manual Trade/i }));
    await waitFor(() => expect(postMock).toHaveBeenCalledTimes(1));
    const body = postMock.mock.calls[0][0];
    expect(body.ai_model_used).toBe('Claude Code');
  });

  it('submits ai_model_used as empty string when the operator skips it', async () => {
    render(<ManualTradeLogForm />);
    fillRequired();
    fireEvent.click(screen.getByRole('button', { name: /Log Manual Trade/i }));
    await waitFor(() => expect(postMock).toHaveBeenCalledTimes(1));
    const body = postMock.mock.calls[0][0];
    expect(body.ai_model_used).toBe('');
  });

  it('trims whitespace around the AI model label before sending', async () => {
    render(<ManualTradeLogForm />);
    fillRequired();
    const aiInput = screen.getByTestId('manual-trade-ai-model-used-input') as HTMLInputElement;
    fireEvent.change(aiInput, { target: { value: '   Multi-model consensus   ' } });
    fireEvent.click(screen.getByRole('button', { name: /Log Manual Trade/i }));
    await waitFor(() => expect(postMock).toHaveBeenCalledTimes(1));
    const body = postMock.mock.calls[0][0];
    expect(body.ai_model_used).toBe('Multi-model consensus');
  });
});
