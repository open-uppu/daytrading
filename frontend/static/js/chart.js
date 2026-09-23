/**
 * PILOTFISH QUANT TERMINAL - TradingView Candlestick Chart Module
 * frontend/static/js/chart.js
 *
 * High-performance dark-themed candlestick and volume chart powered by
 * TradingView Lightweight Charts (v4.x).
 *
 * Exposes window.PilotfishChart:
 *   - initChart(containerId)
 *   - setCandles(bars)
 *   - updateLastCandle(bar)
 *   - renderTradeLines(positions, currentSymbol)
 *   - handleResize()
 *   - clearTradeLines()
 */

(function () {
  'use strict';

  // Module state
  let chart = null;
  let candlestickSeries = null;
  let volumeSeries = null;
  let currentContainer = null;
  let resizeObserver = null;
  let activePriceLines = [];

  // Theme Constants
  const THEME = {
    background: '#0B0F19',
    gridlines: '#1E293B',
    textColor: '#94A3B8',
    crosshairLine: '#64748B',
    upColor: '#10B981',
    downColor: '#EF4444',
    volumeUp: 'rgba(16, 185, 129, 0.45)',
    volumeDown: 'rgba(239, 68, 68, 0.45)',
    tradeEntry: '#06B6D4',
    tradeSL: '#EF4444',
    tradeTP: '#10B981',
  };

  /**
   * Helper to normalize timestamps into UTC Unix seconds.
   * Handles unix seconds, unix milliseconds, and ISO date strings.
   *
   * @param {number|string|Date} rawTime
   * @returns {number} Unix timestamp in seconds
   */
  function parseBarTime(rawTime) {
    if (rawTime == null) {
      return Math.floor(Date.now() / 1000);
    }
    if (typeof rawTime === 'number') {
      return rawTime > 1e11 ? Math.floor(rawTime / 1000) : Math.floor(rawTime);
    }
    if (typeof rawTime === 'string') {
      const trimmed = rawTime.trim();
      const num = Number(trimmed);
      if (!isNaN(num) && /^\d+$/.test(trimmed)) {
        return num > 1e11 ? Math.floor(num / 1000) : Math.floor(num);
      }
      const parsed = Date.parse(trimmed);
      if (!isNaN(parsed)) {
        return Math.floor(parsed / 1000);
      }
    }
    if (rawTime instanceof Date) {
      return Math.floor(rawTime.getTime() / 1000);
    }
    return Math.floor(Date.now() / 1000);
  }

  /**
   * Safe getter for LineStyle enum values across Lightweight Charts versions.
   */
  function getLineStyles() {
    const lw = (typeof window !== 'undefined' && window.LightweightCharts) || {};
    return lw.LineStyle || {
      Solid: 0,
      Dotted: 1,
      Dashed: 2,
      LargeDashed: 3,
      SparseDotted: 4,
    };
  }

  /**
   * Safe getter for CrosshairMode enum values.
   */
  function getCrosshairMode() {
    const lw = (typeof window !== 'undefined' && window.LightweightCharts) || {};
    return (lw.CrosshairMode && lw.CrosshairMode.Normal != null) ? lw.CrosshairMode.Normal : 1;
  }

  /**
   * Initializes the TradingView Lightweight Chart instance in the specified container.
   *
   * @param {string|HTMLElement} containerId - Element ID (default "tv-chart") or HTMLElement
   * @returns {Object|null} The created chart instance or null if unavailable
   */
  function initChart(containerId = 'tv-chart') {
    if (typeof window === 'undefined') {
      console.warn('[PilotfishChart] Window object not available (SSR or non-browser environment).');
      return null;
    }

    if (!window.LightweightCharts) {
      console.error('[PilotfishChart] window.LightweightCharts is not loaded. Ensure script is included in HTML.');
      return null;
    }

    const container = typeof containerId === 'string'
      ? document.getElementById(containerId)
      : containerId;

    if (!container) {
      console.error(`[PilotfishChart] Container element not found: "${containerId}"`);
      return null;
    }

    // Tear down existing chart and observers if previously initialized
    if (chart) {
      clearTradeLines();
      if (resizeObserver) {
        resizeObserver.disconnect();
        resizeObserver = null;
      }
      window.removeEventListener('resize', handleResize);
      try {
        chart.remove();
      } catch (err) {
        console.warn('[PilotfishChart] Error removing prior chart instance:', err);
      }
      chart = null;
      candlestickSeries = null;
      volumeSeries = null;
    }

    currentContainer = container;
    container.innerHTML = '';

    const width = container.clientWidth || 800;
    const height = container.clientHeight || 450;

    const chartOptions = {
      width: width,
      height: height,
      layout: {
        background: { type: 'solid', color: THEME.background },
        textColor: THEME.textColor,
        fontSize: 12,
        fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace',
      },
      grid: {
        vertLines: { color: THEME.gridlines },
        horzLines: { color: THEME.gridlines },
      },
      crosshair: {
        mode: getCrosshairMode(),
        vertLine: {
          color: THEME.crosshairLine,
          width: 1,
          style: getLineStyles().Dashed,
          labelBackgroundColor: THEME.gridlines,
        },
        horzLine: {
          color: THEME.crosshairLine,
          width: 1,
          style: getLineStyles().Dashed,
          labelBackgroundColor: THEME.gridlines,
        },
      },
      rightPriceScale: {
        borderColor: THEME.gridlines,
        scaleMargins: {
          top: 0.1,
          bottom: 0.25,
        },
        autoScale: true,
      },
      timeScale: {
        borderColor: THEME.gridlines,
        timeVisible: true,
        secondsVisible: false,
      },
    };

    try {
      chart = window.LightweightCharts.createChart(container, chartOptions);

      // Create Candlestick series
      candlestickSeries = chart.addCandlestickSeries({
        upColor: THEME.upColor,
        downColor: THEME.downColor,
        borderVisible: false,
        wickUpColor: THEME.upColor,
        wickDownColor: THEME.downColor,
      });

      // Create Volume histogram series (as an overlay scale)
      volumeSeries = chart.addHistogramSeries({
        color: THEME.crosshairLine,
        priceFormat: {
          type: 'volume',
        },
        priceScaleId: '', // Separate overlay scale
      });

      // Position volume histogram strictly at bottom 20% of the chart
      if (volumeSeries && typeof volumeSeries.priceScale === 'function') {
        const priceScale = volumeSeries.priceScale();
        if (priceScale && typeof priceScale.applyOptions === 'function') {
          priceScale.applyOptions({
            scaleMargins: {
              top: 0.8,
              bottom: 0,
            },
          });
        }
      }

      // Attach ResizeObserver for responsive resizing
      if (typeof ResizeObserver !== 'undefined') {
        resizeObserver = new ResizeObserver((entries) => {
          if (!entries || entries.length === 0) return;
          const entry = entries[0];
          const rectWidth = entry.contentRect.width;
          const rectHeight = entry.contentRect.height;
          if (rectWidth > 0 && rectHeight > 0 && chart) {
            chart.applyOptions({ width: rectWidth, height: rectHeight });
          }
        });
        resizeObserver.observe(container);
      }

      // Fallback window resize listener
      window.addEventListener('resize', handleResize);

      console.info('[PilotfishChart] Chart initialized successfully in container:', containerId);
      return chart;
    } catch (err) {
      console.error('[PilotfishChart] Fatal error during initChart:', err);
      return null;
    }
  }

  /**
   * Resizes chart to fit its parent container.
   */
  function handleResize() {
    if (!chart || !currentContainer) return;
    const width = currentContainer.clientWidth;
    const height = currentContainer.clientHeight;
    if (width > 0 && height > 0) {
      chart.applyOptions({ width, height });
    }
  }

  /**
   * Formats and sets historical candle data and volume histogram.
   * Ensures timestamps are sorted strictly ascending and duplicates are removed.
   *
   * @param {Array<Object>} bars - Array of bar objects { time, open, high, low, close, volume }
   */
  function setCandles(bars) {
    if (!candlestickSeries || !volumeSeries) {
      console.warn('[PilotfishChart] Cannot setCandles: series not initialized. Call initChart first.');
      return;
    }

    if (!bars || !Array.isArray(bars) || bars.length === 0) {
      return;
    }

    // Clean, parse, and filter valid bars
    const cleaned = [];
    for (let i = 0; i < bars.length; i++) {
      const b = bars[i];
      if (!b) continue;

      const time = parseBarTime(b.time != null ? b.time : b.timestamp);
      const open = Number(b.open);
      const high = Number(b.high);
      const low = Number(b.low);
      const close = Number(b.close);
      const vol = Number(b.volume != null ? b.volume : (b.tick_volume != null ? b.tick_volume : 0));

      if (isNaN(time) || isNaN(open) || isNaN(high) || isNaN(low) || isNaN(close)) {
        continue;
      }

      cleaned.push({
        time,
        open,
        high,
        low,
        close,
        volume: isNaN(vol) ? 0 : vol,
      });
    }

    if (cleaned.length === 0) return;

    // Sort strictly ascending by timestamp
    cleaned.sort((a, b) => a.time - b.time);

    // Monotonic uniqueness filter: Lightweight Charts requires strictly increasing timestamps
    const uniqueCandles = [];
    const uniqueVolumes = [];
    let lastTime = null;

    for (let i = 0; i < cleaned.length; i++) {
      const bar = cleaned[i];
      const candleItem = {
        time: bar.time,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      };
      const volumeItem = {
        time: bar.time,
        value: bar.volume,
        color: bar.close >= bar.open ? THEME.volumeUp : THEME.volumeDown,
      };

      if (lastTime !== null && bar.time === lastTime) {
        // Overwrite the existing bar with latest bar for the same timestamp
        uniqueCandles[uniqueCandles.length - 1] = candleItem;
        uniqueVolumes[uniqueVolumes.length - 1] = volumeItem;
      } else if (lastTime === null || bar.time > lastTime) {
        uniqueCandles.push(candleItem);
        uniqueVolumes.push(volumeItem);
        lastTime = bar.time;
      }
    }

    try {
      candlestickSeries.setData(uniqueCandles);
      volumeSeries.setData(uniqueVolumes);
      if (chart && typeof chart.timeScale === 'function') {
        chart.timeScale().fitContent();
      }
    } catch (err) {
      console.error('[PilotfishChart] Error applying candle dataset:', err);
    }
  }

  /**
   * Updates the latest forming candle and volume bar with live tick data.
   *
   * @param {Object} bar - Bar or tick object { time, open, high, low, close, volume }
   */
  function updateLastCandle(bar) {
    if (!candlestickSeries || !volumeSeries || !bar) return;

    const time = parseBarTime(bar.time != null ? bar.time : bar.timestamp);
    const close = Number(bar.close != null ? bar.close : bar.price);
    if (isNaN(close)) return;

    const open = Number(bar.open != null ? bar.open : close);
    const high = Number(bar.high != null ? bar.high : Math.max(open, close));
    const low = Number(bar.low != null ? bar.low : Math.min(open, close));
    const vol = Number(bar.volume != null ? bar.volume : (bar.tick_volume != null ? bar.tick_volume : 0));

    const candle = {
      time,
      open: isNaN(open) ? close : open,
      high: isNaN(high) ? close : high,
      low: isNaN(low) ? close : low,
      close,
    };

    const volumeItem = {
      time,
      value: isNaN(vol) ? 0 : vol,
      color: candle.close >= candle.open ? THEME.volumeUp : THEME.volumeDown,
    };

    try {
      candlestickSeries.update(candle);
      volumeSeries.update(volumeItem);
    } catch (err) {
      console.warn('[PilotfishChart] Error updating latest candle:', err);
    }
  }

  /**
   * Removes all active price lines (Entry, SL, TP) from the candlestick series.
   */
  function clearTradeLines() {
    if (candlestickSeries && activePriceLines.length > 0) {
      for (let i = 0; i < activePriceLines.length; i++) {
        try {
          candlestickSeries.removePriceLine(activePriceLines[i]);
        } catch (err) {
          // Ignore if already detached
        }
      }
    }
    activePriceLines = [];
  }

  /**
   * Draws horizontal price overlay lines on the candlestick series for open trades.
   * Removes existing price lines before rendering new ones to prevent line pile-up.
   *
   * @param {Array<Object>} positions - List of open position objects
   * @param {string} [currentSymbol] - Optional current symbol filter (e.g. "XAUUSD")
   */
  function renderTradeLines(positions, currentSymbol) {
    clearTradeLines();

    if (!candlestickSeries || !positions || !Array.isArray(positions) || positions.length === 0) {
      return;
    }

    const LineStyle = getLineStyles();
    const filterSym = currentSymbol ? currentSymbol.toUpperCase() : null;

    for (let i = 0; i < positions.length; i++) {
      const pos = positions[i];
      if (!pos) continue;

      // Filter by symbol if specified
      if (filterSym && pos.symbol && pos.symbol.toUpperCase() !== filterSym) {
        continue;
      }

      const ticket = pos.ticket != null ? pos.ticket : (pos.id != null ? pos.id : '');
      let orderType = 'BUY';
      if (typeof pos.type === 'string') {
        orderType = pos.type.toUpperCase().includes('SELL') ? 'SELL' : 'BUY';
      } else if (pos.type === 1) {
        orderType = 'SELL';
      }

      const openPrice = Number(
        pos.open_price != null
          ? pos.open_price
          : (pos.price_open != null
            ? pos.price_open
            : (pos.price != null
              ? pos.price
              : pos.entry_price))
      );
      const sl = Number(pos.sl != null ? pos.sl : (pos.stop_loss != null ? pos.stop_loss : 0));
      const tp = Number(pos.tp != null ? pos.tp : (pos.take_profit != null ? pos.take_profit : 0));

      // 1. Entry price line: Cyan solid line
      if (!isNaN(openPrice) && openPrice > 0) {
        const entryTitle = ticket ? `${orderType} #${ticket}` : orderType;
        try {
          const entryLine = candlestickSeries.createPriceLine({
            price: openPrice,
            color: THEME.tradeEntry,
            lineWidth: 1,
            lineStyle: LineStyle.Solid,
            axisLabelVisible: true,
            title: entryTitle,
          });
          if (entryLine) activePriceLines.push(entryLine);
        } catch (err) {
          console.warn('[PilotfishChart] Failed to create entry price line:', err);
        }
      }

      // 2. Stop Loss (SL) line: Red dashed line
      if (!isNaN(sl) && sl > 0) {
        try {
          const slLine = candlestickSeries.createPriceLine({
            price: sl,
            color: THEME.tradeSL,
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: 'SL',
          });
          if (slLine) activePriceLines.push(slLine);
        } catch (err) {
          console.warn('[PilotfishChart] Failed to create SL price line:', err);
        }
      }

      // 3. Take Profit (TP) line: Green dashed line
      if (!isNaN(tp) && tp > 0) {
        try {
          const tpLine = candlestickSeries.createPriceLine({
            price: tp,
            color: THEME.tradeTP,
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: 'TP',
          });
          if (tpLine) activePriceLines.push(tpLine);
        } catch (err) {
          console.warn('[PilotfishChart] Failed to create TP price line:', err);
        }
      }
    }
  }

  // Exposed API module
  const PilotfishChart = {
    initChart,
    setCandles,
    updateLastCandle,
    renderTradeLines,
    handleResize,
    clearTradeLines,
    getChart: () => chart,
    getCandlestickSeries: () => candlestickSeries,
    getVolumeSeries: () => volumeSeries,
    getActivePriceLines: () => [...activePriceLines],
    THEME,
  };

  // Export to global window object
  if (typeof window !== 'undefined') {
    window.PilotfishChart = PilotfishChart;
  }

  // Export for CommonJS / Node test runners if available
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = PilotfishChart;
  }
})();
