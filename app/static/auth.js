/* Signing out must not leave a private HTMX snapshot in this browser. */
(function () {
  "use strict";

  try {
    localStorage.removeItem("htmx-history-cache");
  } catch (error) {
    /* Storage can be disabled; there is nothing else to clear. */
  }

  window.addEventListener("pageshow", function (event) {
    if (event.persisted) {
      window.location.reload();
    }
  });
})();
