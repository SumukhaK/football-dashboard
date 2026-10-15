/* Request detail helpers.
 * The only scripted behaviour is the "Copy request ID" button: it copies the
 * button's data-copy value so the ID can be pasted into a trace or log query. */
(function () {
  "use strict";

  function copy(button) {
    var value = button.getAttribute("data-copy");
    if (value && navigator.clipboard) {
      navigator.clipboard.writeText(value);
    }
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-copy]");
    if (button) {
      copy(button);
    }
  });
})();
