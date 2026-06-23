import React, { useState, useEffect } from 'react';
import { Loader2, AlertCircle, Sparkles, CheckSquare, Circle, HelpCircle, Mail, Copy, Check } from 'lucide-react';
import { getInsights, summarizeMeeting } from '../services/api';
import type { MeetingInsights } from '../types';

interface InsightsPanelProps {
  meetingId: string;
  hasTranscript: boolean;
}

export const InsightsPanel: React.FC<InsightsPanelProps> = ({ meetingId, hasTranscript }) => {
  const [insights, setInsights] = useState<MeetingInsights | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isChecking, setIsChecking] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!meetingId) {
      setIsChecking(false);
      return;
    }
    setIsChecking(true);
    getInsights(meetingId)
      .then((data) => {
        setInsights(data);
        setError(null);
      })
      .catch((err) => {
        // 404 means no insights yet — that's normal, not an error
        const status = err?.response?.status;
        if (status !== 404) {
          setError('Failed to load insights.');
        }
      })
      .finally(() => setIsChecking(false));
  }, [meetingId]);

  const handleGenerate = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await summarizeMeeting(meetingId);
      setInsights(data);
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Failed to generate insights. Please try again.';
      setError(message);
    } finally {
      setIsLoading(false);
    }
  };

  const handleCopy = () => {
    if (!insights) return;
    navigator.clipboard.writeText(insights.follow_up_email).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  // Still doing the initial fetch check
  if (isChecking) {
    return (
      <div className="insights-panel">
        <div className="loading-state">
          <Loader2 size={20} className="spin" />
          <span>Loading insights...</span>
        </div>
      </div>
    );
  }

  // Generating in progress
  if (isLoading) {
    return (
      <div className="insights-panel">
        <div className="insights-generate">
          <Loader2 size={28} className="spin" style={{ color: 'var(--accent)', marginBottom: '0.75rem' }} />
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
            Analyzing transcript with Groq AI...
          </p>
        </div>
      </div>
    );
  }

  // No insights yet — show generate button
  if (!insights) {
    const disabled = !hasTranscript;
    return (
      <div className="insights-panel">
        <div className="insights-generate">
          <Sparkles size={32} style={{ color: 'var(--accent)', marginBottom: '1rem' }} />
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginBottom: '1.25rem' }}>
            Generate a summary, action items, decisions, and a follow-up email draft from this meeting's transcript.
          </p>
          {error && (
            <div className="alert alert--error alert--inline" style={{ marginBottom: '1rem', justifyContent: 'center' }}>
              <AlertCircle size={14} />
              {error}
            </div>
          )}
          <div title={disabled ? 'End the meeting first to generate insights' : undefined}>
            <button
              className="btn btn--primary"
              onClick={handleGenerate}
              disabled={disabled}
            >
              <Sparkles size={15} />
              Generate AI Insights
            </button>
          </div>
          {disabled && (
            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.5rem' }}>
              End the meeting first to generate insights
            </p>
          )}
        </div>
      </div>
    );
  }

  // Insights loaded — show the cards
  return (
    <div className="insights-panel">
      <div className="insights-grid">
        {/* Summary */}
        <div className="insight-card">
          <div className="insight-card__title">Summary</div>
          <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
            {insights.summary || <span style={{ color: 'var(--text-muted)' }}>None identified</span>}
          </p>
        </div>

        {/* Action Items */}
        <div className="insight-card">
          <div className="insight-card__title">Action Items</div>
          {insights.action_items.length === 0 ? (
            <p style={{ fontSize: '0.875rem', color: 'var(--text-muted)' }}>None identified</p>
          ) : (
            <ul className="insight-card__list">
              {insights.action_items.map((item, i) => (
                <li key={i}>
                  <CheckSquare size={13} style={{ color: 'var(--accent)', flexShrink: 0, marginTop: '2px' }} />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Decisions */}
        <div className="insight-card">
          <div className="insight-card__title">Decisions</div>
          {insights.decisions.length === 0 ? (
            <p style={{ fontSize: '0.875rem', color: 'var(--text-muted)' }}>None identified</p>
          ) : (
            <ul className="insight-card__list">
              {insights.decisions.map((item, i) => (
                <li key={i}>
                  <Circle size={8} style={{ color: 'var(--success)', flexShrink: 0, marginTop: '5px', fill: 'var(--success)' }} />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Questions Raised */}
        <div className="insight-card">
          <div className="insight-card__title">Questions Raised</div>
          {insights.questions_raised.length === 0 ? (
            <p style={{ fontSize: '0.875rem', color: 'var(--text-muted)' }}>None identified</p>
          ) : (
            <ul className="insight-card__list">
              {insights.questions_raised.map((item, i) => (
                <li key={i}>
                  <HelpCircle size={13} style={{ color: 'var(--warning)', flexShrink: 0, marginTop: '2px' }} />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Follow-up Email — full width */}
        <div className="insight-card email-card">
          <div className="insight-card__title" style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
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

      {/* Regenerate button */}
      <div style={{ marginTop: '1rem', textAlign: 'right' }}>
        <button
          className="btn btn--ghost btn--sm"
          onClick={handleGenerate}
          disabled={isLoading}
        >
          <Sparkles size={13} />
          Regenerate
        </button>
      </div>
    </div>
  );
};
