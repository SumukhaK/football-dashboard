/* The theme button in the sidebar footer.
 *
 * The theme itself is chosen before the first paint by the inline script in
 * <head>, so this file only has to keep the button's label, the saved choice
 * and the charts in step with it. */
(function () {
  "use strict";

  var STORAGE_KEY = "theme";
  var BUTTON = "[data-theme-toggle]";

  function current() {
    var theme = document.documentElement.getAttribute("data-theme");
    return theme === "light" ? "light" : "dark";
  }

  function save(theme) {
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch (error) {
      /* A private window can refuse storage; the choice then lasts this page. */
    }
  }

  function next(theme) {
    return theme === "light"
      ? { name: "dark", label: "Switch to dark theme", text: "Dark" }
      : { name: "light", label: "Switch to light theme", text: "Light" };
  }

  function sync(theme) {
    var copy = next(theme);
    Array.prototype.forEach.call(document.querySelectorAll(BUTTON), function (button) {
      button.setAttribute("aria-label", copy.label);
      var text = button.querySelector(".theme-button-text");
      if (text) {
        text.textContent = copy.text;
      }
    });
  }

  function apply(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    save(theme);
    sync(theme);
    document.dispatchEvent(new CustomEvent("themechange", { detail: { theme: theme } }));
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest(BUTTON);
    if (button) {
      apply(current() === "light" ? "dark" : "light");
    }
  });

  sync(current());
})();
