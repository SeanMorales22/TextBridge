// Message detail page: ask the server every few seconds whether the gateway
// has a newer status, and reload the page when it changes. Stops after the
// message reaches a final state or after about two minutes.
(function () {
  "use strict";

  var form = document.getElementById("refresh-form");
  var note = document.getElementById("auto-refresh-note");
  if (!form) return;

  var token = form.querySelector("input[name=csrfmiddlewaretoken]").value;
  var url = form.getAttribute("action") + "?format=json";
  var intervalMs = 6000;
  var maxChecks = 20;
  var checks = 0;

  function stop(text) {
    if (note) note.textContent = text;
  }

  function check() {
    checks += 1;
    fetch(url, {
      method: "POST",
      headers: { "X-CSRFToken": token },
      credentials: "same-origin",
    })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (data.changed) { window.location.reload(); return; }
        if (data.final) { stop("This message has reached its final status."); return; }
        if (!data.ok && data.message) { stop("Automatic check paused: " + data.message); return; }
        if (checks >= maxChecks) {
          stop("Stopped checking automatically. Use “Refresh delivery status” to check again.");
          return;
        }
        setTimeout(check, intervalMs);
      })
      .catch(function () {
        stop("Automatic check paused. Use “Refresh delivery status” to check again.");
      });
  }

  setTimeout(check, intervalMs);
})();
