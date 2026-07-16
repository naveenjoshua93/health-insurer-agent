class ApiError extends Error {
  constructor(status, detail) {
    super(detail || `request failed: ${status}`);
    this.status = status;
    this.isSessionMissing = status === 404 || status === 410;
  }
}

async function parseOrThrow(res) {
  if (!res.ok) {
    let detail = null;
    try {
      detail = (await res.json()).detail;
    } catch (err) {
      // response wasn't JSON - fall back to status-only error
    }
    throw new ApiError(res.status, detail);
  }
  return res.json();
}

const Api = {
  async createSession() {
    const res = await fetch("/session", { method: "POST" });
    return parseOrThrow(res);
  },

  async getSessionStatus(sessionId) {
    const res = await fetch(`/session/${sessionId}`);
    return parseOrThrow(res);
  },

  async getIntro(sessionId) {
    const res = await fetch(`/session/${sessionId}/intro`, { method: "POST" });
    return parseOrThrow(res);
  },

  async setLanguageOverride(sessionId, languageCode) {
    const body = new URLSearchParams({ language_code: languageCode });
    const res = await fetch(`/session/${sessionId}/language`, { method: "POST", body });
    return parseOrThrow(res);
  },

  async sendTurn(sessionId, audioBlob) {
    const form = new FormData();
    form.append("session_id", sessionId);
    form.append("audio", audioBlob, "turn.webm");
    const res = await fetch("/turn", { method: "POST", body: form });
    return parseOrThrow(res);
  },

  async resolveTurn(sessionId) {
    const res = await fetch(`/session/${sessionId}/resolve`, { method: "POST" });
    return parseOrThrow(res);
  },

  async uploadDocument(sessionId, file) {
    const form = new FormData();
    form.append("session_id", sessionId);
    form.append("file", file);
    const res = await fetch("/document", { method: "POST", body: form });
    return parseOrThrow(res);
  },

  async submitFeedback(sessionId, thumbsUp) {
    const body = new URLSearchParams({ thumbs_up: thumbsUp ? "true" : "false" });
    const res = await fetch(`/session/${sessionId}/feedback`, { method: "POST", body });
    return parseOrThrow(res);
  },

  async getAudit(sessionId) {
    const res = await fetch(`/audit/${sessionId}`);
    return parseOrThrow(res);
  },

  async listSessions() {
    const res = await fetch("/sessions");
    return parseOrThrow(res);
  },

  async getMetrics() {
    const res = await fetch("/metrics");
    return parseOrThrow(res);
  },
};

function playAudioBase64(base64) {
  const audio = new Audio(`data:audio/wav;base64,${base64}`);
  audio.play();
  return audio;
}

function playAudioBase64Async(base64) {
  return new Promise((resolve) => {
    const audio = new Audio(`data:audio/wav;base64,${base64}`);
    audio.onended = resolve;
    audio.onerror = resolve;
    audio.play().catch(resolve);
  });
}

const LANGUAGE_NAMES = {
  "hi-IN": "Hindi", "ml-IN": "Malayalam", "en-IN": "English", "ta-IN": "Tamil",
  "te-IN": "Telugu", "kn-IN": "Kannada", "bn-IN": "Bengali", "mr-IN": "Marathi",
  "gu-IN": "Gujarati", "pa-IN": "Punjabi", "od-IN": "Odia", "unknown": "Detecting…",
};

function languageLabel(code) {
  return LANGUAGE_NAMES[code] || code || "Detecting…";
}
