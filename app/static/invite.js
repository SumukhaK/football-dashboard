/* The invite code is shown once; copying it needs no inline handler. */
document.addEventListener("click", function (event) {
  "use strict";

  var button = event.target.closest(".js-copy-invite");
  if (!button) {
    return;
  }
  navigator.clipboard.writeText(button.dataset.code);
});
