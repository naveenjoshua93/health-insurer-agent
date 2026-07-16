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
  }

  start(stream) {
    const wsProtocol = window.location.protocol === "https:" ? "wss" : "ws";
    this.ws = new WebSocket(`${wsProtocol}://${window.location.host}/ws/live-transcribe`);
    this.ws.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data);
        if (data.kind === "transcript") {
          this.onTranscript(data.transcript);
        } else if (data.kind === "vad" && data.signal_type === "END_SPEECH") {
          this.onEndSpeech();
        } else if (data.kind === "vad" && data.signal_type === "START_SPEECH") {
          this.onStartSpeech();
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
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
      const input = e.inputBuffer.getChannelData(0);
      const downsampled = downsampleBuffer(input, inputRate, 16000);
      const pcm16 = floatTo16BitPCM(downsampled);
      this.ws.send(pcm16.buffer);
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
