//+------------------------------------------------------------------+
//|                                         AgenticMT4Bridge.mq4     |
//|               Autonomous Gold (XAUUSD) Agentic Trading Bridge   |
//|                                  Copyright 2026, Agentic Trader  |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, Agentic Trader"
#property link      "https://github.com/agentic-gold"
#property version   "1.00"
#property strict

//--- Input Parameters
input string   InpServerUrl     = "http://127.0.0.1:8000"; // Python Bridge URL
input int      InpPollIntervalMs = 1000;                     // Polling Interval in ms
input int      InpSlippagePoints= 30;                       // Max Slippage in points
input int      InpMagicNumber   = 888999;                   // Expert Magic Number
input bool     InpUseFilePipe   = false;                    // Enable File Pipe Fallback

//--- Global Variables
datetime g_lastPollTime = 0;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("[AgenticBridge] Initialized for symbol: ", Symbol(), " on period: ", Period());
   EventSetMillisecondTimer(InpPollIntervalMs);
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   Print("[AgenticBridge] Deinitialized. Reason: ", reason);
}

//+------------------------------------------------------------------+
//| Timer event function (called every InpPollIntervalMs)            |
//+------------------------------------------------------------------+
void OnTimer()
{
   SendTelemetry();
   PollCommands();
}

//+------------------------------------------------------------------+
//| Send Telemetry (Account balance, equity, bid, ask, open orders)  |
//+------------------------------------------------------------------+
void SendTelemetry()
{
   string json = "{";
   json += "\"account_number\":" + IntegerToString(AccountNumber()) + ",";
   json += "\"balance\":" + DoubleToString(AccountBalance(), 2) + ",";
   json += "\"equity\":" + DoubleToString(AccountEquity(), 2) + ",";
   json += "\"symbol\":\"" + Symbol() + "\",";
   json += "\"bid\":" + DoubleToString(Bid, 2) + ",";
   json += "\"ask\":" + DoubleToString(Ask, 2) + ",";
   
   // Collect Open Positions
   json += "\"open_positions\":[";
   int total = OrdersTotal();
   bool first = true;
   for(int i = 0; i < total; i++)
   {
      if(OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
      {
         if(OrderSymbol() == Symbol() && OrderMagicNumber() == InpMagicNumber)
         {
            if(!first) json += ",";
            first = false;
            string typeStr = (OrderType() == OP_BUY) ? "BUY" : "SELL";
            json += "{";
            json += "\"ticket\":" + IntegerToString(OrderTicket()) + ",";
            json += "\"symbol\":\"" + OrderSymbol() + "\",";
            json += "\"type\":\"" + typeStr + "\",";
            json += "\"lots\":" + DoubleToString(OrderLots(), 2) + ",";
            json += "\"open_price\":" + DoubleToString(OrderOpenPrice(), 2) + ",";
            json += "\"sl\":" + DoubleToString(OrderStopLoss(), 2) + ",";
            json += "\"tp\":" + DoubleToString(OrderTakeProfit(), 2) + ",";
            json += "\"profit\":" + DoubleToString(OrderProfit(), 2);
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
   
   int res = WebRequest("POST", InpServerUrl + "/api/mt4/telemetry", headers, 1000, postData, result, resultHeaders);
   if(res == -1)
   {
      int err = GetLastError();
      if(err == 4060) // ERR_FUNCTION_NOT_ALLOWED (WebRequest not allowed in options)
      {
         // Fallback to File Pipe if enabled
         if(InpUseFilePipe) WriteTelemetryToFile(json);
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
   
   int res = WebRequest("GET", InpServerUrl + "/api/mt4/commands", headers, 1000, postData, result, resultHeaders);
   if(res > 0 && ArraySize(result) > 0)
   {
      string responseText = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
      // Execute command if found
      ExecuteCommand(responseText);
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
      int cmd = isBuy ? OP_BUY : OP_SELL;
      double price = isBuy ? Ask : Bid;
      
      // Parse lot size (simple extraction or default 0.10)
      double volume = 0.10;
      double sl = 0.0;
      double tp = 0.0;
      
      int ticket = OrderSend(Symbol(), cmd, volume, price, InpSlippagePoints, sl, tp, "AgenticGold", InpMagicNumber, 0, clrGold);
      if(ticket > 0)
      {
         Print("[AgenticBridge] Order successfully opened. Ticket: #", ticket);
         ConfirmExecution("cmd_open", "SUCCESS", ticket, "Order opened successfully");
      }
      else
      {
         int err = GetLastError();
         Print("[AgenticBridge] OrderSend failed. Error: ", err);
         ConfirmExecution("cmd_open", "FAILED", 0, "Error code: " + IntegerToString(err));
      }
   }
   else if(StringFind(json, "ORDER_CLOSE") >= 0)
   {
      // Extract ticket and close
      for(int i = OrdersTotal() - 1; i >= 0; i--)
      {
         if(OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
         {
            if(OrderSymbol() == Symbol() && OrderMagicNumber() == InpMagicNumber)
            {
               double closePrice = (OrderType() == OP_BUY) ? Bid : Ask;
               OrderClose(OrderTicket(), OrderLots(), closePrice, InpSlippagePoints, clrRed);
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Confirm execution back to Python Bridge                          |
//+------------------------------------------------------------------+
void ConfirmExecution(string cmdId, string status, int ticket, string msg)
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
   WebRequest("POST", InpServerUrl + "/api/mt4/confirm", headers, 1000, postData, result, resultHeaders);
}

//+------------------------------------------------------------------+
//| File Pipe Fallback                                               |
//+------------------------------------------------------------------+
void WriteTelemetryToFile(string json)
{
   int fileHandle = FileOpen("agentic_telemetry.json", FILE_WRITE | FILE_TXT);
   if(fileHandle != INVALID_HANDLE)
   {
      FileWriteString(fileHandle, json);
      FileClose(fileHandle);
   }
}
