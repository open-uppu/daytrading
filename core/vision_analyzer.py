"""
Multimodal Vision Analyzer for Gold (XAUUSD) Candlestick Charts.
Supports both LLM Vision APIs (Gemini/OpenAI) and an autonomous Computer Vision Heuristic Engine.
"""

import base64
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
import httpx
import pandas as pd

from config import config
from core.indicators import analyze_candlestick_patterns, detect_support_resistance

logger = logging.getLogger("vision_analyzer")


class VisionAnalyzer:
    """Analyzes chart images and extracts price action patterns and visual bias."""
    
    def __init__(self):
        self.gemini_key = config.gemini_api_key
        self.openai_key = config.openai_api_key
        self.ai_base_url = config.ai_base_url
        self.ai_api_key = config.ai_api_key
        self.ai_model = config.ai_model
        self.provider = config.vision_provider
        
    def analyze_chart(
        self,
        chart_image_path: Path,
        df: pd.DataFrame,
        timeframe: str = "M15"
    ) -> Dict[str, Any]:
        """
        Executes multimodal analysis on the given chart image and price DataFrame.
        """
        # Determine provider
        if (self.provider in ["ollama", "minimax", "custom"]) or (self.provider == "auto" and self.ai_api_key):
            try:
                return self._analyze_with_ollama(chart_image_path, timeframe)
            except Exception as e:
                logger.warning(f"Ollama/Minimax vision failed: {e}. Falling back to next provider.")

        if self.provider == "gemini" and self.gemini_key:
            return self._analyze_with_gemini(chart_image_path, timeframe)
        elif self.provider == "openai" and self.openai_key:
            return self._analyze_with_openai(chart_image_path, timeframe)
        elif self.provider == "auto":
            if self.gemini_key:
                try:
                    return self._analyze_with_gemini(chart_image_path, timeframe)
                except Exception as e:
                    logger.warning(f"Gemini vision failed: {e}. Falling back to heuristic vision.")
            elif self.openai_key:
                try:
                    return self._analyze_with_openai(chart_image_path, timeframe)
                except Exception as e:
                    logger.warning(f"OpenAI vision failed: {e}. Falling back to heuristic vision.")
                    
        # Reliable Autonomous Heuristic Vision Fallback
        return self._analyze_heuristically(chart_image_path, df, timeframe)
        
    def _analyze_heuristically(
        self,
        chart_image_path: Path,
        df: pd.DataFrame,
        timeframe: str
    ) -> Dict[str, Any]:
        """
        Deterministic, high-fidelity visual and price action heuristic analysis.
        """
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else None
        
        candle_patterns = analyze_candlestick_patterns(latest, prev)
        sr_dict = detect_support_resistance(df.tail(60))
        
        close_p = float(latest['close'])
        ema_20 = float(latest.get('ema_20', close_p))
        ema_50 = float(latest.get('ema_50', close_p))
        ema_200 = float(latest.get('ema_200', close_p))
        atr = float(latest.get('atr_14', 4.0))
        
        observations: List[str] = []
        score = 0  # -100 (extreme sell) to +100 (extreme buy)
        detected_pattern = "NONE"
        bias = "NEUTRAL"
        
        # 1. EMA Trend Structure
        if close_p > ema_20 > ema_50 > ema_200:
            score += 35
            bias = "BULLISH"
            observations.append(f"Golden EMA stack: Price ({close_p:.2f}) > EMA20 > EMA50 > EMA200")
        elif close_p < ema_20 < ema_50 < ema_200:
            score -= 35
            bias = "BEARISH"
            observations.append(f"Bearish EMA stack: Price ({close_p:.2f}) < EMA20 < EMA50 < EMA200")
        elif close_p > ema_50 and ema_50 > ema_200:
            score += 20
            bias = "MODERATE_BULLISH"
            observations.append(f"Price above EMA50 and EMA200 uptrend")
        elif close_p < ema_50 and ema_50 < ema_200:
            score -= 20
            bias = "MODERATE_BEARISH"
            observations.append(f"Price below EMA50 and EMA200 downtrend")
        else:
            observations.append("Price consolidating between major EMAs (range-bound)")
            
        # 2. Candlestick Geometry & Rejection Patterns
        if candle_patterns["bullish_pin"]:
            score += 30
            detected_pattern = "BULLISH_PIN_BAR_REJECTION"
            observations.append(f"Long lower rejection wick ({candle_patterns['lower_wick_ratio']*100:.0f}%) indicating institutional buying")
        elif candle_patterns["bearish_pin"]:
            score -= 30
            detected_pattern = "BEARISH_PIN_BAR_REJECTION"
            observations.append(f"Long upper rejection wick ({candle_patterns['upper_wick_ratio']*100:.0f}%) indicating supply rejection")
            
        if candle_patterns["bullish_engulfing"]:
            score += 25
            detected_pattern = "BULLISH_ENGULFING"
            observations.append("Bullish engulfing candle confirms strong upward momentum")
        elif candle_patterns["bearish_engulfing"]:
            score -= 25
            detected_pattern = "BEARISH_ENGULFING"
            observations.append("Bearish engulfing candle confirms strong downward momentum")
            
        # 3. Support & Resistance Proximity
        nearest_support = None
        min_supp_dist = float('inf')
        for supp in sr_dict.get("support", []):
            if supp <= close_p:
                dist = close_p - supp
                if dist < min_supp_dist:
                    min_supp_dist = dist
                    nearest_support = supp
                    
        nearest_resistance = None
        min_res_dist = float('inf')
        for res in sr_dict.get("resistance", []):
            if res >= close_p:
                dist = res - close_p
                if dist < min_res_dist:
                    min_res_dist = dist
                    nearest_resistance = res
                    
        # Check bounce off support
        if nearest_support and min_supp_dist <= 1.0 * atr and candle_patterns["is_bullish"]:
            score += 20
            observations.append(f"Valid bounce from Support Zone around {nearest_support:.2f} (within {min_supp_dist:.2f}$)")
            
        # Check rejection at resistance
        if nearest_resistance and min_res_dist <= 1.0 * atr and not candle_patterns["is_bullish"]:
            score -= 20
            observations.append(f"Rejection at Resistance Zone around {nearest_resistance:.2f} (within {min_res_dist:.2f}$)")
            
        # Bound score between -100 and +100
        score = max(-100, min(100, score))
        confidence = abs(score)
        
        if score >= 50:
            bias = "STRONG_BUY" if score >= 75 else "BUY"
        elif score <= -50:
            bias = "STRONG_SELL" if score <= -75 else "SELL"
        else:
            bias = "NEUTRAL_WAIT"
            
        return {
            "engine": "autonomous_heuristic_vision",
            "chart_image_path": str(chart_image_path),
            "timeframe": timeframe,
            "visual_bias": bias,
            "vision_score": score,
            "confidence": confidence,
            "pattern_detected": detected_pattern,
            "candle_geometry": candle_patterns,
            "nearest_support": nearest_support,
            "nearest_resistance": nearest_resistance,
            "observations": observations
        }

    def _analyze_with_gemini(self, chart_image_path: Path, timeframe: str) -> Dict[str, Any]:
        """Calls Gemini Vision API for multimodal chart analysis."""
        with open(chart_image_path, "rb") as f:
            image_bytes = f.read()
        encoded = base64.b64encode(image_bytes).decode("utf-8")
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.gemini_key}"
        prompt = (
            "You are a professional Gold (XAUUSD) intraday day-trader. "
            "Analyze this candlestick chart image for high-probability setups. "
            "Identify: 1) Visual trend, 2) Candlestick patterns, 3) S/R bounce/break, 4) Visual score (-100 to +100). "
            "Respond strictly in JSON with fields: visual_bias (STRONG_BUY, BUY, NEUTRAL_WAIT, SELL, STRONG_SELL), "
            "vision_score (number -100 to 100), confidence (0 to 100), pattern_detected (string), observations (list of strings)."
        )
        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": "image/png", "data": encoded}}
                ]
            }],
            "generationConfig": {"response_mime_type": "application/json"}
        }
        resp = httpx.post(url, json=payload, timeout=20.0)
        resp.raise_for_status()
        data = resp.json()
        raw_text = data['candidates'][0]['content']['parts'][0]['text']
        parsed = json.loads(raw_text)
        parsed["engine"] = "gemini_multimodal_vision"
        parsed["chart_image_path"] = str(chart_image_path)
        return parsed

    def _analyze_with_openai(self, chart_image_path: Path, timeframe: str) -> Dict[str, Any]:
        """Calls OpenAI GPT-4o-mini Vision API."""
        with open(chart_image_path, "rb") as f:
            image_bytes = f.read()
        encoded = base64.b64encode(image_bytes).decode("utf-8")
        
        headers = {
            "Authorization": f"Bearer {self.openai_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "gpt-4o-mini",
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Analyze this Gold XAUUSD chart image. Return strictly JSON: "
                            "visual_bias, vision_score (-100 to 100), confidence (0 to 100), "
                            "pattern_detected, observations."
                        )
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{encoded}"}
                    }
                ]
            }],
            "response_format": {"type": "json_object"}
        }
        resp = httpx.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=20.0)
        resp.raise_for_status()
        data = resp.json()
        raw_text = data['choices'][0]['message']['content']
        parsed = json.loads(raw_text)
        parsed["engine"] = "openai_vision"
        parsed["chart_image_path"] = str(chart_image_path)
        return parsed

    def _analyze_with_ollama(self, chart_image_path: Path, timeframe: str) -> Dict[str, Any]:
        """Calls OpenAI-compatible Ollama / Minimax multimodal vision API."""
        with open(chart_image_path, "rb") as f:
            image_bytes = f.read()
        encoded = base64.b64encode(image_bytes).decode("utf-8")

        headers = {
            "Authorization": f"Bearer {self.ai_api_key}",
            "Content-Type": "application/json"
        }
        prompt = (
            "You are a professional quantitative and technical intraday trader. "
            "Analyze this candlestick chart image for key technical patterns, trend bias, and S/R levels. "
            "Respond strictly in JSON format with fields: "
            "visual_bias (one of STRONG_BUY, BUY, NEUTRAL_WAIT, SELL, STRONG_SELL), "
            "vision_score (integer from -100 to 100 where positive is bullish and negative is bearish), "
            "confidence (integer 0 to 100), "
            "pattern_detected (short string describing the primary pattern), "
            "observations (list of string observations describing key price action)."
        )
        url = f"{self.ai_base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self.ai_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}}
                    ]
                }
            ]
        }
        resp = httpx.post(url, headers=headers, json=payload, timeout=35.0)
        resp.raise_for_status()
        data = resp.json()
        raw_text = data['choices'][0]['message']['content']

        clean_text = raw_text.strip()
        if "```json" in clean_text:
            clean_text = clean_text.split("```json")[1].split("```")[0].strip()
        elif "```" in clean_text:
            clean_text = clean_text.split("```")[1].split("```")[0].strip()

        parsed = json.loads(clean_text)
        
        # Normalize observations to list of strings
        obs = parsed.get("observations", [])
        if isinstance(obs, dict):
            parsed["observations"] = [f"{k}: {v}" for k, v in obs.items()]
        elif isinstance(obs, str):
            parsed["observations"] = [obs]

        # Normalize visual_bias
        bias = str(parsed.get("visual_bias", "NEUTRAL_WAIT")).upper()
        if "STRONG" in bias and "BUY" in bias:
            bias = "STRONG_BUY"
        elif "STRONG" in bias and "SELL" in bias:
            bias = "STRONG_SELL"
        elif "BUY" in bias or "BULL" in bias:
            bias = "BUY"
        elif "SELL" in bias or "BEAR" in bias:
            bias = "SELL"
        else:
            bias = "NEUTRAL_WAIT"
        parsed["visual_bias"] = bias

        parsed["engine"] = f"ollama_vision_{self.ai_model}"
        parsed["chart_image_path"] = str(chart_image_path)
        return parsed

