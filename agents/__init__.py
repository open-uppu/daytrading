"""
Specialist Agents Package for Multi-Asset Autonomous Trading.
"""

from agents.base_agent import BaseSpecialistAgent
from agents.gold_agent import GoldSpecialistAgent
from agents.btc_agent import BtcSpecialistAgent
from agents.eth_agent import EthSpecialistAgent
from agents.squad_manager import SquadManager

__all__ = [
    "BaseSpecialistAgent",
    "GoldSpecialistAgent",
    "BtcSpecialistAgent",
    "EthSpecialistAgent",
    "SquadManager"
]
