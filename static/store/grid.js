// Grilla talle × color de la tienda mayorista: limita al disponible y suma unidades y subtotal al
// instante. Sin framework; el servidor vuelve a validar todo al guardar.
(function () {
  "use strict";
  var money = new Intl.NumberFormat("es-AR", { style: "currency", currency: "ARS", minimumFractionDigits: 2 });

  function setup(form) {
    var inputs = Array.prototype.slice.call(form.querySelectorAll("input.st-qty:not([disabled])"));
    var units = form.querySelector("[data-grid-units]");
    var subtotal = form.querySelector("[data-grid-subtotal]");
    var warning = form.querySelector("[data-grid-warning]");

    function recalc() {
      var u = 0, s = 0;
      inputs.forEach(function (input) {
        var q = parseInt(input.value, 10);
        if (!isNaN(q) && q > 0) {
          u += q;
          s += q * parseFloat(input.dataset.price || "0");
        }
        input.classList.toggle("has-value", !isNaN(q) && q > 0);
      });
      if (units) units.textContent = u === 1 ? "1 unidad" : u + " unidades";
      if (subtotal) subtotal.textContent = money.format(s);
    }

    function clamp(input) {
      var max = parseInt(input.getAttribute("max"), 10);
      var raw = input.value.replace(/[^0-9]/g, "");
      if (raw !== input.value) input.value = raw;
      var q = parseInt(raw, 10);
      if (!isNaN(max) && q > max) {
        input.value = String(max);
        if (warning) warning.textContent = "Solo podés pedir hasta " + max + " de ese talle y color.";
        input.setAttribute("aria-invalid", "true");
      } else {
        if (warning) warning.textContent = "";
        input.removeAttribute("aria-invalid");
      }
    }

    inputs.forEach(function (input) {
      input.addEventListener("input", function () { clamp(input); recalc(); });
      input.addEventListener("focus", function () { input.select(); });
    });
    recalc();
  }

  document.querySelectorAll("form[data-grid-form]").forEach(setup);
})();
