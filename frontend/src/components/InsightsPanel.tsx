import React, { useState } from 'react';
import {
  Loader2,
  AlertCircle,
  Sparkles,
  CheckSquare,
  Circle,
  HelpCircle,
  Mail,
  Copy,
  Check,
} from 'lucide-react';
import { useRequest } from '../hooks/useRequest';
import { getInsights, summarizeMeeting } from '../services/api';
import { getApiErrorMessage, getErrorStatus, type ErrorMessages } from '../services/errors';
import type { MeetingInsights, MeetingStatus } from '../types';

interface InsightsPanelProps {
  meetingId: string;
  meetingStatus: MeetingStatus;
  hasTranscript: boolean;
}

const SUMMARIZE_ERRORS: ErrorMessages = {
  fallback: 'Failed to generate insights. Please try again.',
  byStatus: {
    429: 'Insights can only be generated a few times per minute. Please wait a moment and try again.',
    502: 'The AI provider failed to produce insights. Please try again in a moment.',
    503: 'AI insights are not configured on this server.',
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
  icon: React.ReactNode;
}

const InsightList: React.FC<InsightListProps> = ({ title, items, icon }) => (
  <div className="insight-card">
    <div className="insight-card__title">{title}</div>
    {items.length === 0 ? (
      <p className="insight-card__empty">None identified</p>
    ) : (
      <ul className="insight-card__list">
        {items.map((item, i) => (
          <li key={i}>
            {icon}
            <span>{item}</span>
          </li>
        ))}
      </ul>
    )}
  </div>
);

export const InsightsPanel: React.FC<InsightsPanelProps> = ({
  meetingId,
  meetingStatus,
  hasTranscript,
}) => {
  const saved = useRequest(meetingId, loadSavedInsights);
  const [generated, setGenerated] = useState<MeetingInsights | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const insights = generated ?? (saved.status === 'success' ? saved.data : null);
  const error =
    generateError ?? (saved.status === 'error' ? 'Could not load saved insights.' : null);
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

  const handleCopy = () => {
    if (!insights || !navigator.clipboard) return;
    navigator.clipboard.writeText(insights.follow_up_email).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      },
      () => undefined,
    );
  };

  const errorAlert = error && (
    <div className="alert alert--error alert--inline insights-panel__alert" role="alert">
      <AlertCircle size={14} />
      {error}
    </div>
  );

  if (saved.status === 'loading' && !generated) {
    return (
      <div className="insights-panel">
        <div className="loading-state">
          <Loader2 size={20} className="spin" />
          <span>Loading insights...</span>
        </div>
      </div>
    );
  }

  if (isGenerating) {
    return (
      <div className="insights-panel">
        <div className="insights-generate">
          <Loader2 size={28} className="spin insights-generate__icon insights-generate__icon--compact" />
          <p className="insights-generate__status">Analyzing transcript with Groq AI...</p>
        </div>
      </div>
    );
  }

  if (!insights) {
    return (
      <div className="insights-panel">
        <div className="insights-generate">
          <Sparkles size={32} className="insights-generate__icon" />
          <p className="insights-generate__description">
            Generate a summary, action items, decisions, and a follow-up email draft from this
            meeting's transcript.
          </p>
          {errorAlert}
          <div title={blockedReason ?? undefined}>
            <button
              className="btn btn--primary"
              onClick={() => void generate(false)}
              disabled={blockedReason !== null}
            >
              <Sparkles size={15} />
              Generate AI Insights
            </button>
          </div>
          {blockedReason && <p className="insights-generate__hint">{blockedReason}</p>}
        </div>
      </div>
    );
  }

  return (
    <div className="insights-panel">
      <div className="insights-grid">
        <div className="insight-card">
          <div className="insight-card__title">Summary</div>
          {insights.summary ? (
            <p className="insight-card__text">{insights.summary}</p>
          ) : (
            <p className="insight-card__empty">None identified</p>
          )}
        </div>

        <InsightList
          title="Action Items"
          items={insights.action_items}
          icon={<CheckSquare size={13} className="insight-card__icon insight-card__icon--action" />}
        />
        <InsightList
          title="Decisions"
          items={insights.decisions}
          icon={<Circle size={8} className="insight-card__icon insight-card__icon--decision" />}
        />
        <InsightList
          title="Questions Raised"
          items={insights.questions_raised}
          icon={<HelpCircle size={13} className="insight-card__icon insight-card__icon--question" />}
        />

        {/* Follow-up email spans the full width */}
        <div className="insight-card email-card">
          <div className="insight-card__title insight-card__title--with-icon">
            <Mail size={12} />
            Follow-up Email
          </div>
          <div className="email-body">
            <button
              className="btn btn--ghost btn--sm copy-btn"
              onClick={handleCopy}
              title="Copy to clipboard"
            >
              {copied ? (
                <>
                  <Check size={12} />
                  Copied!
                </>
              ) : (
                <>
                  <Copy size={12} />
                  Copy
                </>
              )}
            </button>
            {insights.follow_up_email}
          </div>
        </div>
      </div>

      <div className="insights-panel__actions">
        {errorAlert}
        <button
          className="btn btn--ghost btn--sm"
          onClick={() => void generate(true)}
          disabled={blockedReason !== null}
          title={blockedReason ?? 'Generate the insights again from the current transcript'}
        >
          <Sparkles size={13} />
          Regenerate
        </button>
      </div>
    </div>
  );
};
