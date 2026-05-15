/**
 * Sprint 8.1 — Vitest spec for the LocalApiTokenPanel component.
 *
 * The panel must:
 *   * render the "not set" state when no token is stored
 *   * round-trip a token through sessionStorage
 *   * mask the token after save (never show the full value)
 *   * clear cleanly via the Clear button
 *   * never emit broker/execution/AI-approved copy
 *   * always render the data-advisory-only=true / data-execution-permission=false attrs
 */
// @ts-ignore
import { render, screen, fireEvent } from '@testing-library/react';
import { LocalApiTokenPanel } from '@/components/LocalApiTokenPanel';

// @ts-ignore
declare const describe: any;
// @ts-ignore
declare const it: any;
// @ts-ignore
declare const expect: any;
// @ts-ignore
declare const beforeEach: any;

describe('LocalApiTokenPanel', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  it('renders the "not set" state by default', () => {
    render(<LocalApiTokenPanel />);
    const panel = screen.getByTestId('local-api-token-panel');
    expect(panel.getAttribute('data-token-set')).toBe('false');
    expect(panel.getAttribute('data-advisory-only')).toBe('true');
    expect(panel.getAttribute('data-execution-permission')).toBe('false');
    expect(screen.getByTestId('token-status').textContent).toMatch(/not set/i);
    expect(screen.getByTestId('token-input-row')).toBeTruthy();
  });

  it('saves a token to sessionStorage and masks the value', () => {
    render(<LocalApiTokenPanel />);
    const input = screen.getByTestId('token-input') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'super-secret-token-1234' } });
    fireEvent.click(screen.getByTestId('token-save-btn'));
    const panel = screen.getByTestId('local-api-token-panel');
    expect(panel.getAttribute('data-token-set')).toBe('true');
    // The stored token must NEVER be rendered verbatim after save.
    const preview = screen.getByTestId('token-preview').textContent ?? '';
    expect(preview).not.toContain('super-secret-token-1234');
    expect(preview).toMatch(/stored/i);
    // Just-saved confirmation appears (does not display the token).
    expect(screen.getByTestId('token-just-saved').textContent).toMatch(/set/i);
    // sessionStorage holds the token; localStorage stays empty.
    expect(window.sessionStorage.getItem('mvp_api_token')).toBe(
      'super-secret-token-1234',
    );
    expect(window.localStorage.length).toBe(0);
  });

  it('clears the token via the Clear button', () => {
    window.sessionStorage.setItem('mvp_api_token', 'prefilled');
    render(<LocalApiTokenPanel />);
    fireEvent.click(screen.getByTestId('token-clear-btn'));
    const panel = screen.getByTestId('local-api-token-panel');
    expect(panel.getAttribute('data-token-set')).toBe('false');
    expect(window.sessionStorage.getItem('mvp_api_token')).toBeNull();
  });

  it('never emits forbidden broker / execution / AI-approved copy', () => {
    const { container } = render(<LocalApiTokenPanel />);
    const blob = (container.textContent ?? '').toLowerCase();
    expect(blob).not.toMatch(/place order/);
    expect(blob).not.toMatch(/execute trade/);
    expect(blob).not.toMatch(/broker (api|order|connected)/);
    expect(blob).not.toMatch(/auto[- ]trade/);
    expect(blob).not.toMatch(/ai[- ]approved/);
    expect(blob).not.toMatch(/permission granted/);
    expect(blob).not.toMatch(/trade now/);
  });

  it('explicit safety copy disclaims trade authorization', () => {
    render(<LocalApiTokenPanel />);
    expect(screen.getByTestId('token-safety-copy').textContent).toMatch(
      /does not authorise|never authorises|never authorizes/i,
    );
  });
});
