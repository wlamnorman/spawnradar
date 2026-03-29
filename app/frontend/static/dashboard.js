(function () {
  "use strict";

  function capTagRows(container, maxRows) {
    const pills = Array.from(container.querySelectorAll(".tag-pill"));
    if (!pills.length) return;

    const rowTops = [];
    pills.forEach((pill) => {
      if (!rowTops.includes(pill.offsetTop)) {
        rowTops.push(pill.offsetTop);
      }
    });

    if (rowTops.length <= maxRows) return;

    const cutoffTop = rowTops[maxRows];
    const toHide = pills.filter((pill) => pill.offsetTop >= cutoffTop);
    const lastVisible = pills.filter((pill) => pill.offsetTop < cutoffTop);

    toHide.forEach((pill) => {
      pill.style.display = "none";
    });
    let hiddenCount = toHide.length;

    const morePill = document.createElement("span");
    morePill.className = "tag-pill tag-more";
    morePill.textContent = `+${hiddenCount} more`;
    container.appendChild(morePill);

    const targetTop = rowTops[maxRows - 1];
    while (morePill.offsetTop > targetTop && lastVisible.length > 0) {
      lastVisible.pop().style.display = "none";
      morePill.textContent = `+${++hiddenCount} more`;
    }
  }

  document.querySelectorAll(".tag-row").forEach((row) => capTagRows(row, 6));

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest(".card-menu-trigger");
    if (trigger) {
      const menu = trigger.closest(".card-menu");
      const dropdown = menu ? menu.querySelector(".card-menu-dropdown") : null;
      const isOpen = dropdown && !dropdown.classList.contains("hidden");
      document
        .querySelectorAll(".card-menu-dropdown")
        .forEach((node) => node.classList.add("hidden"));
      if (dropdown && !isOpen) {
        dropdown.classList.remove("hidden");
      }
      return;
    }

    if (!event.target.closest(".card-menu")) {
      document
        .querySelectorAll(".card-menu-dropdown")
        .forEach((node) => node.classList.add("hidden"));
    }
  });
})();
