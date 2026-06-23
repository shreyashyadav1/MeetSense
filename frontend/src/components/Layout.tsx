import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Brain, LayoutDashboard } from 'lucide-react';

interface LayoutProps {
  children: React.ReactNode;
  activeMeetingId?: string;
}

export const Layout: React.FC<LayoutProps> = ({ children, activeMeetingId }) => {
  const location = useLocation();

  const isActive = (path: string) => location.pathname === path;

  return (
    <div className="layout">
      <nav className="navbar">
        <div className="navbar__inner">
          <Link to="/" className="navbar__logo">
            <Brain size={22} className="navbar__logo-icon" />
            <span className="navbar__logo-text">MeetSense AI</span>
          </Link>

          <div className="navbar__links">
            <Link
              to="/"
              className={`navbar__link ${isActive('/') ? 'navbar__link--active' : ''}`}
            >
              <LayoutDashboard size={16} />
              Dashboard
            </Link>

            {activeMeetingId && (
              <Link
                to={`/meeting/${activeMeetingId}/live`}
                className={`navbar__link navbar__link--live ${
                  location.pathname.includes('/live') ? 'navbar__link--active' : ''
                }`}
              >
                <span className="navbar__live-dot" />
                Live Meeting
              </Link>
            )}
          </div>
        </div>
      </nav>

      <main className="main-content">
        <div className="content-wrapper">{children}</div>
      </main>
    </div>
  );
};
