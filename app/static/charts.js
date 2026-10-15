/* Overview charts and the errors sparklines.
 * Reads the JSON blocks the templates render into #overview-chart-data and
 * #errors-sparkline-data and draws the ECharts figures. Re-runs after every
 * HTMX body swap, and each render disposes the previous instance first. */
(function () {
  "use strict";

  var AXIS = {
    type: "category",
    axisLabel: { hideOverlap: true },
  };

  /* Series colours come from the same variables the tiles use, so a 5xx bar is
   * the same red as a failed tile and both follow the light/dark theme. */
  var STATUS_VARS = { "2xx": "--ok-fg", "4xx": "--warn-fg", "5xx": "--bad-fg" };
  var LINE_VARS = { p50: "--primary-color", p95: "--warn-fg" };

  function cssVar(name, fallback) {
    var value = getComputedStyle(document.documentElement).getPropertyValue(name);
    return (value || "").trim() || fallback;
  }

  function seriesColor(variables, name, fallback) {
    var variable = variables[name];
    return variable ? cssVar(variable, fallback) : fallback;
  }

  function render(elementId, option) {
    var element = document.getElementById(elementId);
    if (!element) {
      return;
    }
    var existing = echarts.getInstanceByDom(element);
    if (existing) {
      existing.dispose();
    }
    echarts.init(element).setOption(option);
  }

  function trafficOption(chart) {
    return {
      tooltip: { trigger: "axis" },
      legend: { data: chart.series.map(function (line) { return line.name; }) },
      grid: { left: 40, right: 16, top: 32, bottom: 24 },
      xAxis: Object.assign({ data: chart.labels }, AXIS),
      yAxis: { type: "value" },
      series: chart.series.map(function (line) {
        return {
          name: line.name,
          type: "bar",
          stack: "requests",
          itemStyle: { color: seriesColor(STATUS_VARS, line.name, "#5470c6") },
          data: line.values,
        };
      }),
    };
  }

  function latencyOption(chart) {
    return {
      tooltip: { trigger: "axis" },
      legend: { data: chart.series.map(function (line) { return line.name; }) },
      grid: { left: 48, right: 16, top: 32, bottom: 24 },
      xAxis: Object.assign({ data: chart.labels }, AXIS),
      yAxis: { type: "value", name: "ms" },
      series: chart.series.map(function (line) {
        return {
          name: line.name,
          type: "line",
          showSymbol: false,
          connectNulls: true,
          itemStyle: { color: seriesColor(LINE_VARS, line.name, "#5470c6") },
          data: line.values,
        };
      }),
    };
  }

  function sparklineOption(chart) {
    return {
      tooltip: { trigger: "axis" },
      grid: { left: 0, right: 0, top: 2, bottom: 2 },
      xAxis: { type: "category", data: chart.labels, show: false },
      yAxis: { type: "value", show: false, minInterval: 1 },
      series: [
        {
          type: "line",
          showSymbol: false,
          areaStyle: {},
          itemStyle: { color: cssVar("--primary-color", "#2563eb") },
          data: chart.values,
        },
      ],
    };
  }

  function readJson(elementId) {
    var element = document.getElementById(elementId);
    if (!element) {
      return null;
    }
    try {
      return JSON.parse(element.textContent);
    } catch (error) {
      return null;
    }
  }

  function initOverviewCharts() {
    var data = readJson("overview-chart-data");
    if (!data) {
      return;
    }
    if (data.traffic) {
      render("traffic-chart", trafficOption(data.traffic));
    }
    if (data.latency) {
      render("latency-chart", latencyOption(data.latency));
    }
  }

  function initSparklines() {
    var charts = readJson("errors-sparkline-data");
    if (!charts) {
      return;
    }
    charts.forEach(function (chart) {
      render(chart.id, sparklineOption(chart));
    });
  }

  function init() {
    initOverviewCharts();
    initSparklines();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
  document.body.addEventListener("htmx:afterSwap", init);
})();
