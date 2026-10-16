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

  /* Series colours come from the token variables, so every chart moves with the
   * theme: the status classes, the latency percentiles and the accent. */
  var STATUS_VARS = { "2xx": "--chart-ok", "4xx": "--chart-4xx", "5xx": "--chart-5xx" };
  var LINE_VARS = { p50: "--chart-p50", p95: "--accent" };
  var DONUT_VARS = ["--accent", "--chart-4xx", "--chart-ok", "--chart-p50"];

  function cssVar(name) {
    var value = getComputedStyle(document.documentElement).getPropertyValue(name);
    return (value || "").trim();
  }

  function seriesColor(variables, name) {
    var variable = variables[name];
    return variable ? cssVar(variable) : "";
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
          itemStyle: { color: seriesColor(STATUS_VARS, line.name) },
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
          itemStyle: { color: seriesColor(LINE_VARS, line.name) },
          data: line.values,
        };
      }),
    };
  }

  function donutOption(chart) {
    return {
      tooltip: { trigger: "item" },
      color: DONUT_VARS.map(function (name) {
        return cssVar(name);
      }),
      series: [
        {
          type: "pie",
          radius: ["45%", "72%"],
          label: { show: false },
          itemStyle: {
            borderColor: cssVar("--surface"),
            borderWidth: 2,
          },
          data: chart.slices,
        },
      ],
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
          itemStyle: { color: cssVar("--accent") },
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

  function initAssistantCharts() {
    var data = readJson("assistant-chart-data");
    if (!data) {
      return;
    }
    if (data.answers) {
      render("answers-chart", donutOption(data.answers));
    }
  }

  function init() {
    initOverviewCharts();
    initSparklines();
    initAssistantCharts();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
  document.body.addEventListener("htmx:afterSwap", init);
  /* The token values change with the theme, so every chart is drawn again. */
  document.addEventListener("themechange", init);
})();
