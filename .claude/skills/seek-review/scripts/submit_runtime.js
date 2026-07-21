/* SEEK_REVIEW_SUBMIT_RUNTIME
 * Canonical Submit review handler injected by serve_review.py.
 * Wins over agent-generated onclick handlers (capture phase) so truncated
 * or port-stale HTML still POSTs feedback successfully.
 */
(function () {
  if (window.__SEEK_REVIEW_SUBMIT_RUNTIME__) return;
  window.__SEEK_REVIEW_SUBMIT_RUNTIME__ = true;

  function cfg() {
    if (typeof CFG !== "undefined" && CFG) return CFG;
    var el = document.getElementById("seek-review-config");
    if (!el) return {};
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      return {};
    }
  }

  function resolveSubmitUrl() {
    if (location.protocol === "http:" || location.protocol === "https:") {
      return location.origin + "/submit";
    }
    var c = cfg();
    return c.submitUrl || "";
  }

  function syncSubmitUrl() {
    var u = resolveSubmitUrl();
    if (!u) return u;
    if (typeof CFG !== "undefined" && CFG) CFG.submitUrl = u;
    var el = document.getElementById("seek-review-config");
    if (el) {
      try {
        var j = JSON.parse(el.textContent);
        j.submitUrl = u;
        el.textContent = JSON.stringify(j);
      } catch (e) {}
    }
    return u;
  }

  function hostMeta(anchor) {
    var host = document.querySelector('[data-anchor="' + anchor + '"]');
    return {
      section: (host && host.dataset.section) || "",
      quote: (host && host.dataset.quote) || "",
    };
  }

  function collectItems() {
    var items = [];
    var byAnchor =
      typeof commentsByAnchor !== "undefined" && commentsByAnchor
        ? commentsByAnchor
        : {};
    Object.keys(byAnchor).forEach(function (k) {
      var c = byAnchor[k];
      if (!c || !String(c.text || "").trim()) return;
      items.push({
        kind: "comment",
        anchor: c.anchor || k,
        section: c.section || "",
        original_quote: c.original_quote || "",
        feedback: c.text,
      });
    });

    var radioNames = {};
    document.querySelectorAll('input[type="radio"][name]').forEach(function (el) {
      if (el.name === "verdict") return;
      radioNames[el.name] = true;
    });
    Object.keys(radioNames).forEach(function (name) {
      var el = document.querySelector(
        'input[type="radio"][name="' + name + '"]:checked'
      );
      if (!el) return;
      var host =
        el.closest("[data-anchor]") ||
        document.querySelector('[data-anchor="' + name + '"]');
      var anchor = (host && host.dataset.anchor) || name;
      var meta = hostMeta(anchor);
      var labelEl = el.closest("label") || el.parentElement;
      var choiceLabel = "";
      if (labelEl) {
        var lab = labelEl.querySelector(".label");
        choiceLabel = lab
          ? lab.innerText.trim()
          : labelEl.innerText.trim();
      }
      items.push({
        kind: "decision",
        anchor: anchor,
        section: meta.section || (host && host.dataset.section) || "",
        original_quote: meta.quote || (host && host.dataset.quote) || "",
        question: name,
        choice: el.value,
        choice_label: choiceLabel || el.value,
      });
    });

    var checkNames = {};
    document
      .querySelectorAll('input[type="checkbox"][name]')
      .forEach(function (el) {
        checkNames[el.name] = true;
      });
    Object.keys(checkNames).forEach(function (name) {
      var checked = Array.prototype.map.call(
        document.querySelectorAll(
          'input[type="checkbox"][name="' + name + '"]:checked'
        ),
        function (el) {
          return el.value;
        }
      );
      var host =
        document.querySelector('[data-anchor="' + name + '"]') ||
        (document.querySelector(
          'input[type="checkbox"][name="' + name + '"]'
        ) &&
          document
            .querySelector('input[type="checkbox"][name="' + name + '"]')
            .closest("[data-anchor]"));
      var anchor = (host && host.dataset.anchor) || name;
      var meta = hostMeta(anchor);
      items.push({
        kind: "multiselect",
        anchor: anchor,
        section: meta.section || "",
        original_quote: meta.quote || "",
        field: name,
        choices: checked,
      });
    });

    document.querySelectorAll("textarea[name]").forEach(function (el) {
      var val = (el.value || "").trim();
      if (!val) return;
      var host = el.closest("[data-anchor]") || el;
      var anchor = host.dataset.anchor || el.name;
      var meta = hostMeta(anchor);
      items.push({
        kind: "freeform",
        anchor: anchor,
        section: meta.section || host.dataset.section || "",
        original_quote: meta.quote || el.dataset.quote || host.dataset.quote || "",
        field: el.name,
        feedback: val,
      });
    });

    return items;
  }

  function showStatus(ok, message) {
    var confirm = document.getElementById("confirmMsg");
    if (confirm) {
      confirm.style.display = "block";
      confirm.style.background = ok
        ? "var(--teal-soft, #e6f7ef)"
        : "var(--warn-soft, #fff4e5)";
      confirm.style.color = ok
        ? "var(--risk-low, #0a7a45)"
        : "var(--warn, #9a6700)";
      confirm.textContent = message;
      return;
    }
    try {
      window.alert(message);
    } catch (e) {}
  }

  async function onSubmit(ev) {
    if (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      if (typeof ev.stopImmediatePropagation === "function") {
        ev.stopImmediatePropagation();
      }
    }
    var c = cfg();
    var verdictEl = document.querySelector('input[name="verdict"]:checked');
    var payload = {
      source: c.source || "",
      review_html: c.reviewHtml || "",
      feedback_file: c.feedbackFileBase || "",
      feedback_base: c.feedbackFileBase || "",
      exported_at: new Date().toISOString(),
      reviewer: (document.querySelector('[name="reviewer"]') || {}).value || "",
      verdict: verdictEl ? verdictEl.value : null,
      items: collectItems(),
    };

    var pre = document.getElementById("jsonText");
    var preview = document.getElementById("jsonPreview");
    if (pre) pre.textContent = JSON.stringify(payload, null, 2);
    if (preview) preview.classList.add("show");

    var url = syncSubmitUrl();
    if (!url) {
      showStatus(false, "No submit URL (open via serve_review.py, not file://).");
      return;
    }

    var btn = document.getElementById("submitBtn");
    if (btn) {
      btn.disabled = true;
      btn.dataset._srLabel = btn.textContent;
      btn.textContent = "Submitting…";
    }
    try {
      var res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error("HTTP " + res.status);
      var data = await res.json();
      showStatus(
        true,
        "Submitted. Feedback file: " + (data.feedback_file || "")
      );
      var gate =
        document.getElementById("gate") ||
        document.getElementById("submit-zone") ||
        document.getElementById("confirmMsg");
      if (gate && gate.scrollIntoView) {
        gate.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    } catch (err) {
      console.error("seek-review submit failed", err);
      showStatus(
        false,
        "POST failed (" +
          ((err && err.message) || err) +
          "). JSON shown above — Copy/Download if needed."
      );
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = btn.dataset._srLabel || "Submit review";
      }
    }
  }

  function wire() {
    syncSubmitUrl();
    var btn = document.getElementById("submitBtn");
    if (!btn) {
      console.warn("seek-review: #submitBtn not found");
      return;
    }
    // Capture phase + stopImmediatePropagation beats broken agent onclick.
    btn.addEventListener("click", onSubmit, true);
    btn.setAttribute("data-seek-review-submit", "runtime");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }
})();
