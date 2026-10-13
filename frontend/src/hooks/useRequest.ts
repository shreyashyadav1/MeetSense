import { useEffect, useState } from 'react';

export type RequestState<T> =
  | { status: 'loading' }
  | { status: 'success'; data: T }
  | { status: 'error'; error: unknown };

const LOADING: RequestState<never> = { status: 'loading' };

/**
 * Runs `load(key)` and tracks its state. Results are stored together with
 * their key, so a new key reads as loading straight away (no synchronous
 * setState in the effect) and a late response for an old key is ignored.
 * `load` must be stable, e.g. a module-level function.
 */
export function useRequest<T>(key: string, load: (key: string) => Promise<T>): RequestState<T> {
  const [result, setResult] = useState<{ key: string; state: RequestState<T> } | null>(null);

  useEffect(() => {
    let current = true;
    load(key).then(
      (data) => {
        if (current) setResult({ key, state: { status: 'success', data } });
      },
      (error: unknown) => {
        if (current) setResult({ key, state: { status: 'error', error } });
      },
    );
    return () => {
      current = false;
    };
  }, [key, load]);

  return result?.key === key ? result.state : LOADING;
}
