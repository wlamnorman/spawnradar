(function () {
  "use strict";

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

  function initGameForm(root) {
    root.querySelectorAll("[data-char-count]").forEach(bindCharCounter);
  }

  document.querySelectorAll("[data-game-form]").forEach(initGameForm);
})();
