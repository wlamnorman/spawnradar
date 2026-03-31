(function () {
  "use strict";

  function escapeHtml(value) {
    const node = document.createElement("div");
    node.textContent = value;
    return node.innerHTML;
  }

  function normalizeSearchValue(value) {
    return value
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .trim();
  }

  function levenshteinDistance(a, b) {
    const rows = a.length + 1;
    const cols = b.length + 1;
    const matrix = Array.from({ length: rows }, () => Array(cols).fill(0));

    for (let i = 0; i < rows; i += 1) {
      matrix[i][0] = i;
    }
    for (let j = 0; j < cols; j += 1) {
      matrix[0][j] = j;
    }

    for (let i = 1; i < rows; i += 1) {
      for (let j = 1; j < cols; j += 1) {
        const substitutionCost = a[i - 1] === b[j - 1] ? 0 : 1;
        matrix[i][j] = Math.min(
          matrix[i - 1][j] + 1,
          matrix[i][j - 1] + 1,
          matrix[i - 1][j - 1] + substitutionCost,
        );
      }
    }

    return matrix[a.length][b.length];
  }

  function scoreSuggestion(label, query) {
    if (!query) {
      return 0;
    }
    const normalizedLabel = normalizeSearchValue(label);
    if (!normalizedLabel) {
      return null;
    }
    if (normalizedLabel === query) {
      return 0;
    }
    if (normalizedLabel.startsWith(query)) {
      return 1;
    }
    const words = normalizedLabel.split(/[^a-z0-9]+/).filter(Boolean);
    if (words.some((word) => word.startsWith(query))) {
      return 2;
    }
    if (normalizedLabel.includes(query)) {
      return 3;
    }
    const compactLabel = normalizedLabel.replace(/[^a-z0-9]/g, "");
    const compactQuery = query.replace(/[^a-z0-9]/g, "");
    if (compactQuery && compactLabel.includes(compactQuery)) {
      return 4;
    }
    const distance = levenshteinDistance(compactLabel, compactQuery);
    const allowedDistance =
      compactQuery.length >= 8 ? 3 : compactQuery.length >= 5 ? 2 : 1;
    if (distance <= allowedDistance) {
      return 10 + distance;
    }
    return null;
  }

  function bindCharCounter(input) {
    const counterId = input.dataset.charCount;
    if (!counterId) {
      return;
    }
    const counter = document.getElementById(counterId);
    if (!counter) {
      return;
    }

    const sync = () => {
      counter.textContent = String(input.value.length);
    };

    input.addEventListener("input", sync);
    sync();
  }

  function initImportMenu(root) {
    const menu = root.querySelector(".game-import-menu");
    if (!menu) {
      return;
    }

    document.addEventListener("pointerdown", (event) => {
      if (!(event.target instanceof Node)) {
        return;
      }
      if (!menu.contains(event.target)) {
        menu.removeAttribute("open");
      }
    });

    const importBtn = root.querySelector("#import-url-btn");
    const importUrlInput = root.querySelector("#import_url");
    const statusEl = root.querySelector("#import-status");
    if (!importBtn || !importUrlInput) {
      return;
    }

    importBtn.addEventListener("click", async () => {
      const url = importUrlInput.value.trim();
      if (!url) {
        showImportStatus("Please enter a URL.", true);
        return;
      }

      importBtn.disabled = true;
      importBtn.textContent = "Importing…";
      showImportStatus("", false);

      try {
        const resp = await fetch("/games/import-url", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url }),
        });
        if (!resp.ok) {
          const err = await resp.json().catch(() => null);
          throw new Error(
            (err && err.detail) || `Import failed (${resp.status})`,
          );
        }
        const data = await resp.json();
        fillFormFromImport(root, data);
        showImportStatus(
          "Imported! Review the fields below, then Save.",
          false,
        );
      } catch (err) {
        showImportStatus(err.message, true);
      } finally {
        importBtn.disabled = false;
        importBtn.textContent = "Import";
      }
    });

    function showImportStatus(msg, isError) {
      if (!statusEl) return;
      if (!msg) {
        statusEl.hidden = true;
        return;
      }
      statusEl.hidden = false;
      statusEl.className = isError
        ? "alert alert-error"
        : "alert alert-success";
      statusEl.textContent = msg;
    }

    function fillFormFromImport(formRoot, data) {
      // Text fields
      setInput(formRoot, "#name", data.name || "");
      setInput(formRoot, "#summary", data.summary || "");
      setInput(formRoot, "#description", data.description || "");
      setInput(formRoot, "#website_url", data.website_url || "");

      // Update character counters
      formRoot.querySelectorAll("[data-char-count]").forEach((el) => {
        const counter = document.getElementById(el.dataset.charCount);
        if (counter) counter.textContent = el.value.length;
      });

      // Checkboxes: platforms
      setCheckboxes(formRoot, 'input[name="platforms"]', data.platforms || []);

      // Checkboxes: game modes
      setCheckboxes(
        formRoot,
        'input[name="igdb_game_mode_ids"]',
        (data.igdb_game_mode_ids || []).map(String),
      );

      // Tag pickers: clear and repopulate
      setTagPicker(formRoot, "igdb_genre_ids", data.igdb_genre_ids || []);
      setTagPicker(formRoot, "igdb_theme_ids", data.igdb_theme_ids || []);
      setTagPicker(formRoot, "igdb_keyword_ids", data.igdb_keyword_ids || []);
    }

    function setInput(formRoot, selector, value) {
      const el = formRoot.querySelector(selector);
      if (el) el.value = value;
    }

    function setCheckboxes(formRoot, selector, values) {
      formRoot.querySelectorAll(selector).forEach((cb) => {
        cb.checked = values.includes(cb.value);
      });
    }

    function setTagPicker(formRoot, fieldName, values) {
      // Find the tag picker root that contains hidden inputs for this field
      formRoot
        .querySelectorAll("[data-tag-picker-root]")
        .forEach((pickerRoot) => {
          const hiddenInputs = pickerRoot.querySelector(
            "[data-tag-picker-hidden-inputs]",
          );
          if (!hiddenInputs) return;

          const pickerOptions = Array.isArray(pickerRoot._tagPickerOptions)
            ? pickerRoot._tagPickerOptions
            : Array.from(
                pickerRoot.querySelectorAll("[data-tag-picker-suggestion]"),
              ).map((button) => ({
                name: button.dataset.fieldName || "",
                value: button.dataset.fieldValue || "",
                label: button.dataset.label || button.textContent || "",
                pillClass: button.dataset.pillClass || "",
              }));

          // Check if this picker handles our field
          const existingInputs = hiddenInputs.querySelectorAll("input[name]");
          const handlesField =
            Array.from(existingInputs).some(
              (input) => input.name === fieldName,
            ) || pickerOptions.some((option) => option.name === fieldName);
          if (!handlesField) return;

          // Clear only the existing hidden inputs for this specific field.
          hiddenInputs
            .querySelectorAll(`input[name="${fieldName}"]`)
            .forEach((input) => input.remove());

          // Add new values by matching against the picker's full option bank,
          // not only the currently rendered suggestion subset.
          const valStrings = values.map(String);
          pickerOptions.forEach((option) => {
            if (
              option.name === fieldName &&
              valStrings.includes(option.value)
            ) {
              const input = document.createElement("input");
              input.type = "hidden";
              input.name = option.name;
              input.value = option.value;
              input.dataset.label = option.label;
              input.dataset.pillClass = option.pillClass;
              hiddenInputs.appendChild(input);
            }
          });

          // Re-render preview
          const preview = pickerRoot.querySelector("[data-tag-picker-preview]");
          if (preview) {
            const entries = Array.from(
              hiddenInputs.querySelectorAll("input[name]"),
            ).map((input) => ({
              name: input.name,
              value: input.value,
              label: input.dataset.label || input.value,
              pillClass: input.dataset.pillClass || "",
            }));
            if (!entries.length) {
              preview.innerHTML =
                '<span class="text-muted">No tags selected yet.</span>';
            } else {
              preview.innerHTML = entries
                .map(
                  (e) =>
                    `<button type="button" class="tag-pill tag-pill-button ${e.pillClass}" data-entry-name="${escapeHtml(e.name)}" data-entry-value="${escapeHtml(e.value)}" aria-label="Remove ${escapeHtml(e.label)}"><span class="tag-pill-label">${escapeHtml(e.label)}</span><span class="tag-remove">\u00d7</span></button>`,
                )
                .join("");
              // Bind click-to-remove handlers. Note: removeEntry() and
              // render() live inside initTagPicker's closure and are not
              // accessible here, so we manipulate the DOM directly.
              preview
                .querySelectorAll(".tag-pill-button")
                .forEach((button) => {
                  button.addEventListener("click", () => {
                    const eName = button.dataset.entryName || "";
                    const eValue = (
                      button.dataset.entryValue || ""
                    ).toLowerCase();
                    hiddenInputs
                      .querySelectorAll("input[name]")
                      .forEach((input) => {
                        if (
                          input.name === eName &&
                          input.value.toLowerCase() === eValue
                        ) {
                          input.remove();
                        }
                      });
                    button.remove();
                    // Show placeholder if no pills remain
                    if (
                      !preview.querySelector(".tag-pill-button")
                    ) {
                      preview.innerHTML =
                        '<span class="text-muted">No tags selected yet.</span>';
                    }
                  });
                });
            }
          }
        });
    }
  }

  function initTagPicker(root) {
    const searchInput = root.querySelector("[data-tag-picker-search]");
    const preview = root.querySelector("[data-tag-picker-preview]");
    const hiddenInputs = root.querySelector("[data-tag-picker-hidden-inputs]");
    const suggestions = root.querySelector("[data-tag-picker-suggestions]");
    if (!searchInput || !preview || !hiddenInputs) {
      return;
    }

    const allowCustom = searchInput.dataset.allowCustom === "true";
    const customFieldName = searchInput.dataset.customFieldName || "";
    const customPillClass = searchInput.dataset.customPillClass || "";
    const remoteSuggestionsUrl = searchInput.dataset.remoteSuggestionsUrl || "";
    const localSuggestionOptions = suggestions
      ? Array.from(
          suggestions.querySelectorAll("[data-tag-picker-suggestion]"),
        ).map((button) => ({
          name: button.dataset.fieldName || "",
          value: button.dataset.fieldValue || "",
          label: button.dataset.label || button.textContent || "",
          pillClass: button.dataset.pillClass || "",
        }))
      : [];
    root._tagPickerOptions = localSuggestionOptions;
    let activeRequest = null;
    let fetchTimer = null;
    let activeSuggestionIndex = -1;

    function entryKey(entry) {
      return `${entry.name}::${entry.value}`.toLowerCase();
    }

    function readEntries() {
      return Array.from(hiddenInputs.querySelectorAll("input[name]")).map(
        (input) => ({
          name: input.name,
          value: input.value,
          label: input.dataset.label || input.value,
          pillClass: input.dataset.pillClass || "",
        }),
      );
    }

    function writeEntry(entry) {
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = entry.name;
      input.value = entry.value;
      input.dataset.label = entry.label;
      input.dataset.pillClass = entry.pillClass;
      hiddenInputs.appendChild(input);
    }

    function addEntry(entry) {
      const existing = new Set(readEntries().map(entryKey));
      if (existing.has(entryKey(entry))) {
        return;
      }
      writeEntry(entry);
      render();
    }

    function removeEntry(entry) {
      Array.from(hiddenInputs.querySelectorAll("input[name]")).forEach(
        (input) => {
          if (
            input.name === entry.name &&
            input.value.toLowerCase() === entry.value.toLowerCase()
          ) {
            input.remove();
          }
        },
      );
      render();
    }

    function renderPreview() {
      const entries = readEntries();
      if (!entries.length) {
        preview.innerHTML =
          '<span class="text-muted">No tags selected yet.</span>';
        return;
      }
      preview.innerHTML = entries
        .map(
          (entry) =>
            `<button type="button" class="tag-pill tag-pill-button ${entry.pillClass}" data-entry-name="${escapeHtml(entry.name)}" data-entry-value="${escapeHtml(entry.value)}" aria-label="Remove ${escapeHtml(entry.label)}"><span class="tag-pill-label">${escapeHtml(entry.label)}</span><span class="tag-remove">×</span></button>`,
        )
        .join("");
      preview.querySelectorAll(".tag-pill-button").forEach((button) => {
        button.addEventListener("click", () => {
          removeEntry({
            name: button.dataset.entryName || "",
            value: button.dataset.entryValue || "",
          });
        });
      });
    }

    function getSuggestionButtons() {
      if (!suggestions) {
        return [];
      }
      return Array.from(
        suggestions.querySelectorAll("[data-tag-picker-suggestion]"),
      );
    }

    function setActiveSuggestion(index) {
      const buttons = getSuggestionButtons();
      if (!buttons.length) {
        activeSuggestionIndex = -1;
        return;
      }
      const nextIndex = Math.max(0, Math.min(index, buttons.length - 1));
      activeSuggestionIndex = nextIndex;
      buttons.forEach((button, buttonIndex) => {
        const isActive = buttonIndex === nextIndex;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-selected", isActive ? "true" : "false");
      });
      buttons[nextIndex].scrollIntoView({ block: "nearest" });
    }

    function moveActiveSuggestion(direction) {
      const buttons = getSuggestionButtons();
      if (!buttons.length) {
        activeSuggestionIndex = -1;
        return;
      }
      if (activeSuggestionIndex < 0) {
        setActiveSuggestion(direction > 0 ? 0 : buttons.length - 1);
        return;
      }
      const nextIndex =
        (activeSuggestionIndex + direction + buttons.length) % buttons.length;
      setActiveSuggestion(nextIndex);
    }

    function selectSuggestionButton(button) {
      addEntry({
        name: button.dataset.fieldName || "",
        value: button.dataset.fieldValue || "",
        label: button.dataset.label || button.textContent || "",
        pillClass: button.dataset.pillClass || "",
      });
      searchInput.value = "";
      render();
      hideSuggestions();
      searchInput.focus();
    }

    function renderSuggestions() {
      if (!suggestions) {
        return;
      }
      const selected = new Set(readEntries().map(entryKey));
      const query = normalizeSearchValue(searchInput.value);
      const matches = localSuggestionOptions
        .filter((option) => !selected.has(entryKey(option)))
        .map((option) => ({
          option,
          score: scoreSuggestion(option.label, query),
        }))
        .filter(({ score }) => query === "" || score !== null)
        .sort((left, right) => {
          const leftScore = left.score ?? 0;
          const rightScore = right.score ?? 0;
          if (leftScore !== rightScore) {
            return leftScore - rightScore;
          }
          return left.option.label.localeCompare(right.option.label);
        })
        .slice(0, query ? 12 : 24)
        .map(({ option }) => option);

      suggestions.innerHTML = matches
        .map(
          (option) =>
            `<button type="button" class="tag-suggestion" data-tag-picker-suggestion data-field-name="${escapeHtml(option.name)}" data-field-value="${escapeHtml(option.value)}" data-label="${escapeHtml(option.label)}" data-pill-class="${escapeHtml(option.pillClass)}">${escapeHtml(option.label)}</button>`,
        )
        .join("");
      bindSuggestionClicks();
      suggestions.hidden = matches.length === 0;
      if (!suggestions.hidden) {
        setActiveSuggestion(0);
      }
    }

    function renderRemoteSuggestions(items) {
      if (!suggestions) {
        return;
      }
      const selected = new Set(readEntries().map(entryKey));
      suggestions.innerHTML = items
        .filter(
          (item) =>
            !selected.has(
              entryKey({
                name: customFieldName,
                value: item.name,
              }),
            ),
        )
        .map(
          (item) =>
            `<button type="button" class="tag-suggestion" data-tag-picker-suggestion data-field-name="${escapeHtml(customFieldName)}" data-field-value="${escapeHtml(item.name)}" data-label="${escapeHtml(item.name)}" data-pill-class="${escapeHtml(customPillClass)}">${escapeHtml(item.name)}</button>`,
        )
        .join("");
      bindSuggestionClicks();
      suggestions.hidden = suggestions.children.length === 0;
      if (!suggestions.hidden) {
        setActiveSuggestion(0);
      }
    }

    function clearRemoteSuggestions() {
      if (!suggestions) {
        return;
      }
      activeSuggestionIndex = -1;
      suggestions.hidden = true;
      suggestions.innerHTML = "";
    }

    function fetchRemoteSuggestions(query) {
      if (!remoteSuggestionsUrl || !suggestions) {
        return;
      }
      if (activeRequest) {
        activeRequest.abort();
        activeRequest = null;
      }
      const normalizedQuery = query.trim();
      if (normalizedQuery.length < 2) {
        clearRemoteSuggestions();
        return;
      }
      activeRequest = new AbortController();
      fetch(
        `${remoteSuggestionsUrl}?q=${encodeURIComponent(normalizedQuery)}`,
        {
          signal: activeRequest.signal,
          headers: { Accept: "application/json" },
        },
      )
        .then((response) => (response.ok ? response.json() : []))
        .then((items) => {
          if (searchInput.value.trim() !== normalizedQuery) {
            return;
          }
          renderRemoteSuggestions(Array.isArray(items) ? items : []);
        })
        .catch((error) => {
          if (error && error.name === "AbortError") {
            return;
          }
          suggestions.hidden = true;
        })
        .finally(() => {
          activeRequest = null;
        });
    }

    function showSuggestions() {
      if (remoteSuggestionsUrl) {
        if (fetchTimer) {
          window.clearTimeout(fetchTimer);
        }
        fetchTimer = window.setTimeout(() => {
          fetchRemoteSuggestions(searchInput.value);
        }, 120);
        return;
      }
      if (!suggestions) {
        return;
      }
      renderSuggestions();
    }

    function hideSuggestions() {
      if (!suggestions) {
        return;
      }
      if (fetchTimer) {
        window.clearTimeout(fetchTimer);
        fetchTimer = null;
      }
      activeSuggestionIndex = -1;
      suggestions.hidden = true;
    }

    function addCustomEntries(rawValue) {
      rawValue
        .split(",")
        .map((value) => value.trim())
        .filter(Boolean)
        .forEach((value) => {
          addEntry({
            name: customFieldName,
            value,
            label: value,
            pillClass: customPillClass,
          });
        });
    }

    function addFirstMatchingSuggestion() {
      if (!suggestions) {
        return false;
      }
      const buttons = getSuggestionButtons();
      const match =
        activeSuggestionIndex >= 0
          ? buttons[activeSuggestionIndex]
          : buttons[0];
      if (!match) {
        return false;
      }
      selectSuggestionButton(match);
      return true;
    }

    function hasVisibleSuggestions() {
      return (
        !!suggestions &&
        !suggestions.hidden &&
        getSuggestionButtons().length > 0
      );
    }

    function render() {
      renderPreview();
      if (remoteSuggestionsUrl) {
        if (searchInput.value.trim()) {
          fetchRemoteSuggestions(searchInput.value);
        } else {
          clearRemoteSuggestions();
        }
      } else {
        renderSuggestions();
      }
    }

    function bindSuggestionClicks() {
      if (!suggestions) {
        return;
      }
      suggestions
        .querySelectorAll("[data-tag-picker-suggestion]")
        .forEach((button, index) => {
          button.onclick = () => {
            selectSuggestionButton(button);
          };
          button.onmouseenter = () => {
            setActiveSuggestion(index);
          };
        });
    }

    bindSuggestionClicks();

    searchInput.addEventListener("input", showSuggestions);
    searchInput.addEventListener("focus", showSuggestions);
    searchInput.addEventListener("blur", () => {
      window.setTimeout(hideSuggestions, 120);
    });
    searchInput.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        if (suggestions && suggestions.hidden) {
          showSuggestions();
          return;
        }
        moveActiveSuggestion(1);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        if (suggestions && suggestions.hidden) {
          showSuggestions();
          return;
        }
        moveActiveSuggestion(-1);
        return;
      }
      if (event.key === "Escape") {
        hideSuggestions();
        return;
      }
      if (event.key !== "Enter") {
        return;
      }
      event.preventDefault();
      const rawValue = searchInput.value.trim();
      if (!rawValue) {
        return;
      }
      if (hasVisibleSuggestions() && addFirstMatchingSuggestion()) {
        return;
      }
      if (allowCustom) {
        addCustomEntries(rawValue);
      } else {
        addFirstMatchingSuggestion();
      }
      searchInput.value = "";
      render();
      hideSuggestions();
    });

    render();
    hideSuggestions();

    document.addEventListener("pointerdown", (event) => {
      if (!root.contains(event.target)) {
        hideSuggestions();
      }
    });
  }

  function initGameForm(root) {
    root.querySelectorAll("[data-char-count]").forEach(bindCharCounter);
    initImportMenu(root);
    root.querySelectorAll("[data-tag-picker-root]").forEach(initTagPicker);
  }

  document.querySelectorAll("[data-game-form]").forEach(initGameForm);
})();
