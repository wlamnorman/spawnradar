(function () {
  "use strict";

  const form = document.querySelector("[data-reset-password-form]");
  if (!form) {
    return;
  }

  const password = form.querySelector("#new_password");
  const confirm = form.querySelector("#confirm_password");
  const message = form.querySelector("[data-password-mismatch]");
  if (!password || !confirm || !message) {
    return;
  }

  function validate() {
    const mismatch = Boolean(confirm.value) && password.value !== confirm.value;
    message.hidden = !mismatch;
    return !mismatch;
  }

  password.addEventListener("input", validate);
  confirm.addEventListener("input", validate);
  form.addEventListener("submit", (event) => {
    if (!validate()) {
      event.preventDefault();
    }
  });
})();
