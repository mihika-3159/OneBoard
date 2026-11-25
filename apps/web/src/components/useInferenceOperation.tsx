import React, {useEffect, useRef, useState} from 'react';
import {api} from '../services/api';

export function useInferenceOperation() {
  const controller = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; controller.current?.abort(); };
  }, []);
  async function run<T = any>(path: string, payload?: unknown): Promise<T> {
    if (controller.current) throw new Error('An inference request is already running');
    const current = new AbortController();
    controller.current = current;
    setBusy(true);
    setMessage('Inference running');
    try {
      const value = await api.streamInference<T>(path, payload, current.signal,
        text => { if (mounted.current) setMessage(text); });
      if (current.signal.aborted) throw new Error('Inference cancelled');
      if (mounted.current) setMessage('');
      return value;
    } catch (e) {
      if (mounted.current) setMessage(current.signal.aborted ? 'Inference cancelled. No partial result was accepted.' :
        'Inference interrupted. Retry to request a new result.');
      throw e;
    } finally {
      if (controller.current === current) controller.current = null;
      if (mounted.current) setBusy(false);
    }
  }
  function cancel() { controller.current?.abort(); }
  const indicator = message ? <div className="flex items-center gap-3 rounded-lg border border-slate-700 p-3 text-sm text-slate-300">
    <span role="status" aria-live="polite">{message}</span>
    {busy && <button type="button" onClick={cancel} className="px-3 py-1 border rounded">Cancel inference</button>}
  </div> : null;
  return {run, cancel, indicator, busy};
}
