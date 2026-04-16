# -*- coding: utf-8 -*-

"""
# Author: JB Fiche (from original F.Barho)
# Created: 2026-04-16
# This file contains the code for the ROI manager GUI.

qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
"""

from qtpy import QtCore, QtWidgets

from qudi.core.connector import Connector
from qudi.core.module import GuiBase


class RoiMainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ROI Manager Dummy")

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)

        layout = QtWidgets.QVBoxLayout(central)

        self.position_label = QtWidgets.QLabel("Stage position: x=0, y=0, z=0")
        layout.addWidget(self.position_label)

        self.roi_list = QtWidgets.QListWidget()
        layout.addWidget(self.roi_list)

        button_row = QtWidgets.QHBoxLayout()
        layout.addLayout(button_row)

        self.add_button = QtWidgets.QPushButton("Add ROI from current position")
        self.goto_button = QtWidgets.QPushButton("Go to selected ROI")
        self.refresh_button = QtWidgets.QPushButton("Refresh position")

        button_row.addWidget(self.add_button)
        button_row.addWidget(self.goto_button)
        button_row.addWidget(self.refresh_button)


class RoiGui(GuiBase):
    roi_logic = Connector(name="roi_logic")

    def on_activate(self):
        self._logic = self.roi_logic()
        self._mw = RoiMainWindow()

        self._mw.add_button.clicked.connect(self._add_roi_from_position)
        self._mw.goto_button.clicked.connect(self._goto_selected_roi)
        self._mw.refresh_button.clicked.connect(self._refresh_position)

        self._logic.sigRoiListChanged.connect(self._update_roi_list)
        self._logic.sigActiveRoiChanged.connect(self._update_active_roi)
        self._logic.sigStageMoved.connect(self._update_position_label)

        self._update_roi_list(list(self._logic.roi_list))
        self._update_active_roi(int(self._logic.active_roi))
        self._refresh_position()

        self._restore_window_geometry(self._mw)

    def on_deactivate(self):
        self._save_window_geometry(self._mw)

        try:
            self._logic.sigRoiListChanged.disconnect(self._update_roi_list)
            self._logic.sigActiveRoiChanged.disconnect(self._update_active_roi)
            self._logic.sigStageMoved.disconnect(self._update_position_label)
        except Exception:
            pass

        self._mw.close()

    def show(self):
        self._mw.show()
        self._mw.raise_()
        self._mw.activateWindow()

    @QtCore.Slot()
    def _refresh_position(self):
        pos = self._logic.get_stage_position()
        self._update_position_label(pos)

    @QtCore.Slot()
    def _add_roi_from_position(self):
        pos = self._logic.get_stage_position()
        index = len(self._logic.roi_list) + 1
        name = f"ROI_{index:03d}"
        self._logic.add_roi(name=name, x=pos["x"], y=pos["y"], z=pos["z"])

    @QtCore.Slot()
    def _goto_selected_roi(self):
        row = self._mw.roi_list.currentRow()
        if row >= 0:
            self._logic.move_stage_to_roi(row)

    @QtCore.Slot(list)
    def _update_roi_list(self, rois):
        self._mw.roi_list.blockSignals(True)
        self._mw.roi_list.clear()

        for roi in rois:
            text = (
                f'{roi["name"]}  '
                f'(x={roi["x"]:.2f}, y={roi["y"]:.2f}, z={roi["z"]:.2f})'
            )
            self._mw.roi_list.addItem(text)

        self._mw.roi_list.blockSignals(False)

    @QtCore.Slot(int)
    def _update_active_roi(self, index):
        if 0 <= index < self._mw.roi_list.count():
            self._mw.roi_list.setCurrentRow(index)

    @QtCore.Slot(dict)
    def _update_position_label(self, pos):
        self._mw.position_label.setText(
            f'Stage position: x={pos["x"]:.2f}, y={pos["y"]:.2f}, z={pos["z"]:.2f}'
        )