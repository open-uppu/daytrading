/**
 * PILOTFISH QUANT TERMINAL - Reactive Dashboard WebSocket Client & DOM Updater
 * frontend/static/js/dashboard.js
 *
 * Orchestrates real-time state, WebSocket streaming, TradingView Lightweight Chart
 * integration, KPI metrics with flash animations, target progress tracking,
 * active positions table, closed orders feed, and specialist squad monitor cards.
 */

(function () {
  'use strict';

  // Configuration constants
  const CONFIG = {
    wsPath: '/ws/live',
    reconnectBaseDelayMs: 1000,
    reconnectMaxDelayMs: 5000,
    reconnectBackoffMultiplier: 1.5,
    pingIntervalMs: 15000,
    defaultSymbol: 'XAUUSD',
    defaultTimeframe: 'M5',
  };

  // Reactive state store
  const state = {
    currentSymbol: CONFIG.defaultSymbol,
    currentTimeframe: CONFIG.defaultTimeframe,
    ws: null,
    reconnectAttempts: 0,
    reconnectTimeoutId: null,
    pingIntervalId: null,
    clockIntervalId: null,
    lastPingSentTime: null,
    account: null,
    portfolio: null,
    openPositions: [],
    closedOrders: [],
    specialists: null,
    lastMetrics: {
      balance: null,
      equity: null,
      floatingPnl: null,
      todayPnl: null,
    },
  };

  /**
   * Safe getter for DOM element by ID.
   * @param {string} id
   * @returns {HTMLElement|null}
   */
  function getEl(id) {
    if (typeof document === 'undefined') return null;
    return document.getElementById(id);
  }

  /**
   * Escape special HTML characters to prevent XSS.
   * @param {any} str
   * @returns {string}
   */
  function escapeHtml(str) {
    if (str == null) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  /**
   * Format numbers as USD currency ($10,000.00).
   * @param {number|string} val
   * @returns {string}
   */
  function formatCurrency(val) {
    if (val == null || isNaN(Number(val))) return '$0.00';
    const num = Number(val);
    return '$' + num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  /**
   * Format numbers as signed USD currency (+$150.00, -$50.00, $0.00).
   * @param {number|string} val
   * @returns {string}
   */
  function formatSignedCurrency(val) {
    if (val == null || isNaN(Number(val))) return '$0.00';
    const num = Number(val);
    if (Math.abs(num) < 0.0001) return '$0.00';
    const sign = num > 0 ? '+' : '-';
    const absFormatted = Math.abs(num).toLocaleString('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
    return `${sign}$${absFormatted}`;
  }

  /**
   * Triggers green or red flash animations on numeric DOM elements when their value changes.
   * Uses CSS classes .flash-green and .flash-red defined in terminal.css.
   *
   * @param {HTMLElement|null} element
   * @param {number|null} prevVal
   * @param {number|null} newVal
   */
  function flashMetric(element, prevVal, newVal) {
    if (!element || prevVal === null || newVal === null || prevVal === undefined || newVal === undefined) return;
    const diff = Number(newVal) - Number(prevVal);
    if (Math.abs(diff) < 0.001) return;

    const flashClass = diff > 0 ? 'flash-green' : 'flash-red';
    element.classList.remove('flash-green', 'flash-red');
    // Force DOM reflow to ensure animation restarts cleanly
    void element.offsetWidth;
    element.classList.add(flashClass);

    setTimeout(() => {
      if (element) {
        element.classList.remove('flash-green', 'flash-red');
      }
    }, 850);
  }

  /**
   * Updates Account KPI cards (Balance, Equity, Floating PnL, Today's Realized PnL).
   *
   * @param {Object} account
   * @param {Object} portfolio
   */
  function updateKpiCards(account, portfolio) {
    if (!account) return;

    const balanceEl = getEl('metric-balance');
    const equityEl = getEl('metric-equity');
    const floatingEl = getEl('metric-floating-pnl');
    const todayPnlEl = getEl('metric-today-pnl');

    const newBalance = Number(account.balance != null ? account.balance : 0);
    const newEquity = Number(account.equity != null ? account.equity : newBalance);
    const newFloating = Number(account.floating_pnl != null ? account.floating_pnl : (newEquity - newBalance));

    let newTodayPnl = 0;
    let dailyPct = 0;
    if (portfolio) {
      newTodayPnl = Number(portfolio.realized_pnl_usd != null ? portfolio.realized_pnl_usd : 0);
      dailyPct = Number(portfolio.daily_return_pct != null ? portfolio.daily_return_pct : 0);
    } else if (account.balance != null && portfolio?.starting_balance) {
      newTodayPnl = newBalance - Number(portfolio.starting_balance);
    }

    // Trigger flash animations on change
    if (state.lastMetrics.balance !== null) {
      flashMetric(balanceEl, state.lastMetrics.balance, newBalance);
    }
    if (state.lastMetrics.equity !== null) {
      flashMetric(equityEl, state.lastMetrics.equity, newEquity);
    }
    if (state.lastMetrics.floatingPnl !== null) {
      flashMetric(floatingEl, state.lastMetrics.floatingPnl, newFloating);
    }
    if (state.lastMetrics.todayPnl !== null) {
      flashMetric(todayPnlEl, state.lastMetrics.todayPnl, newTodayPnl);
    }

    // Cache updated metrics
    state.lastMetrics.balance = newBalance;
    state.lastMetrics.equity = newEquity;
    state.lastMetrics.floatingPnl = newFloating;
    state.lastMetrics.todayPnl = newTodayPnl;

    // Render formatted values
    if (balanceEl) {
      balanceEl.textContent = formatCurrency(newBalance);
    }
    if (equityEl) {
      equityEl.textContent = formatCurrency(newEquity);
    }
    if (floatingEl) {
      floatingEl.textContent = formatSignedCurrency(newFloating);
      floatingEl.className = `text-xl md:text-2xl font-bold font-mono ${
        newFloating > 0 ? 'text-emerald-400' : newFloating < 0 ? 'text-rose-400' : 'text-slate-100'
      }`;
    }
    if (todayPnlEl) {
      todayPnlEl.textContent = formatSignedCurrency(newTodayPnl);
      todayPnlEl.className = `text-xl md:text-2xl font-bold font-mono ${
        newTodayPnl > 0 ? 'text-emerald-400' : newTodayPnl < 0 ? 'text-rose-400' : 'text-slate-100'
      }`;
    }

    // Update subtitles
    if (portfolio && portfolio.starting_balance != null) {
      const startBalEl = balanceEl?.parentElement?.querySelector('.text-slate-500');
      if (startBalEl) {
        startBalEl.textContent = `Starting: ${formatCurrency(portfolio.starting_balance)}`;
      }
    }

    const floatingSubEl = floatingEl?.parentElement?.querySelector('.text-slate-500');
    if (floatingSubEl) {
      const baseBal = (portfolio?.starting_balance || newBalance || 10000);
      const floatPct = (newFloating / baseBal) * 100;
      floatingSubEl.textContent = `Unrealized: ${floatPct >= 0 ? '+' : ''}${floatPct.toFixed(2)}%`;
    }

    const todaySubEl = todayPnlEl?.parentElement?.querySelector('.text-slate-500');
    if (todaySubEl) {
      todaySubEl.textContent = `${dailyPct >= 0 ? '+' : ''}${dailyPct.toFixed(2)}% return`;
    }

    // Update system mode badge
    if (account.mode) {
      const modeBadge = getEl('mode-badge');
      if (modeBadge) {
        modeBadge.textContent = account.mode;
        if (account.mode.toUpperCase().includes('MT5')) {
          modeBadge.className = 'px-2 py-0.5 rounded text-xs font-mono uppercase bg-emerald-950/80 text-emerald-400 border border-emerald-500/30';
        } else {
          modeBadge.className = 'px-2 py-0.5 rounded text-xs font-mono uppercase bg-blue-950/80 text-blue-400 border border-blue-500/30';
        }
      }
    }
  }

  /**
   * Updates Daily Target progress bar, fill width, and marker labels.
   * Track markers:
   *   -3% (Max Loss)   -> 0% width
   *    0% (Breakeven)  -> 23% width
   *   +3% (Soft Target)-> 46% width
   *  +10% (Hard Target)-> 100% width
   *
   * @param {Object} portfolio
   */
  function updateTargetProgressBar(portfolio) {
    if (!portfolio) return;

    const barEl = getEl('target-progress-bar');
    const labelEl = getEl('target-progress-label');
    const hardLabelEl = getEl('hard-target-label');
    const maxLossLabelEl = getEl('max-loss-label');

    const dailyPct = Number(portfolio.daily_return_pct != null ? portfolio.daily_return_pct : 0);
    const realizedUsd = Number(portfolio.realized_pnl_usd != null ? portfolio.realized_pnl_usd : 0);
    const targetProfitUsd = Number(portfolio.target_profit_usd != null ? portfolio.target_profit_usd : 300);
    const targetPct = Number(portfolio.target_pct != null ? portfolio.target_pct : 3.0);

    const hardTargetPct = Number(portfolio.hard_target_pct != null ? portfolio.hard_target_pct : 10.0);
    const hardTargetUsd = Number(portfolio.hard_target_profit_usd != null ? portfolio.hard_target_profit_usd : 1000);

    const maxLossPct = Number(portfolio.max_loss_pct != null ? portfolio.max_loss_pct : 3.0);
    const maxLossUsd = Number(portfolio.max_loss_usd != null ? portfolio.max_loss_usd : 300);

    // Update target label
    if (labelEl) {
      const sign = dailyPct >= 0 ? '+' : '';
      labelEl.textContent = `${sign}${dailyPct.toFixed(2)}% (${formatSignedCurrency(realizedUsd)} / ${formatCurrency(targetProfitUsd)})`;
      if (dailyPct >= targetPct) {
        labelEl.className = 'font-mono text-xs font-bold text-emerald-300 bg-emerald-950/90 border border-emerald-400 px-2 py-0.5 rounded shadow-[0_0_8px_rgba(16,185,129,0.5)]';
      } else if (dailyPct < 0) {
        labelEl.className = 'font-mono text-xs font-bold text-rose-400 bg-rose-950/60 border border-rose-500/30 px-2 py-0.5 rounded';
      } else {
        labelEl.className = 'font-mono text-xs font-bold text-emerald-400 bg-emerald-950/60 border border-emerald-500/30 px-2 py-0.5 rounded';
      }
    }

    if (hardLabelEl) {
      hardLabelEl.textContent = `+${hardTargetPct.toFixed(1)}% Hard Target (${formatCurrency(hardTargetUsd)})`;
    }
    if (maxLossLabelEl) {
      maxLossLabelEl.textContent = `-${maxLossPct.toFixed(1)}% Max Loss (-${formatCurrency(maxLossUsd)})`;
    }

    // Piecewise linear interpolation matching track marker pins:
    let barWidth = 23;
    if (dailyPct <= 0) {
      const fraction = Math.max(0, (dailyPct + maxLossPct) / (maxLossPct || 3));
      barWidth = fraction * 23;
    } else if (dailyPct <= targetPct) {
      const fraction = dailyPct / (targetPct || 3);
      barWidth = 23 + fraction * (46 - 23);
    } else {
      const fraction = Math.min(1, (dailyPct - targetPct) / ((hardTargetPct - targetPct) || 7));
      barWidth = 46 + fraction * (100 - 46);
    }

    barWidth = Math.max(0, Math.min(100, barWidth));

    if (barEl) {
      barEl.style.width = `${barWidth.toFixed(1)}%`;
      if (dailyPct < 0) {
        barEl.className = 'target-progress-fill bg-gradient-to-r from-rose-700 to-rose-500';
      } else if (dailyPct >= hardTargetPct) {
        barEl.className = 'target-progress-fill bg-gradient-to-r from-emerald-500 via-cyan-400 to-purple-500 shadow-[0_0_12px_rgba(6,182,212,0.7)]';
      } else if (dailyPct >= targetPct) {
        barEl.className = 'target-progress-fill bg-gradient-to-r from-emerald-500 to-cyan-400 shadow-[0_0_8px_rgba(16,185,129,0.5)]';
      } else {
        barEl.className = 'target-progress-fill bg-gradient-to-r from-emerald-600 to-emerald-400';
      }
    }
  }

  /**
   * Renders active open positions into the table body.
   *
   * @param {Array<Object>} positions
   */
  function renderPositionsTable(positions) {
    const tbody = getEl('open-positions-tbody');
    const countEl = getEl('open-positions-count');

    const posList = Array.isArray(positions) ? positions : [];
    if (countEl) {
      countEl.textContent = String(posList.length);
    }

    if (!tbody) return;

    if (posList.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="8" class="text-center py-6 text-slate-500 text-xs italic font-mono">
            No active open positions. Specialist agents scanning market...
          </td>
        </tr>
      `;
      return;
    }

    const rowsHtml = posList.map((pos) => {
      const ticket = pos.ticket != null ? `#${pos.ticket}` : '#--';
      const symbol = escapeHtml(pos.symbol || '--');
      const typeStr = String(pos.type || pos.side || 'BUY').toUpperCase();
      const isBuy = typeStr.includes('BUY') || typeStr === '0';
      const typeBadge = isBuy
        ? '<span class="badge-buy">BUY</span>'
        : '<span class="badge-sell">SELL</span>';

      const volume = Number(pos.volume || pos.lot || 0).toFixed(2);
      const openPrice = pos.open_price != null
        ? Number(pos.open_price).toFixed(pos.open_price > 500 ? 2 : 4)
        : '--';
      const currentPrice = pos.current_price != null
        ? Number(pos.current_price).toFixed(pos.current_price > 500 ? 2 : 4)
        : '--';

      const slStr = pos.sl && Number(pos.sl) > 0
        ? Number(pos.sl).toFixed(pos.sl > 500 ? 2 : 4)
        : '-';
      const tpStr = pos.tp && Number(pos.tp) > 0
        ? Number(pos.tp).toFixed(pos.tp > 500 ? 2 : 4)
        : '-';
      const slTp = `${slStr} / ${tpStr}`;

      const profit = Number(pos.profit != null ? pos.profit : 0);
      const profitClass = profit > 0 ? 'text-emerald-400 font-bold' : profit < 0 ? 'text-rose-400 font-bold' : 'text-slate-300 font-bold';
      const profitText = formatSignedCurrency(profit);

      return `
        <tr>
          <td class="text-slate-400 font-mono">${ticket}</td>
          <td class="font-bold text-slate-200">${symbol}</td>
          <td>${typeBadge}</td>
          <td class="text-slate-300">${volume}</td>
          <td class="text-slate-300">${openPrice}</td>
          <td class="text-slate-200 font-semibold">${currentPrice}</td>
          <td class="text-slate-400">${slTp}</td>
          <td class="text-right ${profitClass}">${profitText}</td>
        </tr>
      `;
    }).join('');

    tbody.innerHTML = rowsHtml;
  }

  /**
   * Renders today's closed orders feed.
   *
   * @param {Array<Object>} orders
   */
  function renderClosedOrders(orders) {
    const container = getEl('closed-orders-list');
    if (!container) return;

    const orderList = Array.isArray(orders) ? orders : [];
    if (orderList.length === 0) {
      container.innerHTML = `
        <div class="text-center py-6 text-slate-500 text-xs italic font-mono">
          No orders closed today.
        </div>
      `;
      return;
    }

    const itemsHtml = orderList.slice().reverse().map((order) => {
      const symbol = escapeHtml(order.symbol || '--');
      const typeStr = String(order.type || order.side || 'BUY').toUpperCase();
      const isBuy = typeStr.includes('BUY') || typeStr === '0';
      const badge = isBuy ? '<span class="badge-buy">BUY</span>' : '<span class="badge-sell">SELL</span>';
      const volume = Number(order.volume || order.lot || 0).toFixed(2);
      const profit = Number(order.profit != null ? order.profit : 0);
      const profitClass = profit > 0 ? 'text-emerald-400 font-bold' : profit < 0 ? 'text-rose-400 font-bold' : 'text-slate-300 font-bold';

      let timeStr = '';
      const rawTime = order.close_time || order.time || order.timestamp;
      if (rawTime) {
        try {
          const d = typeof rawTime === 'number'
            ? (rawTime > 1e11 ? new Date(rawTime) : new Date(rawTime * 1000))
            : new Date(rawTime);
          timeStr = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'UTC' }) + ' UTC';
        } catch {
          timeStr = String(rawTime);
        }
      }

      return `
        <div class="flex items-center justify-between p-2 rounded bg-slate-900/60 border border-slate-800/80 text-xs font-mono">
          <div class="flex items-center gap-2">
            ${badge}
            <span class="font-bold text-slate-200">${symbol}</span>
            <span class="text-slate-500 text-[11px]">${volume} lot</span>
          </div>
          <div class="flex items-center gap-3">
            ${timeStr ? `<span class="text-slate-500 text-[11px]">${timeStr}</span>` : ''}
            <span class="${profitClass}">${formatSignedCurrency(profit)}</span>
          </div>
        </div>
      `;
    }).join('');

    container.innerHTML = itemsHtml;
  }

  /**
   * Renders specialist squad monitor cards (Gold, BTC, ETH).
   *
   * @param {Object} specialists
   */
  function renderSpecialistCards(specialists) {
    const container = getEl('specialist-squad-container');
    if (!container || !specialists) return;

    const agentIcons = {
      gold: { icon: '🥇', color: 'text-amber-400' },
      btc: { icon: '⚡', color: 'text-amber-500' },
      eth: { icon: '💎', color: 'text-purple-400' },
    };

    const getStatusBadge = (status) => {
      const s = String(status || 'WAIT').toUpperCase();
      if (s === 'ACTIVE' || s === 'IN_TRADE') {
        return '<span class="status-badge px-2 py-0.5 text-[10px] font-mono rounded bg-emerald-950/80 text-emerald-400 border border-emerald-500/40">ACTIVE</span>';
      }
      if (s === 'SCANNING' || s === 'WAIT') {
        return '<span class="status-badge px-2 py-0.5 text-[10px] font-mono rounded bg-blue-950/80 text-blue-400 border border-blue-500/40">WAIT</span>';
      }
      if (s === 'TARGET_REACHED' || s === 'STOPPED' || s === 'LOCKED') {
        return '<span class="status-badge px-2 py-0.5 text-[10px] font-mono rounded bg-purple-950/80 text-purple-400 border border-purple-500/40">LOCKED</span>';
      }
      return `<span class="status-badge px-2 py-0.5 text-[10px] font-mono rounded bg-slate-800 text-slate-400 border border-slate-700">${escapeHtml(s)}</span>`;
    };

    const keys = Object.keys(specialists);
    if (keys.length === 0) return;

    const cardsHtml = keys.map((key) => {
      const agent = specialists[key];
      const meta = agentIcons[key.toLowerCase()] || { icon: '🤖', color: 'text-blue-400' };
      const name = escapeHtml(agent.name || `${key}SpecialistAgent`);
      const symbol = escapeHtml(agent.symbol || key.toUpperCase());
      const strategy = escapeHtml(agent.strategy || 'Autonomous Strategy');
      const conf = agent.confidence != null
        ? Number(agent.confidence).toFixed(2)
        : (agent.conf != null ? Number(agent.conf).toFixed(2) : '0.0');
      const statusBadge = getStatusBadge(agent.status);

      return `
        <div class="specialist-card" data-agent="${escapeHtml(key)}">
          <div class="flex items-center justify-between mb-1">
            <div class="flex items-center gap-2">
              <span class="${meta.color} font-bold text-xs">${meta.icon} ${name}</span>
              <span class="font-mono text-[11px] bg-slate-800 px-1.5 py-0.5 rounded text-slate-300">${symbol}</span>
            </div>
            ${statusBadge}
          </div>
          <div class="text-[11px] text-slate-400 flex justify-between font-mono">
            <span>${strategy}</span>
            <span class="text-slate-300 font-semibold">Conf: ${conf}</span>
          </div>
        </div>
      `;
    }).join('');

    container.innerHTML = cardsHtml;
  }

  /**
   * Updates connection status pill and latency indicator in the header.
   *
   * @param {'connected'|'connecting'|'reconnecting'|'disconnected'} status
   * @param {number|null} latencyMs
   */
  function updateConnectionStatus(status, latencyMs = null) {
    const statusEl = getEl('connection-status');
    const pingEl = getEl('connection-ping');

    if (status === 'connected') {
      if (statusEl) {
        statusEl.className = 'inline-flex items-center px-2 py-0.5 rounded text-xs font-mono bg-emerald-950/80 text-emerald-400 border border-emerald-500/30';
        statusEl.innerHTML = '<span class="w-2 h-2 mr-1.5 rounded-full bg-emerald-500 pulse-green"></span>CONNECTED';
      }
      if (pingEl && latencyMs != null) {
        pingEl.textContent = `${latencyMs}ms`;
        pingEl.className = 'text-xs font-mono text-slate-400 ml-1.5';
      }
    } else if (status === 'connecting') {
      if (statusEl) {
        statusEl.className = 'inline-flex items-center px-2 py-0.5 rounded text-xs font-mono bg-amber-950/80 text-amber-400 border border-amber-500/30';
        statusEl.innerHTML = '<span class="w-2 h-2 mr-1.5 rounded-full bg-amber-500 pulse-yellow"></span>CONNECTING...';
      }
      if (pingEl) {
        pingEl.textContent = '--';
      }
    } else if (status === 'reconnecting') {
      if (statusEl) {
        statusEl.className = 'inline-flex items-center px-2 py-0.5 rounded text-xs font-mono bg-amber-950/80 text-amber-400 border border-amber-500/30';
        statusEl.innerHTML = '<span class="w-2 h-2 mr-1.5 rounded-full bg-amber-500 pulse-yellow"></span>RECONNECTING...';
      }
      if (pingEl) {
        pingEl.textContent = '--';
      }
    } else {
      if (statusEl) {
        statusEl.className = 'inline-flex items-center px-2 py-0.5 rounded text-xs font-mono bg-rose-950/80 text-rose-400 border border-rose-500/30';
        statusEl.innerHTML = '<span class="w-2 h-2 mr-1.5 rounded-full bg-rose-500 pulse-red"></span>DISCONNECTED';
      }
      if (pingEl) {
        pingEl.textContent = 'offline';
        pingEl.className = 'text-xs font-mono text-rose-400 ml-1.5';
      }
    }
  }

  /**
   * Starts UTC digital clock updater ticking every 1 second.
   */
  function startUtcClock() {
    stopUtcClock();
    const clockEl = getEl('utc-clock');
    function tick() {
      if (!clockEl) return;
      const now = new Date();
      const h = String(now.getUTCHours()).padStart(2, '0');
      const m = String(now.getUTCMinutes()).padStart(2, '0');
      const s = String(now.getUTCSeconds()).padStart(2, '0');
      clockEl.textContent = `${h}:${m}:${s} UTC`;
    }
    tick();
    state.clockIntervalId = setInterval(tick, 1000);
  }

  /**
   * Stops UTC digital clock updater.
   */
  function stopUtcClock() {
    if (state.clockIntervalId) {
      clearInterval(state.clockIntervalId);
      state.clockIntervalId = null;
    }
  }

  /**
   * Sends WebSocket subscription message for symbol and timeframe.
   *
   * @param {string} symbol
   * @param {string} timeframe
   */
  function subscribe(symbol, timeframe) {
    state.currentSymbol = symbol.toUpperCase();
    state.currentTimeframe = timeframe.toUpperCase();

    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify({
        action: 'subscribe',
        symbol: state.currentSymbol,
        timeframe: state.currentTimeframe,
      }));
    }

    // Immediately re-draw trade lines for newly selected symbol
    if (window.PilotfishChart) {
      window.PilotfishChart.renderTradeLines(state.openPositions, state.currentSymbol);
    }
  }

  /**
   * Sends ping heartbeat over WebSocket to measure round-trip latency.
   */
  function sendPing() {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.lastPingSentTime = (typeof performance !== 'undefined' && performance.now)
        ? performance.now()
        : Date.now();
      state.ws.send(JSON.stringify({ action: 'ping' }));
    }
  }

  /**
   * Starts periodic ping heartbeat every 15s.
   */
  function startPingHeartbeat() {
    stopPingHeartbeat();
    setTimeout(sendPing, 500);
    state.pingIntervalId = setInterval(sendPing, CONFIG.pingIntervalMs);
  }

  /**
   * Stops periodic ping heartbeat.
   */
  function stopPingHeartbeat() {
    if (state.pingIntervalId) {
      clearInterval(state.pingIntervalId);
      state.pingIntervalId = null;
    }
  }

  /**
   * Handles incoming WebSocket messages.
   *
   * @param {string} rawData
   */
  function handleSocketMessage(rawData) {
    let data;
    try {
      data = typeof rawData === 'string' ? JSON.parse(rawData) : rawData;
    } catch (err) {
      console.warn('[DashboardWS] Failed to parse message JSON:', err);
      return;
    }

    if (!data || typeof data !== 'object') return;

    const msgType = data.type || (data.action === 'pong' ? 'pong' : '');

    // 1. PONG latency calculation
    if (msgType === 'pong') {
      if (state.lastPingSentTime != null) {
        const now = (typeof performance !== 'undefined' && performance.now)
          ? performance.now()
          : Date.now();
        const latency = Math.max(1, Math.round(now - state.lastPingSentTime));
        updateConnectionStatus('connected', latency);
      }
      return;
    }

    // 2. Initial or full SNAPSHOT
    if (msgType === 'snapshot') {
      if (data.account) state.account = data.account;
      if (data.portfolio) state.portfolio = data.portfolio;
      if (Array.isArray(data.open_positions)) state.openPositions = data.open_positions;
      if (Array.isArray(data.closed_orders)) state.closedOrders = data.closed_orders;
      if (data.specialists) state.specialists = data.specialists;

      if (data.symbol) {
        state.currentSymbol = data.symbol.toUpperCase();
        highlightActiveSymbolButton(state.currentSymbol);
      }
      if (data.timeframe) {
        state.currentTimeframe = data.timeframe.toUpperCase();
        highlightActiveTimeframeButton(state.currentTimeframe);
      }

      updateKpiCards(state.account, state.portfolio);
      updateTargetProgressBar(state.portfolio);
      renderPositionsTable(state.openPositions);
      renderClosedOrders(state.closedOrders);
      renderSpecialistCards(state.specialists);

      if (window.PilotfishChart) {
        if (Array.isArray(data.bars) && data.bars.length > 0) {
          window.PilotfishChart.setCandles(data.bars);
        }
        window.PilotfishChart.renderTradeLines(state.openPositions, state.currentSymbol);
      }
      return;
    }

    // 3. Historical or full BARS response (e.g. after symbol/tf change)
    if (msgType === 'bars') {
      if (data.symbol && data.symbol.toUpperCase() === state.currentSymbol) {
        if (window.PilotfishChart && Array.isArray(data.bars)) {
          window.PilotfishChart.setCandles(data.bars);
          window.PilotfishChart.renderTradeLines(state.openPositions, state.currentSymbol);
        }
      }
      return;
    }

    // 4. Real-time candle / tick update
    if (msgType === 'bar_update' || msgType === 'candle' || data.bar) {
      const bar = data.bar || data.candle;
      if (window.PilotfishChart && bar) {
        window.PilotfishChart.updateLastCandle(bar);
      }
      return;
    }

    // 5. Telemetry / Account / Positions live event
    if (msgType === 'telemetry' || msgType === 'account_update' || msgType === 'tick') {
      if (data.account) {
        state.account = Object.assign({}, state.account, data.account);
      }
      if (data.portfolio) {
        state.portfolio = Object.assign({}, state.portfolio, data.portfolio);
      }
      if (Array.isArray(data.open_positions)) {
        state.openPositions = data.open_positions;
      }
      if (Array.isArray(data.closed_orders)) {
        state.closedOrders = data.closed_orders;
      }
      if (data.specialists) {
        state.specialists = Object.assign({}, state.specialists, data.specialists);
      }

      updateKpiCards(state.account, state.portfolio);
      updateTargetProgressBar(state.portfolio);
      renderPositionsTable(state.openPositions);
      if (data.closed_orders) renderClosedOrders(state.closedOrders);
      if (data.specialists) renderSpecialistCards(state.specialists);

      if (window.PilotfishChart && (data.open_positions || data.positions)) {
        window.PilotfishChart.renderTradeLines(state.openPositions, state.currentSymbol);
      }
    }
  }

  /**
   * Connects to WebSocket server at /ws/live with auto-reconnection and exponential backoff.
   */
  function connectWebSocket() {
    if (state.ws) {
      try {
        state.ws.close();
      } catch {}
      state.ws = null;
    }

    if (state.reconnectTimeoutId) {
      clearTimeout(state.reconnectTimeoutId);
      state.reconnectTimeoutId = null;
    }

    updateConnectionStatus(state.reconnectAttempts > 0 ? 'reconnecting' : 'connecting');

    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${window.location.host}${CONFIG.wsPath}`;

    try {
      const ws = new WebSocket(wsUrl);
      state.ws = ws;

      ws.onopen = function () {
        console.info('[DashboardWS] Connected successfully to', wsUrl);
        state.reconnectAttempts = 0;
        updateConnectionStatus('connected');
        startPingHeartbeat();

        // If symbol/timeframe is not default, subscribe immediately
        if (state.currentSymbol !== CONFIG.defaultSymbol || state.currentTimeframe !== CONFIG.defaultTimeframe) {
          subscribe(state.currentSymbol, state.currentTimeframe);
        }
      };

      ws.onmessage = function (event) {
        handleSocketMessage(event.data);
      };

      ws.onerror = function (err) {
        console.warn('[DashboardWS] WebSocket connection error:', err);
      };

      ws.onclose = function (event) {
        console.warn('[DashboardWS] WebSocket closed (code: ' + event.code + '). Scheduling reconnect...');
        stopPingHeartbeat();
        updateConnectionStatus('disconnected');
        scheduleReconnect();
      };
    } catch (err) {
      console.error('[DashboardWS] Exception while establishing WebSocket:', err);
      updateConnectionStatus('disconnected');
      scheduleReconnect();
    }
  }

  /**
   * Schedules reconnection with exponential backoff clamped between 1s and 5s.
   */
  function scheduleReconnect() {
    if (state.reconnectTimeoutId) return;

    state.reconnectAttempts++;
    const delay = Math.min(
      CONFIG.reconnectMaxDelayMs,
      CONFIG.reconnectBaseDelayMs * Math.pow(CONFIG.reconnectBackoffMultiplier, state.reconnectAttempts - 1)
    );

    console.info(`[DashboardWS] Reconnecting in ${Math.round(delay)}ms (attempt ${state.reconnectAttempts})...`);
    state.reconnectTimeoutId = setTimeout(() => {
      state.reconnectTimeoutId = null;
      connectWebSocket();
    }, delay);
  }

  /**
   * Highlights active symbol button in the toolbar.
   *
   * @param {string} symbol
   */
  function highlightActiveSymbolButton(symbol) {
    const container = getEl('symbol-buttons');
    if (!container) return;
    const buttons = container.querySelectorAll('button');
    buttons.forEach((btn) => {
      const sym = (btn.dataset.symbol || btn.textContent || '').trim().toUpperCase();
      if (sym === symbol.toUpperCase()) {
        btn.classList.add('term-btn-active');
      } else {
        btn.classList.remove('term-btn-active');
      }
    });
  }

  /**
   * Highlights active timeframe button in the toolbar.
   *
   * @param {string} timeframe
   */
  function highlightActiveTimeframeButton(timeframe) {
    const container = getEl('timeframe-buttons');
    if (!container) return;
    const buttons = container.querySelectorAll('button');
    buttons.forEach((btn) => {
      const tf = (btn.dataset.tf || btn.dataset.timeframe || btn.textContent || '').trim().toUpperCase();
      if (tf === timeframe.toUpperCase()) {
        btn.classList.add('term-btn-active');
      } else {
        btn.classList.remove('term-btn-active');
      }
    });
  }

  /**
   * Binds click events for Symbol and Timeframe toolbar selectors.
   */
  function bindUiEvents() {
    const symbolContainer = getEl('symbol-buttons');
    if (symbolContainer && typeof symbolContainer.addEventListener === 'function') {
      symbolContainer.addEventListener('click', (e) => {
        const btn = e.target.closest ? e.target.closest('button') : null;
        if (!btn) return;
        const symbol = (btn.dataset.symbol || btn.textContent || '').trim().toUpperCase();
        if (!symbol) return;

        highlightActiveSymbolButton(symbol);
        subscribe(symbol, state.currentTimeframe);
      });
    }

    const tfContainer = getEl('timeframe-buttons');
    if (tfContainer && typeof tfContainer.addEventListener === 'function') {
      tfContainer.addEventListener('click', (e) => {
        const btn = e.target.closest ? e.target.closest('button') : null;
        if (!btn) return;
        const tf = (btn.dataset.tf || btn.dataset.timeframe || btn.textContent || '').trim().toUpperCase();
        if (!tf) return;

        highlightActiveTimeframeButton(tf);
        subscribe(state.currentSymbol, tf);
      });
    }
  }

  /**
   * Master dashboard initializer.
   */
  function init() {
    // 1. Initialize Lightweight Chart canvas if available
    if (window.PilotfishChart && typeof window.PilotfishChart.initChart === 'function') {
      window.PilotfishChart.initChart('tv-chart');
    }

    // 2. Start digital clock updater
    startUtcClock();

    // 3. Bind UI event listeners
    bindUiEvents();

    // 4. Connect WebSocket client
    connectWebSocket();

    console.info('[PilotfishDashboard] Initialized successfully. Default:', state.currentSymbol, state.currentTimeframe);
  }

  /**
   * Destroys all background timers and closes WebSocket connection.
   */
  function destroy() {
    stopUtcClock();
    stopPingHeartbeat();
    if (state.reconnectTimeoutId) {
      clearTimeout(state.reconnectTimeoutId);
      state.reconnectTimeoutId = null;
    }
    if (state.ws) {
      try {
        state.ws.close();
      } catch {}
      state.ws = null;
    }
  }

  // Exposed API
  const PilotfishDashboard = {
    init,
    destroy,
    getState: () => ({ ...state }),
    connect: connectWebSocket,
    subscribe,
    startUtcClock,
    stopUtcClock,
    startPingHeartbeat,
    stopPingHeartbeat,
    updateKpiCards,
    updateTargetProgressBar,
    renderPositionsTable,
    renderClosedOrders,
    renderSpecialistCards,
    updateConnectionStatus,
    flashMetric,
    formatCurrency,
    formatSignedCurrency,
  };

  // Export to global window object
  if (typeof window !== 'undefined') {
    window.PilotfishDashboard = PilotfishDashboard;

    // Auto-run init when DOM is ready in browser environment
    if (typeof document !== 'undefined') {
      if (document.readyState === 'loading' && typeof document.addEventListener === 'function') {
        document.addEventListener('DOMContentLoaded', init);
      } else {
        init();
      }
    }
  }

  // Export for CommonJS / Node test runners
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = PilotfishDashboard;
  }
})();
