/**
 * Upgrade gate — intercepts filter/workflow actions for free users
 * and shows a subscribe modal instead of processing the action.
 *
 * Reads gate flags from data-filters-unlocked / data-workflow-unlocked
 * on the .matches-toolbar element.  Server-side enforcement is the
 * real security layer; this is UX sugar.
 */
(function () {
  "use strict";

  var toolbar = document.querySelector("[data-filters-unlocked]");
  if (!toolbar) return;

  var filtersUnlocked = toolbar.dataset.filtersUnlocked === "true";
  var workflowUnlocked = toolbar.dataset.workflowUnlocked === "true";

  if (filtersUnlocked && workflowUnlocked) return;

  var modal = document.getElementById("upgrade-gate-modal");
  if (!modal) return;

  var titleEl = document.getElementById("upgrade-gate-title");
  var textEl = document.getElementById("upgrade-gate-text");
  var closeBtn = modal.querySelector(".upgrade-gate-modal-close");

  function showGate(title, text) {
    titleEl.textContent = title;
    textEl.textContent = text;
    modal.showModal();
  }

  closeBtn.addEventListener("click", function () {
    modal.close();
  });

  modal.addEventListener("click", function (e) {
    if (e.target === modal) modal.close();
  });

  /* --- Filter form submit --- */
  if (!filtersUnlocked) {
    var filterForm = document.querySelector("[data-range-filter-form]");
    if (filterForm) {
      filterForm.addEventListener("submit", function (e) {
        e.preventDefault();
        showGate(
          "Subscribe to unlock filters",
          "Filter creators by reach, overlap score, games played and contact method.",
        );
      });
    }
  }

  /* --- Status tab clicks --- */
  if (!workflowUnlocked) {
    document.querySelectorAll("[data-status-tab]").forEach(function (tab) {
      tab.addEventListener("click", function (e) {
        e.preventDefault();
        showGate(
          "Subscribe to unlock workflow",
          "Track your outreach pipeline by filtering creators by status.",
        );
      });
    });
  }

  /* --- Workflow actions (status change, save note, quick skip) ---
       Use capture phase so we fire before the existing inline handlers. */
  if (!workflowUnlocked) {
    document.addEventListener(
      "click",
      function (e) {
        var target = e.target.closest(
          "[data-match-status-option], [data-match-save-note], [data-match-quick-status]",
        );
        if (!target) return;
        e.preventDefault();
        e.stopPropagation();
        showGate(
          "Subscribe to unlock workflow",
          "Change creator status, add notes and manage your outreach pipeline.",
        );
      },
      true,
    );
  }
})();
