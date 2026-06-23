import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, Mic, X, Loader2, RefreshCw } from 'lucide-react';
import { Layout } from '../components/Layout';
import { MeetingCard } from '../components/MeetingCard';
import { useMeetings } from '../hooks/useMeetings';

export const Dashboard: React.FC = () => {
  const navigate = useNavigate();
  const { meetings, isLoading, error, createMeeting, refresh } = useMeetings();

  const [showModal, setShowModal] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [isCreating, setIsCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const activeMeeting = meetings.find((m) => m.status === 'active');

  const handleOpenModal = () => {
    setNewTitle('');
    setCreateError(null);
    setShowModal(true);
  };

  const handleCloseModal = () => {
    if (!isCreating) {
      setShowModal(false);
      setNewTitle('');
      setCreateError(null);
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    const title = newTitle.trim();
    if (!title) return;

    setIsCreating(true);
    setCreateError(null);

    try {
      const meeting = await createMeeting(title);
      setShowModal(false);
      navigate(`/meeting/${meeting.id}/live`);
    } catch (err) {
      console.error('[Dashboard] Failed to create meeting:', err);
      setCreateError('Could not create meeting. Make sure the backend is running.');
    } finally {
      setIsCreating(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') handleCloseModal();
  };

  return (
    <Layout activeMeetingId={activeMeeting?.id}>
      <div className="dashboard">
        {/* Header */}
        <div className="dashboard__header">
          <div className="dashboard__title-group">
            <h1 className="dashboard__title">Dashboard</h1>
            <p className="dashboard__subtitle">
              Capture and review your meetings with live transcription.
            </p>
          </div>
          <div className="dashboard__actions">
            <button
              className="btn btn--ghost btn--sm"
              onClick={refresh}
              aria-label="Refresh meetings"
              disabled={isLoading}
            >
              <RefreshCw size={14} className={isLoading ? 'spin' : ''} />
              Refresh
            </button>
            <button className="btn btn--primary" onClick={handleOpenModal}>
              <Plus size={16} />
              New Meeting
            </button>
          </div>
        </div>

        {/* Error banner */}
        {error && (
          <div className="alert alert--warning">
            <span>{error}</span>
          </div>
        )}

        {/* Meeting list */}
        <div className="dashboard__section">
          <h2 className="section-title">
            Meetings
            {meetings.length > 0 && (
              <span className="section-count">{meetings.length}</span>
            )}
          </h2>

          {isLoading && meetings.length === 0 ? (
            <div className="loading-state">
              <Loader2 size={24} className="spin" />
              <span>Loading meetings...</span>
            </div>
          ) : meetings.length === 0 ? (
            <div className="empty-state">
              <div className="empty-state__icon">
                <Mic size={40} />
              </div>
              <h3 className="empty-state__title">No meetings yet</h3>
              <p className="empty-state__desc">
                Start your first meeting to see live transcription in action.
              </p>
              <button className="btn btn--primary" onClick={handleOpenModal}>
                <Plus size={16} />
                Start your first meeting
              </button>
            </div>
          ) : (
            <div className="meeting-list">
              {meetings.map((meeting) => (
                <MeetingCard key={meeting.id} meeting={meeting} />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* New Meeting Modal */}
      {showModal && (
        <div
          className="modal-overlay"
          onClick={handleCloseModal}
          onKeyDown={handleKeyDown}
          role="dialog"
          aria-modal="true"
          aria-label="New meeting"
        >
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal__header">
              <h2 className="modal__title">
                <Mic size={18} />
                New Meeting
              </h2>
              <button
                className="modal__close"
                onClick={handleCloseModal}
                aria-label="Close modal"
                disabled={isCreating}
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleCreate} className="modal__form">
              <div className="form-field">
                <label className="form-label" htmlFor="meeting-title">
                  Meeting Title
                </label>
                <input
                  id="meeting-title"
                  className="form-input"
                  type="text"
                  placeholder="e.g. Weekly Standup, Product Review..."
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                  autoFocus
                  disabled={isCreating}
                  maxLength={120}
                />
              </div>

              {createError && (
                <div className="alert alert--error">
                  <span>{createError}</span>
                </div>
              )}

              <div className="modal__footer">
                <button
                  type="button"
                  className="btn btn--ghost"
                  onClick={handleCloseModal}
                  disabled={isCreating}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn--primary"
                  disabled={!newTitle.trim() || isCreating}
                >
                  {isCreating ? (
                    <>
                      <Loader2 size={15} className="spin" />
                      Starting...
                    </>
                  ) : (
                    <>
                      <Mic size={15} />
                      Start Meeting
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </Layout>
  );
};
