export class StaleRequestError extends Error {
  constructor() {
    super("A newer request replaced this one.");
    this.name = "StaleRequestError";
  }
}

export class ApiClient {
  constructor(languageProvider) {
    this.languageProvider = languageProvider;
    this.requests = new Map();
    this.sequence = 0;
  }

  abortAll() {
    this.requests.forEach(({ controller }) => controller.abort());
    this.requests.clear();
  }

  async request(path, options = {}, config = {}) {
    const scope = config.scope || `${options.method || "GET"}:${path}`;
    const previous = this.requests.get(scope);
    if (previous) previous.controller.abort();

    const controller = new AbortController();
    const requestId = ++this.sequence;
    this.requests.set(scope, { controller, requestId });
    const timeout = window.setTimeout(
      () => controller.abort("timeout"),
      config.timeout || 30000,
    );

    const language = Object.prototype.hasOwnProperty.call(config, "language")
      ? config.language
      : this.languageProvider();
    const url = withLanguage(path, language);
    try {
      const response = await fetch(url, {
        ...options,
        signal: controller.signal,
        headers: {
          ...(options.body ? { "Content-Type": "application/json" } : {}),
          ...(options.headers || {}),
        },
      });
      const current = this.requests.get(scope);
      if (!current || current.requestId !== requestId) throw new StaleRequestError();
      let payload = null;
      try { payload = await response.json(); } catch (_) { /* non-JSON download/error */ }
      if (!response.ok) {
        const error = new Error(
          payload?.error?.message || "The server could not complete that request.",
        );
        error.code = payload?.error?.code;
        error.details = payload?.error || {};
        throw error;
      }
      return payload;
    } catch (error) {
      if (error instanceof StaleRequestError) throw error;
      if (error.name === "AbortError") {
        const timedOut = controller.signal.reason === "timeout";
        const wrapped = new Error(timedOut ? "The server took too long to respond." : "Request superseded.");
        wrapped.code = timedOut ? "request_timeout" : "request_aborted";
        throw wrapped;
      }
      throw error;
    } finally {
      window.clearTimeout(timeout);
      const current = this.requests.get(scope);
      if (current?.requestId === requestId) this.requests.delete(scope);
    }
  }
}

function withLanguage(path, language) {
  if (!language) return path;
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}language=${encodeURIComponent(language)}`;
}
