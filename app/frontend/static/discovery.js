(function () {
  "use strict";

  function csrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') || '' : '';
  }

  function waitForMinimum(startedAt, minBusyMs) {
    const delay = Math.max(0, Number(minBusyMs || 0) - (Date.now() - startedAt));
    if (delay <= 0) {
      return Promise.resolve();
    }
    return new Promise((resolve) => window.setTimeout(resolve, delay));
  }

  function createController(options) {
    const buttonSelector = options.buttonSelector || '[data-run-discovery]';
    const statusElementId = options.statusElementId || 'discovery-status-global';
    const minBusyMs = Number(options.minBusyMs || 0);
    let latestUsage = options.initialUsage || null;

    function buttons() {
      return Array.from(document.querySelectorAll(buttonSelector));
    }

    function buttonIsDiscoveryReady(button) {
      return button.dataset.discoveryReady !== 'false';
    }

    function buttonForGame(gameId) {
      return buttons().find((button) => button.dataset.gameId === gameId) || null;
    }

    function setBusy(busy) {
      buttons().forEach((button) => {
        if (!buttonIsDiscoveryReady(button)) {
          return;
        }
        const defaultLabel = button.dataset.defaultLabel || 'Run Discovery';
        const busyLabel = button.dataset.busyLabel || 'Running Discovery...';
        button.textContent = busy ? busyLabel : defaultLabel;
        button.dataset.busy = busy ? 'true' : 'false';
        button.classList.toggle('is-busy', busy);
      });
    }

    function setDisabled(disabled) {
      buttons().forEach((button) => {
        const nextDisabled = disabled || !buttonIsDiscoveryReady(button);
        button.disabled = nextDisabled;
        button.setAttribute('aria-disabled', nextDisabled ? 'true' : 'false');
      });
    }

    function setStatus(text, blocked) {
      const status = document.getElementById(statusElementId);
      if (!status) {
        return;
      }
      status.textContent = text;
      status.classList.toggle('is-blocked', Boolean(blocked));
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
      setStatus(usage.message, !usage.can_run);
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
      setStatus(opts.startMessage || 'Starting discovery…', false);

      let res;
      let data = null;
      try {
        res = await fetch(`/api/games/${gameId}/run-ingestion`, {
          method: 'POST',
          headers: { 'X-CSRF-Token': csrfToken() },
        });
        try {
          data = await res.json();
        } catch (_) {
          data = null;
        }
      } catch (_) {
        await waitForMinimum(startedAt, opts.minBusyMs ?? minBusyMs);
        setStatus('Network error. Please try again.', true);
        setBusy(false);
        setDisabled(!(latestUsage && latestUsage.can_run));
        return { ok: false, error: 'network' };
      }

      if (!res.ok) {
        await waitForMinimum(startedAt, opts.minBusyMs ?? minBusyMs);
        const message = (data && data.detail) || 'Error starting discovery.';
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
        syncUsage,
        getLatestUsage,
      };

      if (typeof opts.onSuccess === 'function') {
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
