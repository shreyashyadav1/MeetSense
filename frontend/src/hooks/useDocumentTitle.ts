import { useEffect } from 'react';

const APP_NAME = 'MeetSense';

/** Names the browser tab after the current page, e.g. "Weekly sync – MeetSense". */
export function useDocumentTitle(title: string | null): void {
  useEffect(() => {
    document.title = title ? `${title} – ${APP_NAME}` : APP_NAME;
  }, [title]);
}
