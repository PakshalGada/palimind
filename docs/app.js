/* PaliMind site — highlight the current page in the nav. */
(function () {
  "use strict";

  var page = document.body.getAttribute("data-page") || "home";
  var links = document.querySelectorAll(".nav-links a");
  Array.prototype.forEach.call(links, function (link) {
    var href = link.getAttribute("href").split("/").pop().replace(".html", "");
    if (href === page || (page === "home" && href === "index")) {
      link.classList.add("active");
    }
  });
})();