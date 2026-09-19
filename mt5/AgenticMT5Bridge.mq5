//+------------------------------------------------------------------+
//|                                         AgenticMT5Bridge.mq5     |
//|               Autonomous Gold (XAUUSD) Agentic Trading Bridge   |
//|                                  Copyright 2026, Agentic Trader  |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, Agentic Trader"
#property link      "https://github.com/agentic-gold"
#property version   "2.00"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\AccountInfo.mqh>

//--- Input Parameters
input string   InpServerUrl       = "http://127.0.0.1:8000"; // Python Bridge URL
input int      InpPollIntervalMs   = 1000;                     // Polling Interval in ms
input ulong    InpMagicNumber     = 888999;                   // Expert Magic Number
input ulong    InpDeviationPoints = 30;                       // Max Slippage/Deviation
input bool     InpUseFilePipe     = false;                    // Enable File Pipe Fallback
input bool     InpRequireStops    = true;                     // Reject unprotected live opens

//--- Global Objects
CTrade         g_trade;
CPositionInfo  g_pos;
CAccountInfo   g_account;
datetime       g_lastHistorySync  = 0;

// StringToCharArray(..., WHOLE_ARRAY, CP_UTF8) appends a C-string NUL.
// HTTP JSON bodies must not include it; keep the conversion in one place so
// telemetry and execution confirmations use the same wire format.
bool JsonToUtf8Bytes(const string json, char &bytes[])
{
   int copied = StringToCharArray(json, bytes, 0, WHOLE_ARRAY, CP_UTF8);
   if(copied <= 0)
      return false;
   if(ArraySize(bytes) > 0 && bytes[ArraySize(bytes) - 1] == 0)
      ArrayResize(bytes, ArraySize(bytes) - 1);
   return ArraySize(bytes) > 0;
}

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   g_trade.SetExpertMagicNumber(InpMagicNumber);
   g_trade.SetDeviationInPoints(InpDeviationPoints);
   g_trade.SetTypeFilling(ORDER_FILLING_IOC);
   
   Print("[AgenticMT5] Initialized for symbol: ", Symbol(), " Account: ", AccountInfoInteger(ACCOUNT_LOGIN), " Server: ", AccountInfoString(ACCOUNT_SERVER));
   EventSetMillisecondTimer(InpPollIntervalMs);
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   Print("[AgenticMT5] Deinitialized. Reason: ", reason);
}

//+------------------------------------------------------------------+
//| Timer event function (called every InpPollIntervalMs)            |
//+------------------------------------------------------------------+
void OnTimer()
{
   SendTelemetry();
   SendMarketBars("XAUUSD", PERIOD_M15, 120);
   SendMarketBars("BTCUSD", PERIOD_M15, 120);
   SendMarketBars("ETHUSD", PERIOD_M15, 120);
   PollCommands();
   CheckFileCommands();
}

//+------------------------------------------------------------------+
//| Tick event function (fires on every price movement)              |
//+------------------------------------------------------------------+
void OnTick()
{
   static datetime lastTickRun = 0;
   if(TimeCurrent() - lastTickRun >= 1)
   {
      lastTickRun = TimeCurrent();
      SendTelemetry();
      PollCommands();
      CheckFileCommands();
   }
}

//+------------------------------------------------------------------+
//| Upload fresh OHLCV bars for each specialist symbol               |
//+------------------------------------------------------------------+
void SendMarketBars(const string symbol, const ENUM_TIMEFRAMES timeframe, const int count)
{
   if(!SymbolSelect(symbol, true))
      return;

   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int copied = CopyRates(symbol, timeframe, 0, count, rates);
   if(copied <= 0)
      return;

   string json = "{\"symbol\":\"" + symbol + "\",\"timeframe\":\"M15\",\"bars\":[";
   bool first = true;
   // Send oldest to newest so Python's tail(-1) is the current bar.
   for(int i = copied - 1; i >= 0; i--)
   {
      if(!first) json += ",";
      first = false;
      json += "{\"timestamp\":" + IntegerToString((long)rates[i].time) + ",";
      json += "\"open\":" + DoubleToString(rates[i].open, 8) + ",";
      json += "\"high\":" + DoubleToString(rates[i].high, 8) + ",";
      json += "\"low\":" + DoubleToString(rates[i].low, 8) + ",";
      json += "\"close\":" + DoubleToString(rates[i].close, 8) + ",";
      json += "\"volume\":" + IntegerToString((long)rates[i].tick_volume) + "}";
   }
   json += "]}";

   char postData[];
   char result[];
   string resultHeaders;
   string headers = "Content-Type: application/json\r\n";
   if(!JsonToUtf8Bytes(json, postData))
      return;

   int res = WebRequest("POST", InpServerUrl + "/api/mt5/bars", headers, 1000,
                        postData, result, resultHeaders);
   if(res == -1)
   {
      static datetime lastBarsErr = 0;
      if(TimeCurrent() - lastBarsErr >= 15)
      {
         lastBarsErr = TimeCurrent();
         Print("[AgenticMT5] Bar upload failed for ", symbol, ". Error: ", GetLastError());
      }
   }
}

