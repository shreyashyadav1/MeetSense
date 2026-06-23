import { useCallback, useEffect, useRef, useState } from 'react';
import type { MicrophoneStatus } from '../types';

interface UseMicrophoneOptions {
  onChunk: (chunk: Blob) => void;
}

export function useMicrophone({ onChunk }: UseMicrophoneOptions): {
  status: MicrophoneStatus;
  startRecording: () => Promise<void>;
  stopRecording: () => void;
  audioLevel: number;
} {
  const [status, setStatus] = useState<MicrophoneStatus>('idle');
  const [audioLevel, setAudioLevel] = useState(0);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animFrameRef = useRef<number | null>(null);
  const isRecordingRef = useRef(false);
  const onChunkRef = useRef(onChunk);

  // Keep onChunk ref in sync so startRecording closure is always current
  useEffect(() => {
    onChunkRef.current = onChunk;
  }, [onChunk]);

  const stopLevelLoop = useCallback(() => {
    if (animFrameRef.current !== null) {
      cancelAnimationFrame(animFrameRef.current);
      animFrameRef.current = null;
    }
  }, []);

  const startLevelLoop = useCallback(() => {
    const analyser = analyserRef.current;
    if (!analyser) return;

    const data = new Uint8Array(analyser.frequencyBinCount);

    const tick = () => {
      if (!isRecordingRef.current) return;

      analyser.getByteFrequencyData(data);

      // Compute RMS of frequency data, normalised to 0-100
      let sum = 0;
      for (let i = 0; i < data.length; i++) {
        sum += data[i] * data[i];
      }
      const rms = Math.sqrt(sum / data.length);
      const normalised = Math.min(100, Math.round((rms / 128) * 100));

      setAudioLevel(normalised);
      animFrameRef.current = requestAnimationFrame(tick);
    };

    animFrameRef.current = requestAnimationFrame(tick);
  }, []);

  const stopRecording = useCallback(() => {
    isRecordingRef.current = false;
    stopLevelLoop();
    setAudioLevel(0);

    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
    mediaRecorderRef.current = null;

    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }

    if (audioContextRef.current) {
      audioContextRef.current.close().catch(() => {});
      audioContextRef.current = null;
    }

    analyserRef.current = null;
    setStatus('idle');
  }, [stopLevelLoop]);

  const startRecording = useCallback(async () => {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setStatus('unsupported');
      return;
    }

    setStatus('requesting');

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      console.error('[useMicrophone] getUserMedia failed:', err);
      setStatus('error');
      return;
    }

    streamRef.current = stream;

    // Set up Web Audio API for level metering
    try {
      const audioContext = new AudioContext();
      audioContextRef.current = audioContext;

      const source = audioContext.createMediaStreamSource(stream);
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.6;
      source.connect(analyser);
      analyserRef.current = analyser;
    } catch (err) {
      console.error('[useMicrophone] AudioContext setup failed:', err);
      // Non-fatal — recording can continue without level metering
    }

    // Pick the best supported MIME type
    const mimeTypes = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg'];
    const mimeType = mimeTypes.find((t) => MediaRecorder.isTypeSupported(t)) ?? '';

    let recorder: MediaRecorder;
    try {
      recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    } catch (err) {
      console.error('[useMicrophone] MediaRecorder creation failed:', err);
      setStatus('error');
      stream.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
      return;
    }

    mediaRecorderRef.current = recorder;

    recorder.ondataavailable = (event: BlobEvent) => {
      if (event.data && event.data.size > 0) {
        onChunkRef.current(event.data);
      }
    };

    recorder.onerror = (event) => {
      console.error('[useMicrophone] MediaRecorder error:', event);
      setStatus('error');
    };

    recorder.onstop = () => {
      // Cleanup already handled in stopRecording; this is a safety net
    };

    isRecordingRef.current = true;
    recorder.start(250); // emit chunks every 250 ms
    setStatus('active');
    startLevelLoop();
  }, [startLevelLoop]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      isRecordingRef.current = false;
      stopLevelLoop();

      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
        mediaRecorderRef.current.stop();
      }
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
      }
      if (audioContextRef.current) {
        audioContextRef.current.close().catch(() => {});
      }
    };
  }, [stopLevelLoop]);

  return { status, startRecording, stopRecording, audioLevel };
}
