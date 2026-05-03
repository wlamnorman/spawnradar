(function () {
  "use strict";

  const heading = document.getElementById("status-heading");
  const message = document.getElementById("status-message");
  const fallbackLink = document.getElementById("fallback-link");
  if (!heading || !message || !fallbackLink) {
    return;
  }

  const MAX_WAIT_MS = 30000;
  const POLL_INTERVAL_MS = 1500;
  const started = Date.now();

  async function checkStatus() {
    try {
      const response = await fetch("/billing/status");
      const data = await response.json();
      if (data.active) {
        window.location.href = "/billing";
        return;
      }
    } catch (_) {
      // Leave the loading state in place and retry until timeout.
    }

    if (Date.now() - started >= MAX_WAIT_MS) {
      heading.textContent = "Almost there...";
      message.textContent =
        "Taking longer than expected. Your subscription should appear shortly.";
      fallbackLink.hidden = false;
      return;
    }

    window.setTimeout(checkStatus, POLL_INTERVAL_MS);
  }

  checkStatus();
})();