//+------------------------------------------------------------------+
//| Send Telemetry (Account balance, equity, bid, ask, open orders)  |
//+------------------------------------------------------------------+
void SendTelemetry()
{
   double bid = SymbolInfoDouble(Symbol(), SYMBOL_BID);
   double ask = SymbolInfoDouble(Symbol(), SYMBOL_ASK);
   
   string json = "{";
   json += "\"account_number\":" + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)) + ",";
   json += "\"server\":\"" + AccountInfoString(ACCOUNT_SERVER) + "\",";
   json += "\"balance\":" + DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2) + ",";
   json += "\"equity\":" + DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY), 2) + ",";
   json += "\"symbol\":\"" + Symbol() + "\",";
   json += "\"bid\":" + DoubleToString(bid, 2) + ",";
   json += "\"ask\":" + DoubleToString(ask, 2) + ",";
   
   // Collect Open Positions for every symbol this bridge instance owns.
   // Filtering by the chart's Symbol() would hide positions on the other two
   // instruments the squad trades (XAUUSD/BTCUSD/ETHUSD).
   json += "\"open_positions\":[";
   int total = PositionsTotal();
   bool first = true;
   for(int i = 0; i < total; i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0 && g_pos.SelectByTicket(ticket))
      {
         if(g_pos.Magic() == InpMagicNumber)
         {
            if(!first) json += ",";
            first = false;
            string typeStr = (g_pos.PositionType() == POSITION_TYPE_BUY) ? "BUY" : "SELL";
            json += "{";
            json += "\"ticket\":" + IntegerToString(ticket) + ",";
            json += "\"symbol\":\"" + g_pos.Symbol() + "\",";
            json += "\"type\":\"" + typeStr + "\",";
            json += "\"lots\":" + DoubleToString(g_pos.Volume(), 2) + ",";
            json += "\"open_price\":" + DoubleToString(g_pos.PriceOpen(), 2) + ",";
            json += "\"sl\":" + DoubleToString(g_pos.StopLoss(), 2) + ",";
            json += "\"tp\":" + DoubleToString(g_pos.TakeProfit(), 2) + ",";
            json += "\"profit\":" + DoubleToString(g_pos.Profit(), 2) + ",";
            // Include per-symbol prices so the bridge can serve quotes for
            // symbols other than the one this EA is charted on.
            json += "\"bid\":" + DoubleToString(SymbolInfoDouble(g_pos.Symbol(), SYMBOL_BID), 2) + ",";
            json += "\"ask\":" + DoubleToString(SymbolInfoDouble(g_pos.Symbol(), SYMBOL_ASK), 2);
            json += "}";
         }
      }
   }
   json += "],";

   // Collect Closed Deals from Today (all symbols owned by this EA)
   json += "\"closed_orders\":[";
   datetime from = TimeCurrent() - 86400;
   HistorySelect(from, TimeCurrent());
   int dealsTotal = HistoryDealsTotal();
   bool firstDeal = true;
   for(int d = dealsTotal - 1; d >= 0 && d >= dealsTotal - 20; d--)
   {
      ulong dealTicket = HistoryDealGetTicket(d);
      if(dealTicket > 0)
      {
         long entryType = HistoryDealGetInteger(dealTicket, DEAL_ENTRY);
         long magic = HistoryDealGetInteger(dealTicket, DEAL_MAGIC);
         if(entryType == DEAL_ENTRY_OUT && magic == (long)InpMagicNumber) // Deal closed
         {
            if(!firstDeal) json += ",";
            firstDeal = false;
            double dealProfit = HistoryDealGetDouble(dealTicket, DEAL_PROFIT);
            double dealPrice = HistoryDealGetDouble(dealTicket, DEAL_PRICE);
            json += "{";
            json += "\"ticket\":" + IntegerToString(dealTicket) + ",";
            json += "\"symbol\":\"" + HistoryDealGetString(dealTicket, DEAL_SYMBOL) + "\",";
            json += "\"close_price\":" + DoubleToString(dealPrice, 2) + ",";
            json += "\"pnl_usd\":" + DoubleToString(dealProfit, 2);
            json += "}";
         }
      }
   }
   json += "]}";

   // Send via HTTP WebRequest
   string headers = "Content-Type: application/json\r\n";
   char postData[];
   char result[];
   string resultHeaders;
   if(!JsonToUtf8Bytes(json, postData))
   {
      Print("[AgenticMT5] Could not encode telemetry JSON");
      return;
   }
   
   int res = WebRequest("POST", InpServerUrl + "/api/mt5/telemetry", headers, 1000, postData, result, resultHeaders);
   if(res == -1)
   {
      int err = GetLastError();
      if((err == 4014 || err == 4060) && InpUseFilePipe) // WebRequest restricted -> use file pipe
      {
         WriteTelemetryToFile(json);
      }
   }
}

