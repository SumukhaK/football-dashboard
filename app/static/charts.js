/* Overview charts, the errors sparklines and the access charts.
 * Reads the JSON blocks the templates render into #overview-chart-data,
 * #errors-sparkline-data and #access-chart-data and draws the ECharts figures.
 * Re-runs after every HTMX body swap and on every theme change; each render
 * disposes the previous instance, and a swap also disposes the instances whose
 * elements the new body replaced, so no instance outlives its canvas. */
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

  function cssVar(name) {
    var value = getComputedStyle(document.documentElement).getPropertyValue(name);
    return (value || "").trim();
  }

  function seriesColor(variables, name) {
    var variable = variables[name];
    return variable ? cssVar(variable) : "";
  }

  /* The elements we have drawn into, so a swap that replaces the body can let
   * go of the instances whose canvases have just left the document. */
  var drawn = [];

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
    if (drawn.indexOf(element) === -1) {
      drawn.push(element);
    }
  }

  function disposeDetached() {
    drawn = drawn.filter(function (element) {
      if (document.contains(element)) {
        return true;
      }
      var instance = echarts.getInstanceByDom(element);
      if (instance) {
        instance.dispose();
      }
      return false;
    });
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

  function countOption(chart) {
    return {
      tooltip: { trigger: "axis" },
      grid: { left: 40, right: 16, top: 16, bottom: 24 },
      xAxis: Object.assign({ data: chart.labels }, AXIS),
      yAxis: { type: "value", minInterval: 1 },
      series: [
        {
          type: "bar",
          itemStyle: { color: cssVar("--accent") },
          data: chart.series.length ? chart.series[0].values : [],
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
    if (data.sparklines) {
      data.sparklines.forEach(function (chart) {
        render(chart.id, sparklineOption(chart));
      });
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

  function initAccessCharts() {
    var data = readJson("access-chart-data");
    if (!data) {
      return;
    }
    if (data.failed_sign_ins) {
      render("failed-signins-chart", countOption(data.failed_sign_ins));
    }
    if (data.rate_limit) {
      render("rate-limit-chart", countOption(data.rate_limit));
    }
  }

  function init() {
    disposeDetached();
    initOverviewCharts();
    initSparklines();
    initAccessCharts();
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
