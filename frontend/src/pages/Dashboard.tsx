import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertCircle, Loader2, Plus, RefreshCw } from 'lucide-react';
import { Layout } from '../components/Layout';
import { MeetingListItem } from '../components/MeetingListItem';
import { TranscriptPanel } from '../components/TranscriptPanel';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { useMeetings } from '../hooks/useMeetings';
import { getApiErrorMessage } from '../services/errors';
import type { Meeting, TranscriptSegment } from '../types';
import { dayKey, formatDayHeading } from '../utils/format';
import {
  MEETING_TITLE_MAX_LENGTH,
  meetingTitleLength,
  validateMeetingTitle,
} from '../utils/validation';
import './Dashboard.css';

const CREATE_ERRORS = {
  fallback: 'Couldn’t start the meeting. Try again in a moment.',
  byStatus: {
    429: 'You’re creating meetings too quickly. Wait a minute, then try again.',
  },
};

/** A two-line sample shown on an empty dashboard, so it's clear what a transcript will look like. */
const EXAMPLE_TRANSCRIPT: TranscriptSegment[] = [
  {
    id: 'example-1',
    meeting_id: 'example',
    speaker: 'Priya',
    text: 'Can we lock the launch date before Friday?',
    timestamp: 754,
    confidence: 1,
  },
  {
    id: 'example-2',
    meeting_id: 'example',
    speaker: 'Marcus',
    text: 'Yes. I’ll confirm with design and send it round tomorrow.',
    timestamp: 758,
    confidence: 1,
  },
];

interface DayGroup {
  key: string;
  label: string;
  meetings: Meeting[];
}

/** Ended meetings, newest first, grouped by the day they started. */
function groupByDay(meetings: readonly Meeting[], now = new Date()): DayGroup[] {
  const sorted = [...meetings].sort((a, b) => b.started_at.localeCompare(a.started_at));
  const groups: DayGroup[] = [];
  for (const meeting of sorted) {
    const date = new Date(meeting.started_at);
    const key = Number.isNaN(date.getTime()) ? meeting.started_at : dayKey(date);
    const last = groups.at(-1);
    if (last && last.key === key) {
      last.meetings.push(meeting);
    } else {
      groups.push({ key, label: formatDayHeading(meeting.started_at, now), meetings: [meeting] });
    }
  }
  return groups;
}

