(function () {
    "use strict";

    var configNode = document.getElementById("matches-page-config");
    if (!configNode) {
        return;
    }

    var config = {};
    try {
        config = JSON.parse(configNode.textContent || "{}");
    } catch (_error) {
        return;
    }

    var gameSlug = String(config.gameSlug || "");
    var matchesPageSize = Number(config.pageSize) || 20;
    var workflowStatuses = Array.isArray(config.workflowStatuses)
        ? config.workflowStatuses
        : [];

    function clamp(value, min, max) {
        return Math.min(Math.max(value, min), max);
    }

    function positionFloatingPanel(panel, summary, options) {
        if (!panel || !summary) {
            return;
        }
        var summaryRect = summary.getBoundingClientRect();
        var panelHeight = panel.offsetHeight;
        var panelWidth = panel.offsetWidth;
        var viewportHeight =
            window.innerHeight || document.documentElement.clientHeight || 0;
        var viewportWidth =
            window.innerWidth || document.documentElement.clientWidth || 0;
        var horizontalPadding = 8;
        var verticalPadding = 8;
        var requiredSpace = panelHeight + 8;
        var spaceBelow = viewportHeight - summaryRect.bottom;
        var spaceAbove = summaryRect.top;
        var preferredLeft =
            options && options.align === "end"
                ? summaryRect.right - panelWidth
                : summaryRect.left;
        var left = clamp(
            preferredLeft,
            horizontalPadding,
            Math.max(
                horizontalPadding,
                viewportWidth - panelWidth - horizontalPadding,
            ),
        );
        var top = summaryRect.bottom + verticalPadding;
        if (spaceBelow < requiredSpace && spaceAbove > spaceBelow) {
            top = Math.max(
                verticalPadding,
                summaryRect.top - panelHeight - verticalPadding,
            );
        } else {
            top = Math.min(
                top,
                Math.max(
                    verticalPadding,
                    viewportHeight - panelHeight - verticalPadding,
                ),
            );
        }
        panel.style.left = left + "px";
        panel.style.top = top + "px";
    }

    function bindFloatingDetailsMenu(menu, options) {
        var panel = menu.querySelector(options.panelSelector);
        var summary = menu.querySelector("summary");

        function reposition() {
            if (!menu.open || !panel || !summary) {
                return;
            }
            positionFloatingPanel(panel, summary, options);
        }

        menu.addEventListener("toggle", function () {
            if (menu.open) {
                requestAnimationFrame(reposition);
            }
        });

        return reposition;
    }

    (function initGameTooltips() {
        var tip = document.getElementById("game-tooltip");
        if (!tip) {
            return;
        }
        document.querySelectorAll("[data-tooltip]").forEach(function (el) {
            el.addEventListener("mouseenter", function () {
                tip.textContent = el.getAttribute("data-tooltip");
                tip.style.opacity = "1";
            });
            el.addEventListener("mousemove", function (event) {
                var offset = 12;
                var tipWidth = tip.offsetWidth;
                var tipHeight = tip.offsetHeight;
                var maxLeft = window.innerWidth - tipWidth - 8;
                var desiredLeft = event.clientX + offset;
                var left = Math.min(desiredLeft, Math.max(8, maxLeft));
                var desiredTop = event.clientY - tipHeight - offset;
                var top =
                    desiredTop >= 8
                        ? desiredTop
                        : Math.min(
                              event.clientY + offset,
                              window.innerHeight - tipHeight - 8,
                          );
                tip.style.left = left + "px";
                tip.style.top = top + "px";
            });
            el.addEventListener("mouseleave", function () {
                tip.style.opacity = "0";
            });
        });
    })();

    var filterMenus = Array.from(
        document.querySelectorAll(".matches-filter-menu"),
    );
    var repositioners = filterMenus.map(function (menu) {
        return bindFloatingDetailsMenu(menu, {
            panelSelector: ".matches-filter-panel",
            align: "end",
        });
    });

    var statusTabs = document.querySelectorAll("[data-status-tab]");

    function updateStatusTabs(statusCounts) {
        statusTabs.forEach(function (tab) {
            var status = tab.getAttribute("data-status-tab");
            var countNode = tab.querySelector(".matches-status-tab-count");
            if (!countNode || !statusCounts || statusCounts[status] == null) {
                return;
            }
            var count = Number(statusCounts[status]) || 0;
            countNode.textContent = String(count);
            tab.classList.toggle("is-empty", count === 0);
        });
    }

    function currentWorkflowContext() {
        var params = new URLSearchParams(window.location.search);
        return {
            active_status: params.get("status") || "all",
            min_reach: params.get("min_reach") || "",
            max_reach: params.get("max_reach") || "",
            min_games: params.get("min_games") || "",
            max_games: params.get("max_games") || "",
            reachable_via: params.getAll("reachable_via"),
        };
    }

    function currentMatchesPage() {
        var params = new URLSearchParams(window.location.search);
        var page = Number(params.get("page") || "1");
        if (!Number.isFinite(page) || page < 1) {
            return 1;
        }
        return Math.floor(page);
    }

    function reloadMatchesPage(page) {
        var nextUrl = new URL(window.location.href);
        if (page <= 1) {
            nextUrl.searchParams.delete("page");
        } else {
            nextUrl.searchParams.set("page", String(page));
        }
        window.location.assign(nextUrl.toString());
    }

    function expectedVisibleRows(totalCount, page) {
        var offset = (page - 1) * matchesPageSize;
        var remaining = Math.max(0, totalCount - offset);
        return Math.min(matchesPageSize, remaining);
    }

    function applyWorkflowResponse(row, menu, payload) {
        row.dataset.currentStatus = payload.status;
        workflowStatuses.forEach(function (statusName) {
            row.classList.remove("match-row--" + statusName);
        });
        row.classList.add("match-row--" + payload.status);
        var summary = row.querySelector("[data-match-status-summary]");
        var label = row.querySelector("[data-match-status-label]");
        if (summary) {
            summary.className = "match-status-pill " + payload.status_class;
        }
        if (label) {
            label.textContent = payload.status_label;
        }
        row.querySelectorAll("[data-match-status-option]").forEach(function (
            button,
        ) {
            button.classList.toggle(
                "is-active",
                button.getAttribute("data-status-value") === payload.status,
            );
        });
        var quickSkipButton = row.querySelector("[data-match-quick-status]");
        if (quickSkipButton) {
            quickSkipButton.classList.toggle(
                "is-active",
                payload.status === "not_pursuing",
            );
            if (payload.status === "not_pursuing") {
                quickSkipButton.setAttribute(
                    "data-status-value",
                    "suggested",
                );
                quickSkipButton.setAttribute(
                    "aria-label",
                    "Move back to Suggested",
                );
                quickSkipButton.setAttribute(
                    "title",
                    "Move back to Suggested",
                );
            } else {
                quickSkipButton.setAttribute(
                    "data-status-value",
                    "not_pursuing",
                );
                quickSkipButton.setAttribute(
                    "aria-label",
                    "Move to Not Pursuing",
                );
                quickSkipButton.setAttribute("title", "Not Pursuing");
            }
        }
        var noteInput = row.querySelector("[data-match-note]");
        if (noteInput && noteInput.value !== payload.notes) {
            noteInput.value = payload.notes;
        }
        var noteDot = row.querySelector("[data-match-note-dot]");
        if (noteDot) {
            noteDot.hidden = !payload.has_notes;
        }
        updateStatusTabs(payload.status_counts);
        if (!payload.visible) {
            row.remove();
        }
        var visibleRowCount =
            document.querySelectorAll("[data-match-row]").length;
        var currentPage = currentMatchesPage();
        var currentTotalCount = Number(payload.current_total_count) || 0;
        var lastPage = Math.max(
            1,
            Math.ceil(currentTotalCount / matchesPageSize),
        );
        if (currentPage > lastPage) {
            reloadMatchesPage(lastPage);
            return;
        }
        if (
            visibleRowCount === 0 ||
            visibleRowCount !==
                expectedVisibleRows(currentTotalCount, currentPage)
        ) {
            reloadMatchesPage(currentPage);
            return;
        }
        if (menu) {
            menu.open = false;
        }
    }

    document.querySelectorAll("[data-match-workflow]").forEach(function (menu) {
        var row = menu.closest("[data-match-row]");
        if (!row) {
            return;
        }
        var quickSkipButton = row.querySelector("[data-match-quick-status]");
        var reposition = bindFloatingDetailsMenu(menu, {
            panelSelector: ".match-workflow-panel",
            align: "start",
        });
        repositioners.push(reposition);

        function submitWorkflow(update) {
            var noteInput = row.querySelector("[data-match-note]");
            var payload = Object.assign(
                {
                    status: update.status || row.dataset.currentStatus,
                    notes: noteInput ? noteInput.value : "",
                },
                currentWorkflowContext(),
            );
            fetch(
                "/games/" +
                    encodeURIComponent(gameSlug) +
                    "/matches/" +
                    encodeURIComponent(row.dataset.accountId) +
                    "/workflow",
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        Accept: "application/json",
                    },
                    body: JSON.stringify(payload),
                },
            )
                .then(function (response) {
                    if (!response.ok) {
                        throw new Error("Workflow update failed");
                    }
                    return response.json();
                })
                .then(function (payload) {
                    applyWorkflowResponse(
                        row,
                        update.closeMenu ? menu : null,
                        payload,
                    );
                })
                .catch(function () {
                    window.location.reload();
                });
        }

        menu.querySelectorAll("[data-match-status-option]").forEach(function (
            button,
        ) {
            button.addEventListener("click", function () {
                submitWorkflow({
                    status: button.getAttribute("data-status-value"),
                    closeMenu: true,
                });
            });
        });
        var saveNoteButton = menu.querySelector("[data-match-save-note]");
        if (saveNoteButton) {
            saveNoteButton.addEventListener("click", function () {
                submitWorkflow({
                    closeMenu: false,
                });
            });
        }
        if (quickSkipButton) {
            quickSkipButton.addEventListener("click", function () {
                submitWorkflow({
                    status: quickSkipButton.getAttribute("data-status-value"),
                    closeMenu: true,
                });
            });
        }
    });

    window.addEventListener("resize", function () {
        repositioners.forEach(function (reposition) {
            reposition();
        });
    });
    window.addEventListener(
        "scroll",
        function () {
            repositioners.forEach(function (reposition) {
                reposition();
            });
        },
        true,
    );

    document.addEventListener("click", function (event) {
        document
            .querySelectorAll("[data-match-workflow], .matches-filter-menu")
            .forEach(function (menu) {
                if (!menu.contains(event.target)) {
                    menu.open = false;
                }
            });
    });

    document
        .querySelectorAll(".matches-contact-filter-chips")
        .forEach(function (group) {
            var chips = Array.from(
                group.querySelectorAll(".matches-contact-filter-chip"),
            );

            function renderChipStates() {
                chips.forEach(function (chip) {
                    var input = chip.querySelector('input[type="checkbox"]');
                    if (!input) {
                        return;
                    }
                    chip.classList.toggle("is-active", input.checked);
                });
            }

            chips.forEach(function (chip) {
                var input = chip.querySelector('input[type="checkbox"]');
                if (!input) {
                    return;
                }

                input.addEventListener("change", renderChipStates);
                chip.addEventListener("dblclick", function () {
                    chips.forEach(function (otherChip) {
                        var otherInput = otherChip.querySelector(
                            'input[type="checkbox"]',
                        );
                        if (!otherInput) {
                            return;
                        }
                        otherInput.checked = otherChip === chip;
                    });
                    renderChipStates();
                });
            });

            renderChipStates();
        });

    document.querySelectorAll("[data-range-filter-form]").forEach(function (
        form,
    ) {
        var reachMin = form.querySelector('[data-range-input="min_reach"]');
        var reachMax = form.querySelector('[data-range-input="max_reach"]');
        var gamesMin = form.querySelector('[data-range-input="min_games"]');
        var gamesMax = form.querySelector('[data-range-input="max_games"]');
        var numberMinReach = form.querySelector(
            '[data-range-number="min_reach"]',
        );
        var numberMaxReach = form.querySelector(
            '[data-range-number="max_reach"]',
        );
        var numberMinGames = form.querySelector(
            '[data-range-number="min_games"]',
        );
        var numberMaxGames = form.querySelector(
            '[data-range-number="max_games"]',
        );
        var reachWrapper = form.querySelector('[data-range-wrapper="reach"]');
        var gamesWrapper = form.querySelector('[data-range-wrapper="games"]');
        var reachFloor = Math.max(
            Number(reachWrapper.dataset.rangeFloor) || 1,
            1,
        );
        var reachCeiling = Math.max(
            Number(reachWrapper.dataset.rangeCeiling) || reachFloor,
            reachFloor,
        );
        var reachSliderMax = Number(reachMax.max) || 100;
        var gamesCeiling = Number(gamesMax.max);
        var safeGamesCeiling = Math.max(gamesCeiling, 1);

        function clampInput(input, min, max) {
            var numeric = Number(input.value);
            if (Number.isNaN(numeric)) {
                numeric = min;
            }
            numeric = Math.max(min, Math.min(max, numeric));
            input.value = String(numeric);
        }

        function sanitizeNumericText(input) {
            input.value = input.value.replace(/[^\d]/g, "");
        }

        function sliderToReach(sliderValue) {
            var clampedSlider = Math.max(
                0,
                Math.min(reachSliderMax, Number(sliderValue) || 0),
            );
            if (reachCeiling <= reachFloor) {
                return reachCeiling;
            }
            var ratio = clampedSlider / reachSliderMax;
            var minLog = Math.log10(reachFloor);
            var maxLog = Math.log10(reachCeiling);
            return Math.round(
                Math.pow(10, minLog + ratio * (maxLog - minLog)),
            );
        }

        function reachToSlider(reachValue) {
            var clampedReach = Math.max(
                reachFloor,
                Math.min(reachCeiling, Number(reachValue) || reachFloor),
            );
            if (reachCeiling <= reachFloor) {
                return 0;
            }
            var minLog = Math.log10(reachFloor);
            var maxLog = Math.log10(reachCeiling);
            var reachLog = Math.log10(clampedReach);
            return (
                ((reachLog - minLog) / (maxLog - minLog)) * reachSliderMax
            );
        }

        function commitNumberInput(numberInput, rangeInput, ceiling, kind) {
            sanitizeNumericText(numberInput);
            if (!numberInput.value) {
                if (kind === "reach") {
                    numberInput.value = String(
                        sliderToReach(rangeInput.value),
                    );
                } else {
                    numberInput.value = rangeInput.value;
                }
            }
            clampInput(numberInput, 0, ceiling);
            if (kind === "reach") {
                rangeInput.value = String(reachToSlider(numberInput.value));
            } else {
                rangeInput.value = numberInput.value;
            }
            render();
        }

        function clampPair(
            minInput,
            maxInput,
            ceiling,
            minNumberInput,
            maxNumberInput,
        ) {
            clampInput(minInput, 0, ceiling);
            clampInput(maxInput, 0, ceiling);
            if (Number(minInput.value) > Number(maxInput.value)) {
                if (
                    document.activeElement === minInput ||
                    document.activeElement === minNumberInput
                ) {
                    minInput.value = maxInput.value;
                } else {
                    maxInput.value = minInput.value;
                }
            }
        }

        function render() {
            var minReachValue = sliderToReach(reachMin.value);
            var maxReachValue = sliderToReach(reachMax.value);
            numberMinReach.value = String(minReachValue);
            numberMaxReach.value = String(maxReachValue);
            if (minReachValue > maxReachValue) {
                if (
                    document.activeElement === reachMin ||
                    document.activeElement === numberMinReach
                ) {
                    reachMin.value = reachMax.value;
                    minReachValue = maxReachValue;
                    numberMinReach.value = String(minReachValue);
                } else {
                    reachMax.value = reachMin.value;
                    maxReachValue = minReachValue;
                    numberMaxReach.value = String(maxReachValue);
                }
            }
            clampPair(
                gamesMin,
                gamesMax,
                gamesCeiling,
                numberMinGames,
                numberMaxGames,
            );
            numberMinGames.value = gamesMin.value;
            numberMaxGames.value = gamesMax.value;
            reachWrapper.style.setProperty(
                "--range-start",
                (Number(reachMin.value) / reachSliderMax) * 100 + "%",
            );
            reachWrapper.style.setProperty(
                "--range-end",
                (Number(reachMax.value) / reachSliderMax) * 100 + "%",
            );
            gamesWrapper.style.setProperty(
                "--range-start",
                (Number(gamesMin.value) / safeGamesCeiling) * 100 + "%",
            );
            gamesWrapper.style.setProperty(
                "--range-end",
                (Number(gamesMax.value) / safeGamesCeiling) * 100 + "%",
            );
        }

        [reachMin, reachMax, gamesMin, gamesMax].forEach(function (input) {
            input.addEventListener("input", render);
        });
        [
            [numberMinReach, reachMin, reachCeiling, "reach"],
            [numberMaxReach, reachMax, reachCeiling, "reach"],
            [numberMinGames, gamesMin, gamesCeiling, "games"],
            [numberMaxGames, gamesMax, gamesCeiling, "games"],
        ].forEach(function (pair) {
            var numberInput = pair[0];
            var rangeInput = pair[1];
            var ceiling = pair[2];
            var kind = pair[3];
            numberInput.addEventListener("input", function () {
                sanitizeNumericText(numberInput);
            });
            numberInput.addEventListener("blur", function () {
                commitNumberInput(numberInput, rangeInput, ceiling, kind);
            });
            numberInput.addEventListener("keydown", function (event) {
                if (event.key === "Enter") {
                    event.preventDefault();
                    commitNumberInput(numberInput, rangeInput, ceiling, kind);
                }
            });
        });
        form.addEventListener("submit", function () {
            [
                [numberMinReach, reachMin, reachCeiling, "reach"],
                [numberMaxReach, reachMax, reachCeiling, "reach"],
                [numberMinGames, gamesMin, gamesCeiling, "games"],
                [numberMaxGames, gamesMax, gamesCeiling, "games"],
            ].forEach(function (pair) {
                commitNumberInput(pair[0], pair[1], pair[2], pair[3]);
            });
        });
        reachMin.value = String(reachToSlider(numberMinReach.value));
        reachMax.value = String(reachToSlider(numberMaxReach.value));
        render();
    });
})();
