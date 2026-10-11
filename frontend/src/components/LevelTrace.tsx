import React, { useEffect, useRef, useState } from 'react';
import { usePrefersReducedMotion } from '../hooks/usePrefersReducedMotion';
import './LevelTrace.css';

const SAMPLES = 32;
/** Matches the microphone's own level refresh rate. */
const SAMPLE_INTERVAL_MS = 100;

/** Quiet speech still registers: perceived loudness is closer to the square root of the level. */
const toBarScale = (level: number) => Math.min(1, Math.max(0.08, Math.sqrt(level / 100)));

interface LevelTraceProps {
  /** Input level from 0 to 100. */
  level: number;
}

/**
 * The last few seconds of microphone input as a small trace, so it's obvious
 * at a glance that the microphone is hearing the room. With reduced motion it
 * becomes a plain level bar that doesn't scroll.
 */
export const LevelTrace: React.FC<LevelTraceProps> = ({ level }) => {
  const reduceMotion = usePrefersReducedMotion();
  const latest = useRef(level);
  const [history, setHistory] = useState<number[]>(() => new Array<number>(SAMPLES).fill(0));

  useEffect(() => {
    latest.current = level;
  }, [level]);

  useEffect(() => {
    if (reduceMotion) return;
    const timer = setInterval(() => {
      setHistory((previous) => [...previous.slice(1), latest.current]);
    }, SAMPLE_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [reduceMotion]);

  const meterProps = {
    role: 'meter',
    'aria-label': 'Microphone level',
    'aria-valuemin': 0,
    'aria-valuemax': 100,
    'aria-valuenow': Math.round(level),
  } as const;

  if (reduceMotion) {
    return (
      <div className="level-trace level-trace--bar" {...meterProps}>
        <span style={{ transform: `scaleX(${level / 100})` }} />
      </div>
    );
  }

  return (
    <div className="level-trace" {...meterProps}>
      {history.map((value, index) => (
        <span key={index} style={{ transform: `scaleY(${toBarScale(value)})` }} />
      ))}
    </div>
  );
};
