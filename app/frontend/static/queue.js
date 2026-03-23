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

  function contactChannelLabel(channel) {
    switch (channel) {
      case "email":
        return "Email";
      case "twitch_dm":
        return "Twitch DM";
      case "bluesky_reply":
        return "Bluesky reply";
      case "reddit_post":
        return "Reddit post";
      case "reddit_comment":
        return "Reddit comment";
      default:
        return channel
          ? channel
              .split("_")
              .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
              .join(" ")
          : "Profile";
    }
  }

  function contactChannelShortLabel(channel) {
    switch (channel) {
      case "email":
        return "Email";
      case "twitch_dm":
        return "DM";
      case "bluesky_reply":
        return "Reply";
      case "reddit_post":
        return "Post";
      case "reddit_comment":
        return "Comment";
      default:
        return "Profile";
    }
  }

  function buildContactPopover(item) {
    if (!item.contact_channel && !item.contact_value && !item.profile_url) {
      return "";
    }

    const routeRow = item.contact_channel
      ? `<div class="contact-popover-row">
          <span class="contact-popover-key">Best route</span>
          <span class="contact-popover-value">${escHtml(contactChannelLabel(item.contact_channel))}</span>
        </div>`
      : "";

    const contactRow = item.contact_value
      ? `<div class="contact-popover-row">
          <span class="contact-popover-key">${item.contact_channel === "email" ? "Email" : "Contact"}</span>
          ${
            item.contact_channel === "email"
              ? `<a href="mailto:${escHtml(item.contact_value)}" class="contact-popover-link">${escHtml(item.contact_value)}</a>`
              : `<span class="contact-popover-value">${escHtml(item.contact_value)}</span>`
          }
        </div>`
      : "";

    const profileRow = item.profile_url
      ? `<div class="contact-popover-row">
          <span class="contact-popover-key">Profile</span>
          <a href="${escHtml(item.profile_url)}" target="_blank" rel="noreferrer" class="contact-popover-link">${escHtml(item.handle || "Open profile")}</a>
        </div>`
      : "";

    return `<details class="contact-popover">
      <summary class="contact-trigger">
        <span class="contact-trigger-label">Contact</span>
        <span class="contact-trigger-value">${escHtml(item.contact_channel ? contactChannelShortLabel(item.contact_channel) : "Profile")}</span>
      </summary>
      <div class="contact-popover-panel">
        ${routeRow}
        ${contactRow}
        ${profileRow}
      </div>
    </details>`;
  }

  function closeContactPopovers(exceptPopover) {
    document.querySelectorAll(".contact-popover[open]").forEach((popover) => {
      if (popover !== exceptPopover) {
        popover.removeAttribute("open");
      }
    });
  }

  function audienceText(item) {
    if (item.platform === "twitch") {
      return item.followers_count
        ? `${Number(item.followers_count).toLocaleString()} followers`
        : "";
    }
    return item.audience_size
      ? `${Number(item.audience_size).toLocaleString()} followers`
      : "";
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

    const audienceLabel = audienceText(item);
    const contactPopover = buildContactPopover(item);

    const breakdown = item.score_breakdown || {};
    const fitSummary = (item.fit_summary || "").trim();
    const audienceSizeLabel =
      item.platform === "twitch" ? "Live audience" : "Audience size";
    const dims = [
      ["Genre fit", breakdown.genre_fit],
      ["Audience fit", breakdown.audience_fit],
      ["Platform fit", breakdown.platform_fit],
      ["Contactability", breakdown.contactability],
      [audienceSizeLabel, breakdown.audience_size_score],
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
    const insightsHtml =
      fitSummary || whySelected
        ? `<section class="queue-insights" aria-label="Match insights">
          ${
            fitSummary
              ? `<article class="insight-card">
            <h3 class="insight-card-title">Quick take</h3>
            <p class="insight-card-body">${escHtml(fitSummary)}</p>
          </article>`
              : ""
          }
          ${
            whySelected
              ? `<article class="insight-card">
            <h3 class="insight-card-title">Detailed rationale</h3>
            <p class="insight-card-body">${escHtml(whySelected)}</p>
          </article>`
              : ""
          }
        </section>`
        : "";

    return `<article class="queue-card" id="card-${escHtml(item.draft_item_id)}" data-draft-id="${escHtml(item.draft_item_id)}" data-platform="${escHtml(item.platform)}">
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
            ${audienceLabel ? `<span class="subtle prospect-followers">${escHtml(audienceLabel)}</span>` : ""}
          </div>
        </div>
        <div class="queue-topline-actions">
          ${contactPopover}
          <div class="score-badge ${scoreClass}">
            <span class="score-number">${scorePct}</span>
            <span class="score-label">fit</span>
          </div>
        </div>
      </div>
      ${videoThumbsHtml}
      ${scoreSnapshot}
      ${insightsHtml}
      <details class="message-accordion">
        <summary>Message draft</summary>
        <div class="message-accordion-body">
          ${subjectField}
          <div class="form-group">
            <label class="field-label">Message</label>
            <textarea class="draft-body">${escHtml(item.body_text)}</textarea>
          </div>
        </div>
      </details>
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
   * @param {function} [onStatusUpdate] - optional callback(text, blocked) for status messages
   * @param {function} [onComplete] - optional callback({ newItemsAdded, foundNewItems }) when polling ends
   */
  function startDiscoveryPolling(gameId, runId, onStatusUpdate, onComplete) {
    const POLL_INTERVAL_MS = 3000;
    const MAX_POLL_DURATION_MS = 600000; // 10 minutes hard cap
    const STABLE_POLLS_TO_STOP = 8; // stop after 8 consecutive empty polls once results have started

    const knownIds = new Set(
      Array.from(document.querySelectorAll(".queue-card")).map(
        (c) => c.dataset.draftId,
      ),
    );

    let stablePolls = 0;
    let foundNewItems = false;
    let newItemsAdded = 0;
    let intervalId = null;
    const startTime = Date.now();
    let finalStatus = runId ? "started" : null;
    let finalErrorMessage = "";

    function updateStatus(text, blocked) {
      if (onStatusUpdate) onStatusUpdate(text, blocked);
    }

    function finalMessage() {
      if (finalStatus === "failed") {
        return finalErrorMessage || "Discovery stopped because the run failed.";
      }
      if (!foundNewItems) {
        return "Discovery complete. No new prospects were found this run.";
      }
      return `Discovery complete. Added ${newItemsAdded} new prospect${newItemsAdded !== 1 ? "s" : ""}.`;
    }

    function currentFilter() {
      const active = document.querySelector(".queue-filter-btn.is-active");
      return active ? active.dataset.filter || "all" : "all";
    }

    function applyFilterToCard(card) {
      const filter = currentFilter();
      card.hidden = filter !== "all" && card.dataset.platform !== filter;
    }

    function stop() {
      if (intervalId !== null) {
        clearInterval(intervalId);
        intervalId = null;
      }
      updateStatus(finalMessage(), false);
      if (onComplete) {
        onComplete({ newItemsAdded, foundNewItems });
      }
    }

    async function poll() {
      if (Date.now() - startTime > MAX_POLL_DURATION_MS) {
        stop();
        return;
      }

      let data;
      try {
        const path = runId
          ? `/api/games/${gameId}/queue?run_id=${encodeURIComponent(runId)}`
          : `/api/games/${gameId}/queue`;
        const res = await fetch(path);
        if (!res.ok) return;
        data = await res.json();
      } catch (_) {
        return;
      }

      const run = data.discovery_run || null;
      if (run) {
        finalStatus = run.status || finalStatus;
        if (run.status === "failed") {
          finalErrorMessage =
            run.error_message || "Discovery stopped because the run failed.";
        }
      }

      const items = data.items || [];
      const newItems = items.filter(
        (item) => !knownIds.has(item.draft_item_id),
      );

      if (newItems.length === 0) {
        if (run && (run.status === "completed" || run.status === "failed")) {
          stop();
          return;
        }
        if (!run && foundNewItems) {
          stablePolls += 1;
          if (stablePolls >= STABLE_POLLS_TO_STOP) {
            stop();
          }
        }
        return;
      }

      foundNewItems = true;
      newItemsAdded += newItems.length;
      stablePolls = 0;

      newItems.sort(
        (a, b) => (b.priority_score || 0) - (a.priority_score || 0),
      );

      let list = document.getElementById("queue-list");
      if (!list) {
        const emptyEl = document.querySelector(".empty-queue");
        if (emptyEl) {
          const container = document.createElement("div");
          container.className = "queue-list";
          container.id = "queue-list";
          emptyEl.replaceWith(container);
        } else {
          return;
        }
        list = document.getElementById("queue-list");
      }

      for (const item of newItems) {
        knownIds.add(item.draft_item_id);

        const tmp = document.createElement("div");
        tmp.innerHTML = buildCard(item);
        const card = tmp.firstElementChild;

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
        applyFilterToCard(card);

        card.style.opacity = "0";
        card.style.transition = "opacity 0.4s ease";
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            card.style.opacity = "1";
          });
        });
      }

      const countEl = document.getElementById("queue-count-label");
      if (countEl) {
        const total = list.querySelectorAll(".queue-card").length;
        const gameNameEl = countEl.querySelector("strong");
        const gameName = gameNameEl ? gameNameEl.textContent : "";
        countEl.innerHTML = `${total} prospect${total !== 1 ? "s" : ""} waiting for review in <strong>${escHtml(gameName)}</strong>.`;
      }

      updateStatus(
        `Searching for new prospects… ${newItemsAdded} new prospect${newItemsAdded !== 1 ? "s" : ""} queued so far.`,
        false,
      );

      if (run && (run.status === "completed" || run.status === "failed")) {
        stop();
      }
    }

    function scorePct(item) {
      return Math.round((item.priority_score || 0) * 100);
    }

    intervalId = setInterval(poll, POLL_INTERVAL_MS);
    poll();
  }

  document.addEventListener("click", (event) => {
    const popover = event.target.closest(".contact-popover");
    if (popover) {
      closeContactPopovers(popover);
      return;
    }
    closeContactPopovers(null);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeContactPopovers(null);
    }
  });

  window.startDiscoveryPolling = startDiscoveryPolling;
})();
