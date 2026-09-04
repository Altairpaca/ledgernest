/* LedgerNest 前端脚本：主题、图表渲染、快速记账交互 */
(function () {
  "use strict";

  // ---- 主题：localStorage > 系统偏好 ----
  function applyTheme(theme) {
    if (theme === "dark" || (!theme && window.matchMedia("(prefers-color-scheme: dark)").matches)) {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
  }
  var savedTheme = null;
  try { savedTheme = localStorage.getItem("ln-theme"); } catch (e) {}
  applyTheme(savedTheme);
  window.LNTheme = {
    current: function () { return document.documentElement.classList.contains("dark") ? "dark" : "light"; },
    set: function (t) {
      try { localStorage.setItem("ln-theme", t); } catch (e) {}
      applyTheme(t);
    },
    toggle: function () { this.set(this.current() === "dark" ? "light" : "dark"); },
  };

  // ---- ECharts 渲染 ----
  window.LNChart = function (elId, option) {
    var el = document.getElementById(elId);
    if (!el || typeof echarts === "undefined") return;
    var chart = echarts.getInstanceByDom(el) || echarts.init(el, null, { renderer: "canvas" });
    chart.setOption(option, true);
    window.removeEventListener("resize", chart._lnResize);
    chart._lnResize = function () { chart.resize(); };
    window.addEventListener("resize", chart._lnResize);
    return chart;
  };

  // 通用图表配置（从 data-* 属性读取；overrideType 可切换图表类型）
  window.LNChartFromData = function (elId, overrideType) {
    var el = document.getElementById(elId);
    if (!el || typeof echarts === "undefined") return;
    var dataNode = el.dataset.chartScript ? document.getElementById(el.dataset.chartScript) : null;
    var data = JSON.parse(dataNode ? dataNode.textContent : (el.dataset.chart || "{}"));
    var type = overrideType || el.dataset.chartType || "bar";
    var labels = data.labels || [];
    var series = data.series || [];
    // 兼容后端 chart_payload 的 {labels, income, expense, net} 结构
    if (!series.length && (data.income || data.expense || data.net)) {
      series = [
        { name: "收入", data: data.income || [] },
        { name: "支出", data: data.expense || [] },
      ];
    }
    if (!labels.length) { el.innerHTML = ""; return; }
    var option = {
      tooltip: { trigger: "axis" },
      grid: { left: 8, right: 8, top: 32, bottom: 8, containLabel: true },
      legend: series.length > 1 ? { top: 0, type: "scroll" } : undefined,
      xAxis: { type: "category", data: labels, axisLabel: { interval: 0, rotate: labels.length > 6 ? 30 : 0 } },
      yAxis: { type: "value" },
    };
    if (type === "pie") {
      var pieData = (series[0] && series[0].data || []).map(function (v, i) { return { name: labels[i], value: v }; });
      option = {
        tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
        legend: { type: "scroll", bottom: 0 },
        series: [{ type: "pie", radius: ["38%", "68%"], center: ["50%", "45%"], data: pieData, label: { show: false } }],
      };
    } else if (type === "line") {
      option.series = series.map(function (s) {
        return { name: s.name, type: "line", data: s.data, smooth: true, symbolSize: 5, areaStyle: { opacity: 0.08 } };
      });
    } else {
      option.series = series.map(function (s) {
        return { name: s.name, type: "bar", data: s.data, barMaxWidth: 28, borderRadius: [4, 4, 0, 0] };
      });
    }
    return window.LNChart(elId, option);
  };

  window.LNSwitchChart = function (elId, type) {
    window.LNChartFromData(elId, type);
  };

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-chart]").forEach(function (el) {
      window.LNChartFromData(el.id);
    });
  });

  // ---- 金额格式化 ----
  window.LNMoney = function (value, currency) {
    var n = Number(value);
    if (isNaN(n)) return "0.00";
    var s = n.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return currency ? s + " " + currency : s;
  };
})();
