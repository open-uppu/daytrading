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

//--- Global Objects
CTrade         g_trade;
CPositionInfo  g_pos;
CAccountInfo   g_account;
datetime       g_lastHistorySync  = 0;

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
   
   // Collect Open Positions
   json += "\"open_positions\":[";
   int total = PositionsTotal();
   bool first = true;
   for(int i = 0; i < total; i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0 && g_pos.SelectByTicket(ticket))
      {
         if(g_pos.Symbol() == Symbol() && g_pos.Magic() == InpMagicNumber)
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
            json += "\"profit\":" + DoubleToString(g_pos.Profit(), 2);
            json += "}";
         }
      }
   }
   json += "],";

   // Collect Closed Deals from Today
   json += "\"closed_orders\":[";
   datetime from = TimeCurrent() - 86400;
   HistorySelect(from, TimeCurrent());
   int dealsTotal = HistoryDealsTotal();
   bool firstDeal = true;
   for(int d = dealsTotal - 1; d >= 0 && d >= dealsTotal - 10; d--)
   {
      ulong dealTicket = HistoryDealGetTicket(d);
      if(dealTicket > 0)
      {
         long entryType = HistoryDealGetInteger(dealTicket, DEAL_ENTRY);
         if(entryType == DEAL_ENTRY_OUT) // Deal closed
         {
            if(!firstDeal) json += ",";
            firstDeal = false;
            double dealProfit = HistoryDealGetDouble(dealTicket, DEAL_PROFIT);
            json += "{";
            json += "\"ticket\":" + IntegerToString(dealTicket) + ",";
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
   StringToCharArray(json, postData, 0, WHOLE_ARRAY, CP_UTF8);
   
   int res = WebRequest("POST", InpServerUrl + "/api/mt5/telemetry", headers, 1000, postData, result, resultHeaders);
   if(res == -1)
   {
      int err = GetLastError();
      if(err == 4060 && InpUseFilePipe) // WebRequest restricted -> use file pipe
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
      bool isBuy = (StringFind(json, "\"type\":\"BUY\"") >= 0);
      double volume = ExtractDouble(json, "\"volume\":", 0.01);
      double sl = ExtractDouble(json, "\"sl\":", 0.0);
      double tp = ExtractDouble(json, "\"tp\":", 0.0);
      string cmdId = ExtractString(json, "\"id\":\"", "\"");
      
      bool success = false;
      if(isBuy)
      {
         success = g_trade.Buy(volume, Symbol(), 0, sl, tp, "AgenticMT5");
      }
      else
      {
         success = g_trade.Sell(volume, Symbol(), 0, sl, tp, "AgenticMT5");
      }
      
      if(success)
      {
         ulong orderTicket = g_trade.ResultOrder();
         Print("[AgenticMT5] Order executed successfully. Ticket: #", orderTicket);
         ConfirmExecution(cmdId, "SUCCESS", orderTicket, "Executed in MT5");
      }
      else
      {
         uint retcode = g_trade.ResultRetcode();
         Print("[AgenticMT5] Order execution failed. Retcode: ", retcode);
         ConfirmExecution(cmdId, "FAILED", 0, "Retcode: " + IntegerToString(retcode));
      }
   }
   else if(StringFind(json, "ORDER_CLOSE") >= 0)
   {
      ulong ticket = (ulong)ExtractDouble(json, "\"ticket\":", 0.0);
      if(ticket > 0)
      {
         g_trade.PositionClose(ticket);
      }
      else
      {
         // Close all expert positions
         for(int i = PositionsTotal() - 1; i >= 0; i--)
         {
            ulong t = PositionGetTicket(i);
            if(t > 0 && g_pos.SelectByTicket(t))
            {
               if(g_pos.Symbol() == Symbol() && g_pos.Magic() == InpMagicNumber)
               {
                  g_trade.PositionClose(t);
               }
            }
         }
      }
   }
   else if(StringFind(json, "ORDER_MODIFY") >= 0)
   {
      ulong ticket = (ulong)ExtractDouble(json, "\"ticket\":", 0.0);
      double sl = ExtractDouble(json, "\"sl\":", 0.0);
      double tp = ExtractDouble(json, "\"tp\":", 0.0);
      if(ticket > 0)
      {
         g_trade.PositionModify(ticket, sl, tp);
      }
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
   StringToCharArray(json, postData, 0, WHOLE_ARRAY, CP_UTF8);
   WebRequest("POST", InpServerUrl + "/api/mt5/confirm", headers, 1000, postData, result, resultHeaders);
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
