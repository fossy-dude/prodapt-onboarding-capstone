const CHAT_SESSION_STORAGE_KEY = "sboai_chat_session_id";

function getOrCreateChatSessionId(): string {
  try {
    const stored = sessionStorage.getItem(CHAT_SESSION_STORAGE_KEY);
    if (stored) {
      return stored;
    }
  } catch {
    // sessionStorage may be unavailable (private mode / disabled) — derive fresh.
  }
  const id =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : `chat-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  try {
    sessionStorage.setItem(CHAT_SESSION_STORAGE_KEY, id);
  } catch {
    // Best-effort persistence; the in-memory id still works for this session.
  }
  return id;
}

export { getOrCreateChatSessionId };
