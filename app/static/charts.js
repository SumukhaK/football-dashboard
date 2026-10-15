/* Overview charts.
 * Reads the JSON block that the template rendered into #overview-chart-data
 * and draws the two ECharts figures. Re-runs after every HTMX body swap. */
(function () {
  "use strict";

  var AXIS = {
    type: "category",
    axisLabel: { hideOverlap: true },
  };

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
        return { name: line.name, type: "bar", stack: "requests", data: line.values };
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
          data: line.values,
        };
      }),
    };
  }

  function init() {
    var dataElement = document.getElementById("overview-chart-data");
    if (!dataElement) {
      return;
    }
    var data;
    try {
      data = JSON.parse(dataElement.textContent);
    } catch (error) {
      return;
    }
    if (data.traffic) {
      render("traffic-chart", trafficOption(data.traffic));
    }
    if (data.latency) {
      render("latency-chart", latencyOption(data.latency));
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
  document.body.addEventListener("htmx:afterSwap", init);
})();
