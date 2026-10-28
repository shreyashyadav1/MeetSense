import React, { useEffect, useRef, useState } from 'react';
import { AlertCircle, Check, Copy, Loader2, RotateCw, Sparkles } from 'lucide-react';
import { useRequest } from '../hooks/useRequest';
import { getInsights, summarizeMeeting } from '../services/api';
import { getApiErrorMessage, getErrorStatus, type ErrorMessages } from '../services/errors';
import type { MeetingInsights, MeetingStatus } from '../types';
import { formatTime } from '../utils/format';
import './InsightsPanel.css';

interface InsightsPanelProps {
  meetingId: string;
  meetingStatus: MeetingStatus;
  hasTranscript: boolean;
}

const SUMMARIZE_ERRORS: ErrorMessages = {
  fallback: 'Couldn’t generate insights. Try again in a moment.',
  byStatus: {
    429: 'Insights can only be generated a few times per minute. Wait a moment, then try again.',
    502: 'The AI provider failed to produce insights. Try again in a moment.',
    503:
      'AI insights are not configured on this server. Set GROQ_API_KEY on the backend to turn them on.',
  },
};

/** Saved insights, or null when none have been generated yet (404). */
function loadSavedInsights(meetingId: string): Promise<MeetingInsights | null> {
  return getInsights(meetingId).catch((error: unknown) => {
    if (getErrorStatus(error) === 404) return null;
    throw error;
  });
}

interface InsightListProps {
  title: string;
  items: string[];
  emptyText: string;
}

const InsightList: React.FC<InsightListProps> = ({ title, items, emptyText }) => (
  <section className="insight">
    <h3>{title}</h3>
    {items.length === 0 ? (
      <p className="insight__empty">{emptyText}</p>
    ) : (
      <ul className="insight__list">
        {items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    )}
  </section>
);

type CopyState = 'idle' | 'copied' | 'failed';

export const InsightsPanel: React.FC<InsightsPanelProps> = ({
  meetingId,
  meetingStatus,
  hasTranscript,
}) => {
  const saved = useRequest(meetingId, loadSavedInsights);
  const [generated, setGenerated] = useState<MeetingInsights | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [copyState, setCopyState] = useState<CopyState>('idle');
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (copyTimer.current) clearTimeout(copyTimer.current);
    };
  }, []);

  const insights = generated ?? (saved.status === 'success' ? saved.data : null);
  const error =
    generateError ??
    (saved.status === 'error'
      ? 'Couldn’t load the saved insights. You can still generate new ones.'
      : null);
  const blockedReason =
    meetingStatus !== 'ended'
      ? 'End the meeting first to generate insights.'
      : !hasTranscript
        ? 'This meeting has no transcript to summarize.'
        : null;

  const generate = async (force: boolean) => {
    setIsGenerating(true);
    setGenerateError(null);
    try {
      setGenerated(await summarizeMeeting(meetingId, { force }));
    } catch (err) {
      setGenerateError(getApiErrorMessage(err, SUMMARIZE_ERRORS));
    } finally {
      setIsGenerating(false);
    }
  };

  const showCopyState = (state: CopyState) => {
    setCopyState(state);
    if (copyTimer.current) clearTimeout(copyTimer.current);
    copyTimer.current = setTimeout(() => setCopyState('idle'), 2500);
  };

  const handleCopy = () => {
    if (!insights) return;
    if (!navigator.clipboard) {
      showCopyState('failed');
      return;
    }
    navigator.clipboard.writeText(insights.follow_up_email).then(
      () => showCopyState('copied'),
      () => showCopyState('failed'),
    );
  };

  const errorAlert = error && (
    <div className="notice notice--danger" role="alert">
      <AlertCircle size={18} aria-hidden="true" />
      <p className="notice__body">{error}</p>
    </div>
  );

  if (saved.status === 'loading' && !generated) {
    return (
      <div className="insights-loading" role="status">
        <span className="visually-hidden">Loading insights…</span>
        <span className="skeleton" style={{ width: '92%' }} aria-hidden="true" />
        <span className="skeleton" style={{ width: '78%' }} aria-hidden="true" />
        <span className="skeleton" style={{ width: '54%' }} aria-hidden="true" />
      </div>
    );
  }

  if (isGenerating) {
    return (
      <div className="insights-progress" role="status">
        <Loader2 size={20} className="spin" aria-hidden="true" />
        <div>
          <p className="insights-progress__title">Reading the transcript…</p>
          <p className="insights-progress__text">
            Drafting the summary, action items and follow-up email. This usually takes a few
            seconds.
          </p>
        </div>
      </div>
    );
  }

  if (!insights) {
    return (
      <div className="insights-start">
        <p className="insights-start__text">
          Get a summary, action items, decisions, open questions and a follow-up email drafted
          from this meeting&rsquo;s transcript.
        </p>
        {errorAlert}
        <div className="insights-start__actions">
          <button
            type="button"
            className="button button--primary"
            onClick={() => void generate(false)}
            disabled={blockedReason !== null}
            aria-describedby={blockedReason ? 'insights-blocked' : undefined}
          >
            <Sparkles size={16} aria-hidden="true" />
            Generate insights
          </button>
          {blockedReason && (
            <p className="insights-start__blocked" id="insights-blocked">
              {blockedReason}
            </p>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="insights">
      <section className="insight insight--summary">
        <h3>Summary</h3>
        {insights.summary ? (
          <p>{insights.summary}</p>
        ) : (
          <p className="insight__empty">No summary was produced.</p>
        )}
      </section>

      <InsightList
        title="Action items"
        items={insights.action_items}
        emptyText="No action items came up."
      />
      <InsightList title="Decisions" items={insights.decisions} emptyText="No decisions were made." />
      <InsightList
        title="Open questions"
        items={insights.questions_raised}
        emptyText="No open questions."
      />

      <section className="insight insight--email">
        <div className="insight__head">
          <h3>Follow-up email</h3>
          <button type="button" className="button button--secondary button--small" onClick={handleCopy}>
            {copyState === 'copied' ? (
              <>
                <Check size={16} aria-hidden="true" />
                Copied
              </>
            ) : (
              <>
                <Copy size={16} aria-hidden="true" />
                Copy email
              </>
            )}
          </button>
        </div>
        <div className="letter">{insights.follow_up_email}</div>
        <p className="insight__copy-status" role="status">
          {copyState === 'copied' && <span className="visually-hidden">Email copied to the clipboard.</span>}
          {copyState === 'failed' && 'Couldn’t copy the email. Select the text and copy it yourself.'}
        </p>
      </section>

      <div className="insights__footer">
        <p className="insights__generated">
          Generated at{' '}
          <time dateTime={insights.generated_at}>{formatTime(insights.generated_at)}</time>
        </p>
        {errorAlert}
        <button
          type="button"
          className="button button--secondary button--small"
          onClick={() => void generate(true)}
          disabled={blockedReason !== null}
          title={blockedReason ?? 'Generate the insights again from the current transcript'}
        >
          <RotateCw size={16} aria-hidden="true" />
          Regenerate
        </button>
      </div>
    </div>
  );
};
