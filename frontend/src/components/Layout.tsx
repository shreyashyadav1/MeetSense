import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { LogoMark } from './Logo';
import { OfflineBanner } from './OfflineBanner';
import './Layout.css';

interface LayoutProps {
  children: React.ReactNode;
  activeMeetingId?: string;
  /** The page fills the window and scrolls inside its own panels (the live meeting room). */
  fill?: boolean;
}

export const Layout: React.FC<LayoutProps> = ({ children, activeMeetingId, fill = false }) => {
  const { pathname } = useLocation();
  const liveHref = activeMeetingId ? `/meeting/${activeMeetingId}/live` : null;

  return (
    <div className={`layout${fill ? ' layout--fill' : ''}`}>
      <a className="skip-link" href="#main">
        Skip to content
      </a>

      <header className="appbar">
        <div className="appbar__inner">
          <Link to="/" className="wordmark" translate="no">
            <LogoMark />
            MeetSense
          </Link>

          <nav className="appbar__nav" aria-label="Main">
            <Link
              to="/"
              className="appbar__link"
              aria-current={pathname === '/' ? 'page' : undefined}
            >
              Meetings
            </Link>
            {liveHref && (
              <Link
                to={liveHref}
                className="appbar__link"
                aria-current={pathname === liveHref ? 'page' : undefined}
              >
                <span className="appbar__live-dot" aria-hidden="true" />
                Live meeting
              </Link>
            )}
          </nav>
        </div>
      </header>

      <OfflineBanner />

      <main id="main" className="layout__main" tabIndex={-1}>
        {children}
      </main>
    </div>
  );
};
