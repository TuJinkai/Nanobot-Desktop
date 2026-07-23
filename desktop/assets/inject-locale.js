// nanobot Desktop — default the WebUI to Simplified Chinese.
// Runs as a Pake/Tauri init script (before the page's own scripts), so the
// locale is in localStorage by the time the WebUI's i18n initializes.
// Only sets it when the user hasn't already chosen a language.
(function () {
  try {
    if (!localStorage.getItem("nanobot.locale")) {
      localStorage.setItem("nanobot.locale", "zh-CN");
    }
  } catch (e) {
    /* ignore storage errors */
  }
})();
