/**
 * queue.js — handles action button interactions for the review queue,
 * and live-updates the queue as discovery finds new prospects.
 */
(function () {
  "use strict";

  // ---------------------------------------------------------------------------
  // HTML helpers
  // ---------------------------------------------------------------------------

  function escHtml(str) {
    if (str == null) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  // ---------------------------------------------------------------------------
  // Card builder — mirrors the queue/review.html Jinja2 card template
  // ---------------------------------------------------------------------------

  function buildCard(item) {
    const scorePct = Math.round((item.priority_score || 0) * 100);
    const scoreClass =
      scorePct >= 70
        ? "score-green"
        : scorePct >= 50
          ? "score-yellow"
          : "score-red";

    const nameHtml = item.profile_url
      ? `<a href="${escHtml(item.profile_url)}" target="_blank" rel="noreferrer">${escHtml(item.display_name)}</a>`
      : escHtml(item.display_name);

    const avatarHtml = item.avatar_url
      ? `<img src="${escHtml(item.avatar_url)}" alt="" class="prospect-avatar" loading="lazy">`
      : "";

    const videoThumbs = (item.recent_video_thumbnails || [])
      .map(
        (url) =>
          `<img src="${escHtml(url)}" alt="Recent video" class="video-thumbnail" loading="lazy">`,
      )
      .join("");
    const videoThumbsHtml = videoThumbs
      ? `<div class="video-thumbnails">${videoThumbs}</div>`
      : "";

    const actionPill = item.suggested_action
      ? `<span class="pill pill-action pill-${escHtml(item.suggested_action.toLowerCase())}">${escHtml(item.suggested_action)}</span>`
      : "";

    const contactPill = item.contact_channel
      ? `<span class="pill">${escHtml(item.contact_channel)}</span>`
      : "";

    const audienceSpan = item.audience_size
      ? `<span class="subtle">${Number(item.audience_size).toLocaleString()} followers</span>`
      : "";

    const fitSummary = item.fit_summary
      ? `<p class="fit-summary">${escHtml(item.fit_summary)}</p>`
      : "";

    const breakdown = item.score_breakdown || {};
    const dims = [
      ["Genre fit", breakdown.genre_fit],
      ["Audience fit", breakdown.audience_fit],
      ["Platform fit", breakdown.platform_fit],
      ["Contactability", breakdown.contactability],
      ["Audience size", breakdown.audience_size_score],
    ].filter(([, v]) => v != null);

    const dimRows = dims
      .map(([label, val]) => {
        const pct = Math.round(val * 100);
        return `<div class="score-dim-card">
          <div class="score-dim-topline">
            <span class="score-dim-label">${escHtml(label)}</span>
            <span class="score-dim-value">${pct}%</span>
          </div>
          <span class="score-dim-bar"><span class="score-dim-fill" style="width:${pct}%"></span></span>
        </div>`;
      })
      .join("");

    const reasons = (breakdown.reasons || [])
      .map((r) => `<li>${escHtml(r)}</li>`)
      .join("");

    const scoreSnapshot =
      dims.length > 0
        ? `<section class="score-snapshot" aria-label="Score breakdown">
          <div class="score-snapshot-header">
            <h3 class="score-snapshot-title">Score breakdown</h3>
          </div>
          <div class="score-breakdown-grid">${dimRows}</div>
          ${reasons ? `<ul class="reasons-list">${reasons}</ul>` : ""}
        </section>`
        : "";

    const subjectField = item.subject_line
      ? `<div class="form-group">
          <label class="field-label">Subject line</label>
          <input type="text" class="subject-input" value="${escHtml(item.subject_line)}">
        </div>`
      : "";

    const whySelected = (breakdown.why_selected || "").trim();
    const whySelectedHtml = whySelected
      ? `<p class="why-selected">${escHtml(whySelected)}</p>`
      : "";

    return `<article class="queue-card" id="card-${escHtml(item.draft_item_id)}" data-draft-id="${escHtml(item.draft_item_id)}">
      <div class="queue-topline">
        <div class="queue-prospect-info">
          <div class="prospect-name-row">
            ${avatarHtml}
            <h2 class="prospect-name">
              ${nameHtml}
              <span class="subtle prospect-handle">${escHtml(item.handle)}</span>
            </h2>
          </div>
          <div class="meta-row">
            <span class="pill pill-platform">${escHtml(item.platform)}</span>
            ${actionPill}
            ${contactPill}
            ${audienceSpan}
          </div>
        </div>
        <div class="score-badge ${scoreClass}">
          <span class="score-number">${scorePct}</span>
          <span class="score-label">fit</span>
        </div>
      </div>
      ${videoThumbsHtml}
      ${fitSummary}
      ${scoreSnapshot}
      ${subjectField}
      <div class="form-group">
        <label class="field-label">Message</label>
        <textarea class="draft-body">${escHtml(item.body_text)}</textarea>
      </div>
      ${whySelectedHtml}
    </article>`;
  }

  // ---------------------------------------------------------------------------
  // Discovery polling — called by runDiscovery() after pipeline starts
  // ---------------------------------------------------------------------------

  /**
   * Poll the queue API and inject new cards as they arrive.
   *
   * Stops automatically after STABLE_POLLS_TO_STOP consecutive polls with no
   * new items, or after MAX_POLL_DURATION_MS — whichever comes first.
   *
   * @param {string} gameId
   * @param {function} [onStatusUpdate] - optional callback(text) for status messages
   */
  function startDiscoveryPolling(gameId, onStatusUpdate) {
    const POLL_INTERVAL_MS = 3000;
    const MAX_POLL_DURATION_MS = 120000; // 2 minutes hard cap
    const STABLE_POLLS_TO_STOP = 8; // stop after 8 consecutive empty polls once results have started

    // Seed known IDs from cards already in the DOM
    const knownIds = new Set(
      Array.from(document.querySelectorAll(".queue-card")).map(
        (c) => c.dataset.draftId,
      ),
    );

    let stablePolls = 0;
    let hasSeenItems = false; // don't count stable polls until first result arrives
    let intervalId = null;
    const startTime = Date.now();

    function updateStatus(text) {
      if (onStatusUpdate) onStatusUpdate(text);
    }

    function stop() {
      if (intervalId !== null) {
        clearInterval(intervalId);
        intervalId = null;
      }
    }

    async function poll() {
      if (Date.now() - startTime > MAX_POLL_DURATION_MS) {
        stop();
        updateStatus("Discovery complete.");
        return;
      }

      let data;
      try {
        const res = await fetch(`/api/games/${gameId}/queue`);
        if (!res.ok) return;
        data = await res.json();
      } catch (_) {
        return;
      }

      const items = data.items || [];
      const newItems = items.filter(
        (item) => !knownIds.has(item.draft_item_id),
      );

      if (newItems.length === 0) {
        // Only apply the stability cutoff after we've seen at least one result.
        // Before that, keep polling for the full MAX_POLL_DURATION_MS window.
        if (hasSeenItems) {
          stablePolls += 1;
          if (stablePolls >= STABLE_POLLS_TO_STOP) {
            stop();
            updateStatus("Discovery complete.");
          }
        }
        return;
      }

      hasSeenItems = true;
      stablePolls = 0;

      // Sort new items by priority_score descending so highest-fit items appear first
      newItems.sort(
        (a, b) => (b.priority_score || 0) - (a.priority_score || 0),
      );

      // Ensure the queue-list container exists (page may show empty-queue state)
      let list = document.getElementById("queue-list");
      if (!list) {
        const emptyEl = document.querySelector(".empty-queue");
        if (emptyEl) {
          const container = document.createElement("div");
          container.className = "queue-list";
          container.id = "queue-list";
          emptyEl.replaceWith(container);
        } else {
          // No suitable anchor — skip this poll
          return;
        }
        list = document.getElementById("queue-list");
      }

      for (const item of newItems) {
        knownIds.add(item.draft_item_id);

        const tmp = document.createElement("div");
        tmp.innerHTML = buildCard(item);
        const card = tmp.firstElementChild;

        // Insert in priority-score order among existing cards
        const cards = list.querySelectorAll(".queue-card");
        let inserted = false;
        for (const existing of cards) {
          const existingScore = parseFloat(
            existing.querySelector(".score-number")?.textContent || "0",
          );
          if (scorePct(item) > existingScore) {
            list.insertBefore(card, existing);
            inserted = true;
            break;
          }
        }
        if (!inserted) {
          list.appendChild(card);
        }

        attachCardListeners(card);

        // Brief fade-in animation
        card.style.opacity = "0";
        card.style.transition = "opacity 0.4s ease";
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            card.style.opacity = "1";
          });
        });
      }

      // Update the header count
      const countEl = document.getElementById("queue-count-label");
      if (countEl) {
        const total = list.querySelectorAll(".queue-card").length;
        const gameNameEl = countEl.querySelector("strong");
        const gameName = gameNameEl ? gameNameEl.textContent : "";
        countEl.innerHTML = `${total} prospect${total !== 1 ? "s" : ""} waiting for review in <strong>${escHtml(gameName)}</strong>.`;
      }

      updateStatus(
        `Found ${knownIds.size} prospect${knownIds.size !== 1 ? "s" : ""} so far…`,
      );
    }

    function scorePct(item) {
      return Math.round((item.priority_score || 0) * 100);
    }

    // Start polling
    intervalId = setInterval(poll, POLL_INTERVAL_MS);
    // Run once immediately so the first results appear without a 3s wait
    poll();
  }

  // Expose for use from inline scripts in templates
  window.attachCardListeners = attachCardListeners;
  window.startDiscoveryPolling = startDiscoveryPolling;
})();
