# dev_status.ps1 - one-screen snapshot of the daytrad DEV stack (bridge + dev shell).
# Used by the 3-hour review loop. Exit: 0 = OK, 1 = WARN, 2 = DOWN.
# ASCII only on purpose: Windows PowerShell 5.1 reads BOM-less files as ANSI.
param([string]$Bridge = 'http://127.0.0.1:8000')

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$warn = @()

function Try-Get($url) {
    try { Invoke-RestMethod -Uri $url -TimeoutSec 10 } catch { $null }
}

"## Daytrad DEV - {0:yyyy-MM-dd HH:mm:ss} (Asia/Bangkok)" -f (Get-Date)
""

# --- 1. containers -----------------------------------------------------------
foreach ($c in 'agentic_mt5_bridge', 'agentic_dev') {
    $state = (docker inspect -f '{{.State.Status}}{{if .State.Health}}/{{.State.Health.Status}}{{end}}' $c 2>$null)
    if (-not $state) { "CONTAINER $c = MISSING"; $warn += "$c missing" }
    else {
        "CONTAINER $c = $state"
        if ($state -notmatch '^running(/healthy)?$') { $warn += "$c=$state" }
    }
}

# --- 2. bridge / MT5 ---------------------------------------------------------
$st = Try-Get "$Bridge/api/mt5/status"
if (-not $st) { "BRIDGE = DOWN ($Bridge)"; "VERDICT = DOWN"; exit 2 }
"BRIDGE = {0} | connected={1} | {2} @ {3}" -f $st.status, $st.connected, $st.account_number, $st.server
if (-not $st.connected) { $warn += 'MT5 disconnected' }

$acct = Try-Get "$Bridge/api/mt5/account"
if ($acct) {
    $cur = if ($acct.currency) { $acct.currency } else { $st.currency }
    "ACCOUNT = {0:N2} {1} | equity {2:N2}" -f $acct.balance, $cur, $acct.equity
    $ops = @($acct.open_positions)
    "OPEN POSITIONS = {0}" -f $ops.Count
    foreach ($p in $ops) {
        "  - {0} {1} ticket={2} vol={3} open={4} pnl={5}" -f $p.symbol, $p.type, $p.ticket, $p.volume, $p.price_open, $p.profit
    }
}

# --- 3. data freshness (measured from the bars themselves, not the bridge
#        heartbeat -- the heartbeat says "received Xs ago" even when the EA is
#        re-sending an old bar, e.g. when the market is closed) ---------------
$nowEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$tfExpect = @{ 'M5' = 300; 'M15' = 900 }
$stale = @()
$mismatch = @()
$closed = @()
foreach ($sym in 'XAUUSD', 'BTCUSD', 'ETHUSD') {
    $line = "BARS $sym"
    foreach ($tf in 'M5', 'M15') {
        # NOTE: the query parameter is `timeframe` (not `tf`). A wrong name is
        # silently ignored by FastAPI and falls back to the M15 default, which
        # looks like "M5 returns 900s bars" even though the feed is fine.
        $r = Try-Get "$Bridge/api/mt5/bars?symbol=$sym&timeframe=$tf"
        $bars = @($r.bars)
        if ($bars.Count -lt 2) { $line += " | ${tf}=n/a"; $stale += "${sym}:${tf} empty"; continue }
        $age = $nowEpoch - [int64]$bars[-1].timestamp
        $step = [int64]$bars[-1].timestamp - [int64]$bars[-2].timestamp
        $line += " | ${tf} age=${age}s step=${step}s"
        if ($step -ne $tfExpect[$tf]) { $mismatch += "${sym}:${tf} gives ${step}s bars (expected $($tfExpect[$tf])s)" }
        if ($age -gt 3600) { $closed += "${sym}:${tf}" } elseif ($age -gt ($tfExpect[$tf] * 1.5)) { $stale += "${sym}:${tf} ${age}s" }
    }
    $line
}
if ($mismatch.Count) { "TF MISMATCH: " + ($mismatch -join '; '); $warn += 'timeframe mismatch (EA sending wrong TF)' }
if ($closed.Count) { "NO RECENT BARS (market closed?): " + ($closed -join ', ') }
if ($stale.Count) { "STALE DATA: " + ($stale -join ', '); $warn += 'stale market data' }

# --- 4. daily baseline (the system's own day-start number) -------------------
$baselineFile = Join-Path $repo 'journal/daily_baseline.json'
if (Test-Path $baselineFile) {
    $b = Get-Content $baselineFile -Raw | ConvertFrom-Json
    "DAILY BASELINE = " + ($b | ConvertTo-Json -Compress)
    if ($acct -and [double]$b.balance -gt 0) {
        $pnl = [double]$acct.equity - [double]$b.balance
        $pnlPct = 100.0 * $pnl / [double]$b.balance
        "P&L SINCE DAY START = {0:N2} ({1:N2}%)" -f $pnl, $pnlPct
        if (-$pnlPct -ge 5) { $warn += 'daily loss cutoff reached (-5%)' }
    }
} else { "DAILY BASELINE = (none)" }

# --- 5. verdict --------------------------------------------------------------
""
if ($warn.Count) { "VERDICT = WARN (" + ($warn -join '; ') + ")"; exit 1 }
"VERDICT = OK"
exit 0
