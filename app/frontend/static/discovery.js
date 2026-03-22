(function () {
  "use strict";

  function csrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") || "" : "";
  }

  function waitForMinimum(startedAt, minBusyMs) {
    const delay = Math.max(
      0,
      Number(minBusyMs || 0) - (Date.now() - startedAt),
    );
    if (delay <= 0) {
      return Promise.resolve();
    }
    return new Promise((resolve) => window.setTimeout(resolve, delay));
  }

  function createController(options) {
    const buttonSelector = options.buttonSelector || "[data-run-discovery]";
    const statusElementId =
      options.statusElementId || "discovery-status-global";
    const minBusyMs = Number(options.minBusyMs || 0);
    const hideReadyMessage = Boolean(options.hideReadyMessage);
    let latestUsage = options.initialUsage || null;

    function buttons() {
      return Array.from(document.querySelectorAll(buttonSelector));
    }

    function buttonIsDiscoveryReady(button) {
      return button.dataset.discoveryReady !== "false";
    }

    function buttonForGame(gameId) {
      return (
        buttons().find((button) => button.dataset.gameId === gameId) || null
      );
    }

    function setBusy(busy) {
      buttons().forEach((button) => {
        if (!buttonIsDiscoveryReady(button)) {
          return;
        }
        const defaultLabel = button.dataset.defaultLabel || "Run Discovery";
        const busyLabel = button.dataset.busyLabel || "Running Discovery...";
        button.textContent = busy ? busyLabel : defaultLabel;
        button.dataset.busy = busy ? "true" : "false";
        button.classList.toggle("is-busy", busy);
      });
    }

    function setDisabled(disabled) {
      buttons().forEach((button) => {
        const nextDisabled = disabled || !buttonIsDiscoveryReady(button);
        button.disabled = nextDisabled;
        button.setAttribute("aria-disabled", nextDisabled ? "true" : "false");
      });
    }

    function setStatus(text, blocked) {
      const status = document.getElementById(statusElementId);
      if (!status) {
        return;
      }
      const nextText = text || "";
      status.textContent = nextText;
      status.hidden = nextText.length === 0;
      status.classList.toggle("is-blocked", Boolean(blocked));
    }

    function syncQuotaBars(usage) {
      if (!usage) {
        return;
      }
      Array.from(document.querySelectorAll("[data-discovery-window]")).forEach(
        (row) => {
          const windowName = row.dataset.discoveryWindow;
          const windowUsage = usage[windowName];
          if (!windowUsage || Number(windowUsage.limit || 0) <= 0) {
            row.hidden = true;
            return;
          }
          row.hidden = false;
          const remaining = Number(windowUsage.remaining || 0);
          const limit = Number(windowUsage.limit || 0);
          const pct =
            limit > 0
              ? Math.max(0, Math.min(100, (remaining / limit) * 100))
              : 0;
          const fill = row.querySelector("[data-discovery-fill]");
          const count = row.querySelector("[data-discovery-count]");
          if (fill) {
            fill.style.width = `${pct}%`;
          }
          if (count) {
            count.textContent = `${remaining} / ${limit} left`;
          }
        },
      );
    }

    function getLatestUsage() {
      return latestUsage;
    }

    function syncUsage(usage) {
      if (!usage) {
        return;
      }
      latestUsage = usage;
      setBusy(false);
      setDisabled(!usage.can_run);
      const statusText = hideReadyMessage && usage.can_run ? "" : usage.message;
      setStatus(statusText, !usage.can_run);
      syncQuotaBars(usage);
    }

    async function run(gameId, runOptions) {
      const opts = runOptions || {};
      const targetButton = buttonForGame(gameId);
      if (targetButton && targetButton.disabled) {
        return { skipped: true };
      }

      const startedAt = Date.now();
      setBusy(true);
      setDisabled(true);
      setStatus(opts.startMessage || "Starting discovery…", false);

      let res;
      let data = null;
      try {
        const headers = { "X-CSRF-Token": csrfToken() };
        const fetchInit = { method: "POST", headers };
        if (opts.sources && opts.sources.length > 0) {
          headers["Content-Type"] = "application/json";
          fetchInit.body = JSON.stringify({ sources: opts.sources });
        }
        res = await fetch(`/api/games/${gameId}/run-ingestion`, fetchInit);
        try {
          data = await res.json();
        } catch (_) {
          data = null;
        }
      } catch (_) {
        await waitForMinimum(startedAt, opts.minBusyMs ?? minBusyMs);
        setStatus("Network error. Please try again.", true);
        setBusy(false);
        setDisabled(!(latestUsage && latestUsage.can_run));
        return { ok: false, error: "network" };
      }

      if (!res.ok) {
        await waitForMinimum(startedAt, opts.minBusyMs ?? minBusyMs);
        const message = (data && data.detail) || "Error starting discovery.";
        setStatus(message, true);
        setBusy(false);
        setDisabled(!(latestUsage && latestUsage.can_run));
        return { ok: false, data };
      }

      if (data && data.usage) {
        latestUsage = data.usage;
      }

      await waitForMinimum(startedAt, opts.minBusyMs ?? minBusyMs);

      const api = {
        buttons,
        setBusy,
        setDisabled,
        setStatus,
        syncQuotaBars,
        syncUsage,
        getLatestUsage,
      };

      if (typeof opts.onSuccess === "function") {
        await opts.onSuccess(data, api);
      }

      if (!opts.keepBusyOnSuccess) {
        setBusy(false);
        setDisabled(!(latestUsage && latestUsage.can_run));
      }

      if (opts.successMessage) {
        setStatus(opts.successMessage, false);
      }

      return { ok: true, data, api };
    }

    return {
      buttons,
      setBusy,
      setDisabled,
      setStatus,
      syncQuotaBars,
      syncUsage,
      getLatestUsage,
      run,
    };
  }

  window.SpawnRadarDiscovery = {
    csrfToken,
    createController,
  };
})();