//+------------------------------------------------------------------+
//| Poll pending trade commands from Python agent                    |
//+------------------------------------------------------------------+
void PollCommands()
{
   char postData[];
   char result[];
   string resultHeaders;
   string headers = "Content-Type: application/json\r\n";
   
   int res = WebRequest("GET", InpServerUrl + "/api/mt5/commands", headers, 1000, postData, result, resultHeaders);
   if(res > 0 && ArraySize(result) > 0)
   {
      string responseText = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
      ExecuteCommand(responseText);
   }
   else if(res == -1)
   {
      static datetime lastErrLog = 0;
      if(TimeCurrent() - lastErrLog >= 15)
      {
         lastErrLog = TimeCurrent();
         int err = GetLastError();
         Print("[AgenticMT5] WebRequest returned error ", err, " - Please check Tools -> Options -> Expert Advisors -> WebRequest");
      }
   }
}

//+------------------------------------------------------------------+
//| Check for commands placed via file pipe                          |
//+------------------------------------------------------------------+
void CheckFileCommands()
{
   if(FileIsExist("agentic_mt5_commands.json"))
   {
      int handle = FileOpen("agentic_mt5_commands.json", FILE_READ | FILE_TXT | FILE_ANSI);
      if(handle != INVALID_HANDLE)
      {
         string json = "";
         while(!FileIsEnding(handle))
         {
            json += FileReadString(handle);
         }
         FileClose(handle);
         FileDelete("agentic_mt5_commands.json");
         
         Print("[AgenticMT5] [FILE-PIPE] Received command from file: ", json);
         ExecuteCommand(json);
      }
   }
}

