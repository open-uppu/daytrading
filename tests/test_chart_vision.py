"""
Unit tests for chart generator and vision analysis.
"""

import pytest
from pathlib import Path
import pandas as pd
from core.chart_generator import generate_candlestick_chart
from core.vision_analyzer import VisionAnalyzer
from core.confluence import ConfluenceEngine
from tests.test_indicators import create_sample_ohlcv


def test_chart_generation(tmp_path):
    df = create_sample_ohlcv(50)
    save_path = tmp_path / "test_chart.png"
    result_path = generate_candlestick_chart(df, timeframe="M15", symbol="XAUUSD", save_path=save_path)
    
    assert result_path.exists()
    assert result_path.stat().st_size > 1000  # Non-empty image


def test_vision_analyzer_and_confluence(tmp_path):
    df = create_sample_ohlcv(60)
    chart_path = tmp_path / "test_chart_vision.png"
    generate_candlestick_chart(df, timeframe="M15", symbol="XAUUSD", save_path=chart_path)
    
    analyzer = VisionAnalyzer()
    analyzer.provider = "heuristic"  # Force heuristic test
    vision_result = analyzer.analyze_chart(chart_path, df, timeframe="M15")
    
    assert "visual_bias" in vision_result
    assert "vision_score" in vision_result
    assert "confidence" in vision_result
    
    confluence = ConfluenceEngine(threshold=70.0)
    decision = confluence.evaluate(df, vision_result)
    
    assert "action" in decision
    assert decision["action"] in ["BUY", "SELL", "HOLD"]
    assert "confluence_score" in decision
