document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".admin-game-toggle").forEach((toggle) => {
    toggle.addEventListener("click", () => {
      const detail = toggle.nextElementSibling;
      const isOpen = detail.style.display !== "none";
      detail.style.display = isOpen ? "none" : "block";
      toggle.textContent = toggle.textContent.replace(
        isOpen ? "\u25BE" : "\u25B8",
        isOpen ? "\u25B8" : "\u25BE"
      );
    });
  });
});
