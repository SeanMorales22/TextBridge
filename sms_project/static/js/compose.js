// Compose page: character counter, SMS segment calculator, live preview,
// contact picker and double-submit protection.
(function () {
  "use strict";

  var form = document.getElementById("sms-form");
  if (!form) return;

  var message = document.getElementById("id_message");
  var recipient = document.getElementById("id_recipient");
  var contact = document.getElementById("id_contact");
  var charCount = document.getElementById("char-count");
  var segmentCount = document.getElementById("segment-count");
  var encoding = document.getElementById("encoding");
  var encodingHelp = document.getElementById("encoding-help");
  var counter = document.getElementById("counter");
  var previewBubble = document.getElementById("preview-bubble");
  var previewTo = document.getElementById("preview-to");
  var sendBtn = document.getElementById("send-btn");
  var maxLength = parseInt(message.getAttribute("maxlength"), 10) || 1600;

  // GSM 03.38 basic character set (1 unit each) and extension set (2 units each).
  var GSM_BASIC =
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?" +
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà";
  var GSM_EXTENDED = "^{}\\[~]|€\f";

  function analyse(text) {
    var gsmUnits = 0;
    var isGsm = true;
    for (var i = 0; i < text.length; i++) {
      var ch = text.charAt(i);
      if (GSM_BASIC.indexOf(ch) !== -1) gsmUnits += 1;
      else if (GSM_EXTENDED.indexOf(ch) !== -1) gsmUnits += 2;
      else { isGsm = false; break; }
    }
    var units, single, multi;
    if (isGsm) { units = gsmUnits; single = 160; multi = 153; }
    else { units = text.length; single = 70; multi = 67; } // UTF-16 code units
    var segments = units === 0 ? 0 : units <= single ? 1 : Math.ceil(units / multi);
    return { isGsm: isGsm, units: units, segments: segments, perSegment: segments > 1 ? multi : single };
  }

  function updateCounter() {
    var text = message.value;
    var info = analyse(text);
    charCount.textContent = text.length;
    segmentCount.textContent = info.segments;
    encoding.textContent = info.isGsm ? "GSM-7" : "Unicode";
    encoding.classList.toggle("unicode", !info.isGsm);
    encodingHelp.textContent = info.isGsm
      ? "Plain-text messages fit " + info.perSegment + " characters per SMS segment."
      : "Emoji or special characters detected: each SMS segment now holds only " + info.perSegment + " characters.";
    counter.classList.toggle("over", text.length > maxLength);

    if (text.trim()) {
      previewBubble.textContent = text;
    } else {
      previewBubble.innerHTML = '<span class="muted">Your message will appear here.</span>';
    }
  }

  function updateRecipientPreview() {
    var label = recipient.value.trim();
    if (contact && contact.value) {
      var name = contact.options[contact.selectedIndex].text.replace(/\s*\(.*\)$/, "");
      label = label ? name + " · " + label : name;
    }
    previewTo.textContent = label || "Recipient";
  }

  if (contact) {
    contact.addEventListener("change", function () {
      var match = contact.options[contact.selectedIndex].text.match(/\(([^)]+)\)$/);
      recipient.value = match ? match[1] : "";
      updateRecipientPreview();
    });
  }

  message.addEventListener("input", updateCounter);
  recipient.addEventListener("input", function () {
    if (contact && contact.value) contact.value = ""; // typing a number overrides the contact
    updateRecipientPreview();
  });

  form.addEventListener("reset", function () {
    setTimeout(function () { updateCounter(); updateRecipientPreview(); }, 0);
  });

  form.addEventListener("submit", function (event) {
    // Quick client-side check; the server always validates again.
    if (!recipient.value.trim() && !(contact && contact.value)) {
      // let the server render its proper validation message
      return;
    }
    if (sendBtn.disabled) { event.preventDefault(); return; }
    sendBtn.disabled = true;
    sendBtn.textContent = "Sending…";
  });

  updateCounter();
  updateRecipientPreview();
})();