export const Dashboard: React.FC = () => {
  const navigate = useNavigate();
  const { meetings, isLoading, isRefreshing, error, createMeeting, refresh } = useMeetings();
  useDocumentTitle('Meetings');

  const [composerOpen, setComposerOpen] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [isCreating, setIsCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const titleInput = useRef<HTMLInputElement>(null);

  const activeMeetings = meetings.filter((m) => m.status === 'active');
  const pastGroups = useMemo(
    () => groupByDay(meetings.filter((m) => m.status === 'ended')),
    [meetings],
  );
  const isEmpty = !isLoading && meetings.length === 0;
  const showComposer = composerOpen || isEmpty;

  const titleLength = meetingTitleLength(newTitle);
  const titleError = validateMeetingTitle(newTitle);
  // Don't nag about an empty field before the user has typed anything.
  const visibleTitleError = newTitle.length > 0 ? titleError : null;

  useEffect(() => {
    if (composerOpen) titleInput.current?.focus();
  }, [composerOpen]);

  const openComposer = () => {
    setCreateError(null);
    setComposerOpen(true);
    titleInput.current?.focus();
  };

  const closeComposer = () => {
    if (isCreating) return;
    setComposerOpen(false);
    setNewTitle('');
    setCreateError(null);
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (titleError || isCreating) return;

    setIsCreating(true);
    setCreateError(null);

    try {
      const meeting = await createMeeting(newTitle.trim());
      navigate(`/meeting/${meeting.id}/live`);
    } catch (err) {
      setCreateError(getApiErrorMessage(err, CREATE_ERRORS));
      setIsCreating(false);
    }
  };

  const handleComposerKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape' && !isEmpty) closeComposer();
  };

  return (
    <Layout activeMeetingId={activeMeetings[0]?.id}>
      <div className="page dashboard">
        <header className="dashboard__head">
          <div className="dashboard__intro">
            <h1>Meetings</h1>
            <p className="dashboard__lede">
              Live transcripts of your calls, with action items once they end.
            </p>
          </div>
          <div className="dashboard__actions">
            <button
              type="button"
              className="button button--quiet"
              onClick={refresh}
              aria-label="Refresh meetings"
              disabled={isLoading || isRefreshing}
            >
              <RefreshCw
                size={16}
                className={isLoading || isRefreshing ? 'spin' : undefined}
                aria-hidden="true"
              />
              Refresh
            </button>
            <button type="button" className="button button--primary" onClick={openComposer}>
              <Plus size={16} aria-hidden="true" />
              New meeting
            </button>
          </div>
        </header>

        {showComposer && (
          <form
            className="composer"
            onSubmit={handleCreate}
            onKeyDown={handleComposerKeyDown}
            aria-label="New meeting"
          >
            <div className="field">
              <label className="field__label" htmlFor="meeting-title">
                Meeting title
              </label>
              <div className="composer__row">
                <input
                  ref={titleInput}
                  id="meeting-title"
                  name="title"
                  className="field__input"
                  type="text"
                  autoComplete="off"
                  placeholder="Weekly product sync…"
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                  disabled={isCreating}
                  aria-invalid={visibleTitleError !== null}
                  aria-describedby="meeting-title-hint"
                />
                <div className="composer__buttons">
                  <button
                    type="submit"
                    className="button button--primary"
                    disabled={titleError !== null || isCreating}
                  >
                    {isCreating ? (
                      <>
                        <Loader2 size={16} className="spin" aria-hidden="true" />
                        Starting…
                      </>
                    ) : (
                      'Start meeting'
                    )}
                  </button>
                  {!isEmpty && (
                    <button
                      type="button"
                      className="button button--quiet"
                      onClick={closeComposer}
                      disabled={isCreating}
                    >
                      Cancel
                    </button>
                  )}
                </div>
              </div>
              <div className="field__footer" id="meeting-title-hint">
                <span className="field__error" role="alert">
                  {visibleTitleError}
                </span>
                <span
                  className={`field__count${
                    titleLength > MEETING_TITLE_MAX_LENGTH ? ' field__count--over' : ''
                  }`}
                >
                  {titleLength}/{MEETING_TITLE_MAX_LENGTH}
                </span>
              </div>
            </div>

            {createError && (
              <div className="notice notice--danger" role="alert">
                <AlertCircle size={18} aria-hidden="true" />
                <p className="notice__body">{createError}</p>
              </div>
            )}

            <p className="composer__hint">
              The live transcript opens straight away; start recording when the call begins.
            </p>
          </form>
        )}

        {error && (
          <div className="notice notice--warn dashboard__error" role="status">
            <AlertCircle size={18} aria-hidden="true" />
            <p className="notice__body">{error}</p>
          </div>
        )}

        {isLoading && meetings.length === 0 ? (
          <div className="dashboard__loading" role="status">
            <span className="visually-hidden">Loading meetings…</span>
            {[0, 1, 2].map((row) => (
              <div className="meeting-row meeting-row--skeleton" key={row} aria-hidden="true">
                <span className="skeleton" style={{ width: `${48 - row * 9}%` }} />
                <span className="skeleton" style={{ width: '4rem' }} />
              </div>
            ))}
          </div>
        ) : isEmpty ? (
          <section className="empty-state" aria-labelledby="empty-title">
            <div className="empty-state__text">
              <h2 id="empty-title">No meetings yet</h2>
              <p>
                Start one before your next call. MeetSense writes down what each person says as
                they talk, and when the meeting ends it can draft the summary and action items.
              </p>
            </div>
            <figure className="empty-state__example">
              <figcaption className="empty-state__caption">What a live transcript looks like</figcaption>
              <TranscriptPanel segments={EXAMPLE_TRANSCRIPT} />
            </figure>
          </section>
        ) : (
          <div className="dashboard__lists">
            {activeMeetings.length > 0 && (
              <section aria-labelledby="in-progress">
                <h2 className="day-heading" id="in-progress">
                  In progress
                </h2>
                <ul className="meeting-list">
                  {activeMeetings.map((meeting) => (
                    <MeetingListItem key={meeting.id} meeting={meeting} />
                  ))}
                </ul>
              </section>
            )}
            {pastGroups.map((group) => (
              <section key={group.key} aria-labelledby={`day-${group.key}`}>
                <h2 className="day-heading" id={`day-${group.key}`}>
                  {group.label}
                </h2>
                <ul className="meeting-list">
                  {group.meetings.map((meeting) => (
                    <MeetingListItem key={meeting.id} meeting={meeting} />
                  ))}
                </ul>
              </section>
            ))}
          </div>
        )}
      </div>
    </Layout>
  );
};
