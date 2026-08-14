(() => {
  const navKeyForPath = (path) => {
    if (path === "/") return "dashboard";
    if (path.startsWith("/orders/")) return "orders";
    if (path === "/imports/history/" || /^\/imports\/\d+\/$/.test(path)) return "history";
    if (path.startsWith("/imports/")) return "import";
    if (path.startsWith("/products/aliases/")) return "aliases";
    if (path.startsWith("/products/")) return "products";
    if (path.startsWith("/mappings/")) return "mappings";
    if (path.startsWith("/quality/")) return "quality";
    if (path.startsWith("/ai/")) return "ai";
    if (path.startsWith("/settings/")) return "settings";
    return "";
  };

  const syncNavigation = () => {
    const activeKey = navKeyForPath(window.location.pathname);
    document.querySelectorAll(".sidebar-nav .nav-link").forEach((link) => {
      link.classList.toggle("active", link.dataset.nav === activeKey);
    });
    document.body.classList.remove("sidebar-open", "is-navigating");
    const content = document.getElementById("content");
    if (content) content.setAttribute("aria-busy", "false");
    const title = content?.querySelector("h1")?.textContent?.trim();
    if (title) document.title = `${title} · BAKA`;
    const sidebarMenu = document.getElementById("sidebar-menu");
    if (window.innerWidth < 992 && sidebarMenu?.classList.contains("show")) {
      document.querySelector('[data-bs-target="#sidebar-menu"]')?.click();
    }
  };

  document.addEventListener("htmx:beforeRequest", (event) => {
    if (!event.detail.target || event.detail.target.id !== "content") return;
    document.body.classList.add("is-navigating");
    event.detail.target.setAttribute("aria-busy", "true");
  });
  document.addEventListener("htmx:beforeSwap", (event) => {
    const responseUrl = event.detail.xhr?.responseURL || "";
    if (!responseUrl.includes("/login/")) return;
    event.detail.shouldSwap = false;
    window.location.assign(responseUrl);
  });
  document.addEventListener("htmx:afterSettle", syncNavigation);
  ["htmx:responseError", "htmx:sendError", "htmx:timeout"].forEach((eventName) => {
    document.addEventListener(eventName, syncNavigation);
  });
  window.addEventListener("popstate", syncNavigation);
  document.addEventListener("DOMContentLoaded", syncNavigation);
})();
