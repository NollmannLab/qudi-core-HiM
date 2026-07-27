# -*- coding: utf-8 -*-
"""
Interface for generic pipetting robot controlling.

The interface intentionally exposes only high-level methods associated to the pipetting robot.
Lower lever methods are actually inherited during instantiation by calling the MultiAxisStageInterface/
"""

from abc import abstractmethod
from typing import Dict, Optional, Tuple

from qudi.interface.multi_axis_stage_interface import MultiAxisStageInterface


class PipettingRobotInterface(MultiAxisStageInterface):
    """Interface for a pipetting robot built on a multi-axis stage."""

    @abstractmethod
    def get_robot_parameters(self) -> Dict:
        """Return robot configuration needed by positioning logic."""
        pass

    @abstractmethod
    def get_grid_properties(self) -> Dict:
        """Return the configured probe-grid properties."""
        pass

    @abstractmethod
    def map_probe_number_to_grid_coordinates(
        self,
    ) -> Dict[int, Tuple[int, int]]:
        """Map probe numbers to discrete grid coordinates."""
        pass

    @abstractmethod
    def map_xy_position_to_probe_number(
        self,
        probe_grid_dict: Dict[int, Tuple[int, int]],
        origin: Tuple[float, float, float],
    ) -> Dict[Tuple[float, float], int]:
        """Map physical in-plane coordinates to probe numbers."""
        pass

    @abstractmethod
    def park(self) -> bool:
        """Move the robot to its configured parking position."""
        pass