const Api = {
  async createSession() {
    const res = await fetch("/session", { method: "POST" });
    return res.json();
  },

  async getSessionStatus(sessionId) {
    const res = await fetch(`/session/${sessionId}`);
    return res.json();
  },

  async getIntro(sessionId) {
    const res = await fetch(`/session/${sessionId}/intro`, { method: "POST" });
    return res.json();
  },

  async setLanguageOverride(sessionId, languageCode) {
    const body = new URLSearchParams({ language_code: languageCode });
    const res = await fetch(`/session/${sessionId}/language`, { method: "POST", body });
    return res.json();
  },

  async sendTurn(sessionId, audioBlob) {
    const form = new FormData();
    form.append("session_id", sessionId);
    form.append("audio", audioBlob, "turn.webm");
    const res = await fetch("/turn", { method: "POST", body: form });
    if (!res.ok) throw new Error(`turn failed: ${res.status}`);
    return res.json();
  },

  async uploadDocument(sessionId, file) {
    const form = new FormData();
    form.append("session_id", sessionId);
    form.append("file", file);
    const res = await fetch("/document", { method: "POST", body: form });
    if (!res.ok) throw new Error(`document upload failed: ${res.status}`);
    return res.json();
  },

  async submitFeedback(sessionId, thumbsUp) {
    const body = new URLSearchParams({ thumbs_up: thumbsUp ? "true" : "false" });
    const res = await fetch(`/session/${sessionId}/feedback`, { method: "POST", body });
    return res.json();
  },

  async getAudit(sessionId) {
    const res = await fetch(`/audit/${sessionId}`);
    return res.json();
  },

  async listSessions() {
    const res = await fetch("/sessions");
    return res.json();
  },

  async getMetrics() {
    const res = await fetch("/metrics");
    return res.json();
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