//+------------------------------------------------------------------+
//| Execute incoming JSON command (ORDER_OPEN, ORDER_CLOSE, MODIFY)  |
//+------------------------------------------------------------------+
void ExecuteCommand(string json)
{
   if(StringFind(json, "ORDER_OPEN") >= 0)
   {
      // Trade the symbol named in the command, not the chart's Symbol().
      // MT5 permits trading any symbol from any chart, and this bridge serves
      // three instruments (XAUUSD/BTCUSD/ETHUSD) from a single EA instance.
      string cmdSymbol = ExtractString(json, "\"symbol\":\"", "\"");
      if(cmdSymbol == "") cmdSymbol = Symbol();

      string orderType = ExtractString(json, "\"type\":\"", "\"");
      bool isBuy = (orderType == "BUY");
      double volume = ExtractDouble(json, "\"volume\":", 0.01);
      double sl = ExtractDouble(json, "\"sl\":", 0.0);
      double tp = ExtractDouble(json, "\"tp\":", 0.0);
      string cmdId = ExtractString(json, "\"id\":\"", "\"");

      // Make sure the symbol exists and is subscribed in Market Watch.
      if(!SymbolSelect(cmdSymbol, true))
      {
         string msg = "Unknown or unavailable symbol: " + cmdSymbol;
         Print("[AgenticMT5] Order blocked. ", msg);
         ConfirmExecution(cmdId, "REJECTED", 0, msg);
         return;
      }

      // Validate volume and SL/TP sides before sending, so the EA returns a
      // readable rejection instead of a bare broker retcode.
      double bid = SymbolInfoDouble(cmdSymbol, SYMBOL_BID);
      double ask = SymbolInfoDouble(cmdSymbol, SYMBOL_ASK);

      if(volume <= 0)
      {
         ConfirmExecution(cmdId, "REJECTED", 0, "Invalid volume: " + DoubleToString(volume, 2));
         return;
      }
      if(bid <= 0 || ask <= 0)
      {
         ConfirmExecution(cmdId, "REJECTED", 0, "No price feed for " + cmdSymbol + " (bid/ask unavailable)");
         return;
      }
      if(orderType != "BUY" && orderType != "SELL")
      {
         ConfirmExecution(cmdId, "REJECTED", 0, "Invalid order type: " + orderType);
         return;
      }
      if(InpRequireStops && (sl <= 0 || tp <= 0))
      {
         ConfirmExecution(cmdId, "REJECTED", 0, "Both SL and TP are required for agentic orders");
         return;
      }
      double minVolume = SymbolInfoDouble(cmdSymbol, SYMBOL_VOLUME_MIN);
      double maxVolume = SymbolInfoDouble(cmdSymbol, SYMBOL_VOLUME_MAX);
      double volumeStep = SymbolInfoDouble(cmdSymbol, SYMBOL_VOLUME_STEP);
      if(volume < minVolume || volume > maxVolume || volumeStep <= 0 ||
         MathAbs(volume / volumeStep - MathRound(volume / volumeStep)) > 0.000001)
      {
         ConfirmExecution(cmdId, "REJECTED", 0,
                          "Volume must be within broker min/max and step (min=" +
                          DoubleToString(minVolume, 2) + ", max=" + DoubleToString(maxVolume, 2) + ")");
         return;
      }
      double point = SymbolInfoDouble(cmdSymbol, SYMBOL_POINT);
      double minStopDistance = (double)SymbolInfoInteger(cmdSymbol, SYMBOL_TRADE_STOPS_LEVEL) * point;
      if(isBuy && ((sl > 0 && sl > ask - minStopDistance) || (tp > 0 && tp < ask + minStopDistance)))
      {
         ConfirmExecution(cmdId, "REJECTED", 0, "BUY SL/TP violates broker minimum stop distance");
         return;
      }
      if(!isBuy && ((sl > 0 && sl > bid - minStopDistance) || (tp > 0 && tp < bid + minStopDistance)))
      {
         ConfirmExecution(cmdId, "REJECTED", 0, "SELL SL/TP violates broker minimum stop distance");
         return;
      }
      if(isBuy && sl > 0 && sl >= ask)
      {
         ConfirmExecution(cmdId, "REJECTED", 0, "BUY SL " + DoubleToString(sl, 2) + " >= ask " + DoubleToString(ask, 2));
         return;
      }
      if(!isBuy && sl > 0 && sl <= bid)
      {
         ConfirmExecution(cmdId, "REJECTED", 0, "SELL SL " + DoubleToString(sl, 2) + " <= bid " + DoubleToString(bid, 2));
         return;
      }
      if(isBuy && tp > 0 && tp <= bid)
      {
         ConfirmExecution(cmdId, "REJECTED", 0, "BUY TP " + DoubleToString(tp, 2) + " <= bid " + DoubleToString(bid, 2));
         return;
      }
      if(!isBuy && tp > 0 && tp >= ask)
      {
         ConfirmExecution(cmdId, "REJECTED", 0, "SELL TP " + DoubleToString(tp, 2) + " >= ask " + DoubleToString(ask, 2));
         return;
      }

      bool success = false;
      if(isBuy)
      {
         success = g_trade.Buy(volume, cmdSymbol, 0, sl, tp, "AgenticMT5");
      }
      else
      {
         success = g_trade.Sell(volume, cmdSymbol, 0, sl, tp, "AgenticMT5");
      }

      if(success)
      {
         ulong orderTicket = g_trade.ResultOrder();
         Print("[AgenticMT5] Order executed successfully. Ticket: #", orderTicket,
               " symbol=", cmdSymbol, " volume=", DoubleToString(volume, 2));
         ConfirmExecution(cmdId, "SUCCESS", orderTicket, "Executed in MT5");
      }
      else
      {
         uint retcode = g_trade.ResultRetcode();
         Print("[AgenticMT5] Order execution failed. Retcode: ", retcode,
               " (", g_trade.ResultRetcodeDescription(), ")");
         ConfirmExecution(cmdId, "FAILED", 0, "Retcode: " + IntegerToString(retcode));
      }
   }
   else if(StringFind(json, "ORDER_CLOSE") >= 0)
   {
      string cmdId = ExtractString(json, "\"id\":\"", "\"");
      ulong ticket = (ulong)ExtractDouble(json, "\"ticket\":", 0.0);
      bool success = false;
      if(ticket > 0 && g_pos.SelectByTicket(ticket) && g_pos.Magic() == InpMagicNumber)
      {
         success = g_trade.PositionClose(ticket);
      }
      else
      {
         ConfirmExecution(cmdId, "REJECTED", 0, "Position not found or not owned by this EA");
         return;
      }
      if(success)
         ConfirmExecution(cmdId, "SUCCESS", ticket, "Position closed in MT5");
      else
         ConfirmExecution(cmdId, "FAILED", ticket, "Close retcode: " + IntegerToString(g_trade.ResultRetcode()));
   }
   else if(StringFind(json, "ORDER_MODIFY") >= 0)
   {
      string cmdId = ExtractString(json, "\"id\":\"", "\"");
      ulong ticket = (ulong)ExtractDouble(json, "\"ticket\":", 0.0);
      double sl = ExtractDouble(json, "\"sl\":", 0.0);
      double tp = ExtractDouble(json, "\"tp\":", 0.0);
      if(ticket <= 0 || !g_pos.SelectByTicket(ticket) || g_pos.Magic() != InpMagicNumber)
      {
         ConfirmExecution(cmdId, "REJECTED", 0, "Position not found or not owned by this EA");
         return;
      }
      if(g_trade.PositionModify(ticket, sl, tp))
         ConfirmExecution(cmdId, "SUCCESS", ticket, "Position modified in MT5");
      else
         ConfirmExecution(cmdId, "FAILED", ticket, "Modify retcode: " + IntegerToString(g_trade.ResultRetcode()));
   }
}

