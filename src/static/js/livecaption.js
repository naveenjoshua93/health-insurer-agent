function downsampleBuffer(buffer, inputRate, targetRate) {
  if (targetRate === inputRate) return buffer;
  const ratio = inputRate / targetRate;
  const newLength = Math.round(buffer.length / ratio);
  const result = new Float32Array(newLength);
  let offsetResult = 0;
  let offsetBuffer = 0;
  while (offsetResult < newLength) {
    const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio);
    let accum = 0;
    let count = 0;
    for (let i = offsetBuffer; i < nextOffsetBuffer && i < buffer.length; i++) {
      accum += buffer[i];
      count++;
    }
    result[offsetResult] = count ? accum / count : 0;
    offsetResult++;
    offsetBuffer = nextOffsetBuffer;
  }
  return result;
}

function floatTo16BitPCM(float32Array) {
  const out = new Int16Array(float32Array.length);
  for (let i = 0; i < float32Array.length; i++) {
    const s = Math.max(-1, Math.min(1, float32Array[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}

// Sarvam's own end-of-speech VAD event fires on ordinary thinking pauses, cutting
// callers off mid-thought. We only use Sarvam for live transcription now; end-of-turn
// is decided locally from raw mic amplitude, with a generous silence hold so people
// can pause to think without being cut off.
const SILENCE_RMS_THRESHOLD = 0.015;
const SILENCE_HOLD_MS = 3000;

function rms(float32Array) {
  let sum = 0;
  for (let i = 0; i < float32Array.length; i++) sum += float32Array[i] * float32Array[i];
  return Math.sqrt(sum / float32Array.length);
}

class LiveCaptioner {
  constructor(onTranscript, onEndSpeech, onStartSpeech) {
    this.onTranscript = onTranscript;
    this.onEndSpeech = onEndSpeech || (() => {});
    this.onStartSpeech = onStartSpeech || (() => {});
    this.ws = null;
    this.audioCtx = null;
    this.processor = null;
    this.source = null;
    this.silentGain = null;
    this.hasSpoken = false;
    this.silenceSinceMs = null;
    this.ended = false;
  }

  start(stream) {
    const wsProtocol = window.location.protocol === "https:" ? "wss" : "ws";
    this.ws = new WebSocket(`${wsProtocol}://${window.location.host}/ws/live-transcribe`);
    this.ws.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data);
        if (data.kind === "transcript") {
          this.onTranscript(data.transcript);
        }
      } catch (err) {
        // ignore malformed frames
      }
    };

    this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    this.source = this.audioCtx.createMediaStreamSource(stream);
    this.processor = this.audioCtx.createScriptProcessor(4096, 1, 1);
    const inputRate = this.audioCtx.sampleRate;

    this.processor.onaudioprocess = (e) => {
      const input = e.inputBuffer.getChannelData(0);

      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        const downsampled = downsampleBuffer(input, inputRate, 16000);
        const pcm16 = floatTo16BitPCM(downsampled);
        this.ws.send(pcm16.buffer);
      }

      if (this.ended) return;
      const level = rms(input);
      const now = this.audioCtx.currentTime * 1000;
      if (level >= SILENCE_RMS_THRESHOLD) {
        if (!this.hasSpoken) {
          this.hasSpoken = true;
          this.onStartSpeech();
        }
        this.silenceSinceMs = null;
      } else if (this.hasSpoken) {
        if (this.silenceSinceMs === null) {
          this.silenceSinceMs = now;
        } else if (now - this.silenceSinceMs >= SILENCE_HOLD_MS) {
          this.ended = true;
          this.onEndSpeech();
        }
      }
    };

    // Route through a zero-gain node so onaudioprocess fires without audible echo.
    this.silentGain = this.audioCtx.createGain();
    this.silentGain.gain.value = 0;
    this.source.connect(this.processor);
    this.processor.connect(this.silentGain);
    this.silentGain.connect(this.audioCtx.destination);
  }

  stop() {
    if (this.processor) this.processor.disconnect();
    if (this.source) this.source.disconnect();
    if (this.silentGain) this.silentGain.disconnect();
    if (this.audioCtx) this.audioCtx.close();
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.close();
  }
}
