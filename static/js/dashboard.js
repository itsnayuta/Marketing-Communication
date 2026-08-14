(() => {
  const destroyCharts = () => {
    (window.bakaDashboardCharts || []).forEach((chart) => chart.destroy());
    window.bakaDashboardCharts = [];
  };

  window.renderBakaDashboard = () => {
    const element = document.getElementById("chart-data");
    if (!element || typeof Chart === "undefined") {
      destroyCharts();
      return;
    }

    destroyCharts();
    const data = JSON.parse(element.textContent);
    const brand = "#6c5ce7";
    const green = "#10b981";
    const grid = "rgba(148, 163, 184, .16)";
    Chart.defaults.font.family = 'Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif';
    Chart.defaults.color = "#64748b";

    const line = (id, labels, values, label, color) => {
      const canvas = document.getElementById(id);
      if (!canvas) return null;
      return new Chart(canvas, {
        type: "line",
        data: { labels, datasets: [{ label, data: values, borderColor: color, backgroundColor: `${color}18`, fill: true, tension: .35, pointRadius: 2 }] },
        options: { responsive: true, maintainAspectRatio: false, animation: { duration: 220 }, plugins: { legend: { display: false } }, scales: { x: { grid: { display: false } }, y: { beginAtZero: true, grid: { color: grid } } } }
      });
    };
    const bars = (id, labels, values, color) => {
      const canvas = document.getElementById(id);
      if (!canvas) return null;
      return new Chart(canvas, {
        type: "bar",
        data: { labels, datasets: [{ data: values, backgroundColor: color, borderRadius: 6 }] },
        options: { responsive: true, maintainAspectRatio: false, animation: { duration: 220 }, plugins: { legend: { display: false } }, scales: { x: { grid: { display: false } }, y: { beginAtZero: true, grid: { color: grid } } } }
      });
    };

    window.bakaDashboardCharts = [
      line("revenueDay", data.days, data.dailyRevenue, "Doanh thu thuần", brand),
      line("quantityDay", data.days, data.dailyQuantity, "Số lượng", green),
      bars("revenuePlatform", data.platforms, data.platformRevenue, brand),
      bars("profitPlatform", data.platforms, data.platformProfit, green),
    ].filter(Boolean);
  };

  document.addEventListener("DOMContentLoaded", window.renderBakaDashboard);
  document.addEventListener("htmx:afterSettle", window.renderBakaDashboard);
})();