//+------------------------------------------------------------------+
//| Simple JSON field extraction helpers                             |
//+------------------------------------------------------------------+
double ExtractDouble(string text, string key, double defaultVal)
{
   int pos = StringFind(text, key);
   if(pos < 0) return defaultVal;
   pos += StringLen(key);
   string sub = StringSubstr(text, pos, 30);
   int endPos = StringFind(sub, ",");
   if(endPos < 0) endPos = StringFind(sub, "}");
   if(endPos > 0) sub = StringSubstr(sub, 0, endPos);
   return StringToDouble(sub);
}

string ExtractString(string text, string startKey, string endKey)
{
   int pos = StringFind(text, startKey);
   if(pos < 0) return "cmd_0";
   pos += StringLen(startKey);
   string sub = StringSubstr(text, pos);
   int endPos = StringFind(sub, endKey);
   if(endPos > 0) return StringSubstr(sub, 0, endPos);
   return "cmd_0";
}

//+------------------------------------------------------------------+
//| Confirm execution back to Python Bridge                          |
//+------------------------------------------------------------------+
void ConfirmExecution(string cmdId, string status, ulong ticket, string msg)
{
   string json = "{";
   json += "\"command_id\":\"" + cmdId + "\",";
   json += "\"status\":\"" + status + "\",";
   json += "\"ticket\":" + IntegerToString(ticket) + ",";
   json += "\"message\":\"" + msg + "\"";
   json += "}";

   string headers = "Content-Type: application/json\r\n";
   char postData[];
   char result[];
   string resultHeaders;
   if(!JsonToUtf8Bytes(json, postData))
   {
      Print("[AgenticMT5] Could not encode execution confirmation");
      return;
   }
   int res = WebRequest("POST", InpServerUrl + "/api/mt5/confirm", headers, 1000, postData, result, resultHeaders);
   if(res == -1)
      Print("[AgenticMT5] Confirmation delivery failed. Error: ", GetLastError(), " cmd=", cmdId);
}

//+------------------------------------------------------------------+
//| File Pipe Fallback                                               |
//+------------------------------------------------------------------+
void WriteTelemetryToFile(string json)
{
   int fileHandle = FileOpen("agentic_mt5_telemetry.json", FILE_WRITE | FILE_TXT);
   if(fileHandle != INVALID_HANDLE)
   {
      FileWriteString(fileHandle, json);
      FileClose(fileHandle);
   }
}
