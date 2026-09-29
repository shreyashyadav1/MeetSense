import { useSyncExternalStore } from 'react';
import { apiHealthMonitor } from '../services/apiHealth';

/** Whether the API's last health check failed (network error, timeout or 5xx). */
export function useApiHealth(): boolean {
  return useSyncExternalStore(apiHealthMonitor.subscribe, apiHealthMonitor.getSnapshot).offline;
}
