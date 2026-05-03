(function () {
  "use strict";

  const launchCard = document.querySelector(".billing-launch-card");
  const checkoutButton = document.getElementById("paddle-checkout-button");
  if (!(launchCard instanceof HTMLElement)) {
    return;
  }

  const paddleEnvironment = launchCard.dataset.paddleEnvironment || "";
  const paddleToken = launchCard.dataset.paddleToken || "";
  const priceId = launchCard.dataset.priceId || "";
  const successUrl = launchCard.dataset.successUrl || "";
  const customerEmail = launchCard.dataset.customerEmail || "";

  let customData = {};
  try {
    customData = JSON.parse(launchCard.dataset.customData || "{}");
  } catch (_) {
    customData = {};
  }

  function openCheckout() {
    if (!window.Paddle) {
      return;
    }

    window.Paddle.Checkout.open({
      settings: {
        displayMode: "overlay",
        variant: "one-page",
        theme: "light",
        successUrl,
      },
      items: [{ priceId, quantity: 1 }],
      customer: customerEmail ? { email: customerEmail } : undefined,
      customData,
    });
  }

  if (window.Paddle && paddleEnvironment === "sandbox") {
    window.Paddle.Environment.set("sandbox");
  }
  if (window.Paddle) {
    window.Paddle.Initialize({ token: paddleToken });
  }

  checkoutButton?.addEventListener("click", openCheckout);
  window.setTimeout(openCheckout, 50);
})();
