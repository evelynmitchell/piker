# piker: trading gear for hackers
# Copyright (C) Tyler Goodlet (in stewardship for piker0)

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
Position info and display

"""
from typing import Optional, Callable
from functools import partial
from math import floor

from pyqtgraph import functions as fn
from pydantic import BaseModel
from PyQt5 import QtGui, QtWidgets
from PyQt5.QtCore import QPointF
from PyQt5.QtGui import QGraphicsPathItem

from ._annotate import mk_marker_path
from ._anchors import (
    marker_right_points,
    gpath_pin,
    # keep_marker_in_view,
)
from ..clearing._messages import BrokerdPosition, Status
from ..data._source import Symbol
from ._label import Label
from ._lines import LevelLine, level_line
from ._style import _font


class Position(BaseModel):
    '''Basic pp (personal position) data representation with attached
    fills history.

    This type should be IPC wire ready?

    '''
    symbol: Symbol

    # last size and avg entry price
    size: float
    avg_price: float  # TODO: contextual pricing

    # ordered record of known constituent trade messages
    fills: list[Status] = []


class LevelMarker(QGraphicsPathItem):
    '''An arrow marker path graphich which redraws itself
    to the specified view coordinate level on each paint cycle.

    '''
    def __init__(
        self,
        chart: 'ChartPlotWidget',  # noqa
        style: str,
        get_level: Callable[..., float],
        size: float = 20,
        keep_in_view: bool = True,

    ) -> None:

        # get polygon and scale
        super().__init__()
        self.scale(size, size)

        # interally generates path
        self._style = None
        self.style = style

        self.chart = chart

        self.get_level = get_level
        self.scene_x = lambda: marker_right_points(chart)[1]
        self.level: float = 0
        self.keep_in_view = keep_in_view

        assert self.path_br

    @property
    def style(self) -> str:
        return self._style

    @style.setter
    def style(self, value: str) -> None:
        if self._style != value:
            polygon = mk_marker_path(value)
            self.setPath(polygon)
            self._style = value

            # get the path for the opaque path **without** weird
            # surrounding margin
            self.path_br = self.mapToScene(
                self.path()
            ).boundingRect()


    def delete(self) -> None:
        self.scene().removeItem(self)

    @property
    def h(self) -> float:
        return self.path_br.height()

    @property
    def w(self) -> float:
        return self.path_br.width()

    def position_in_view(
        self,
        # level: float,

    ) -> None:
        '''Show a pp off-screen indicator for a level label.

        This is like in fps games where you have a gps "nav" indicator
        but your teammate is outside the range of view, except in 2D, on
        the y-dimension.

        '''
        level = self.get_level()

        view = self.chart.getViewBox()
        vr = view.state['viewRange']
        ymn, ymx = vr[1]

        # _, marker_right, _ = marker_right_points(line._chart)
        x = self.scene_x()

        if level > ymx:  # pin to top of view
            self.setPos(
                QPointF(
                    x,
                    self.h/3,
                )
            )

        elif level < ymn:  # pin to bottom of view

            self.setPos(
                QPointF(
                    x,
                    view.height() - 4/3*self.h,
                )
            )

        else:
            # pp line is viewable so show marker normally
            self.setPos(
                x,
                self.chart.view.mapFromView(
                    QPointF(0, self.get_level())
                ).y()
            )

        # marker = line._marker
        if getattr(self, 'label', None):
            label = self.label

            # re-anchor label (i.e. trigger call of ``arrow_tr()`` from above
            label.update()

    def paint(
        self,

        p: QtGui.QPainter,
        opt: QtWidgets.QStyleOptionGraphicsItem,
        w: QtWidgets.QWidget

    ) -> None:
        '''Core paint which we override to always update
        our marker position in scene coordinates from a
        view cooridnate "level".

        '''
        if self.keep_in_view:
            self.position_in_view()

        else:  # just place at desired level even if not in view
            self.setPos(
                self.scene_x(),
                self.mapToScene(QPointF(0, self.get_level())).y()
            )

        return super().paint(p, opt, w)


class PositionTracker:
    '''Track and display a real-time position for a single symbol
    on a chart.

    '''
    # inputs
    chart: 'ChartPlotWidget'  # noqa

    # allocated
    info: Position
    pp_label: Label
    size_label: Label
    line: Optional[LevelLine] = None

    _color: str = 'default_light'

    def __init__(
        self,
        chart: 'ChartPlotWidget',  # noqa

    ) -> None:

        self.chart = chart
        self.info = Position(
            symbol=chart.linked.symbol,
            size=0,
            avg_price=0,
        )

        self.pp_label = None

        view = chart.getViewBox()

        # create placeholder 'up' level arrow
        self._level_marker = None
        self._level_marker = self.level_marker(size=1)

        # literally 'pp' label that's always in view
        self.pp_label = pp_label = Label(
            view=view,
            fmt_str='pp',
            color=self._color,
            update_on_range_change=False,
        )

        self._level_marker.label = pp_label

        pp_label.scene_anchor = partial(
            gpath_pin,
            gpath=self._level_marker,
            label=pp_label,
        )
        pp_label.render()
        pp_label.show()

        self.size_label = size_label = Label(
            view=view,
            color=self._color,

            # this is "static" label
            # update_on_range_change=False,
            fmt_str='\n'.join((
                'x{entry_size}',
            )),

            fields={
                'entry_size': 0,
            },
        )
        size_label.render()
        # size_label.scene_anchor = self.align_to_marker

        size_label.scene_anchor = lambda: (
            self.pp_label.txt.pos() + QPointF(self.pp_label.w, 0)
        )
        size_label.hide()

        # TODO: if we want to show more position-y info?
        #     fmt_str='\n'.join((
        #         # '{entry_size}x ',
        #         '{percent_pnl} % PnL',
        #         # '{percent_of_port}% of port',
        #         '${base_unit_value}',
        #     )),

        #     fields={
        #         # 'entry_size': 0,
        #         'percent_pnl': 0,
        #         'percent_of_port': 2,
        #         'base_unit_value': '1k',
        #     },
        # )

    def update(
        self,
        msg: BrokerdPosition,

    ) -> None:
        '''Update graphics and data from average price and size.

        '''
        avg_price, size = msg['avg_price'], msg['size']
        # info updates
        self.info.avg_price = avg_price
        self.info.size = size

        self.update_line(avg_price, size)

        # label updates
        self.size_label.fields['entry_size'] = size
        self.size_label.render()

        if size == 0:
            self.hide()

        else:
            self._level_marker.level = avg_price
            self._level_marker.update()  # trigger paint
            self.show()

            # self.pp_label.show()
            # self._level_marker.show()

    def level(self) -> float:
        if self.line:
            return self.line.value()
        else:
            return 0

    def show(self) -> None:
        if self.info.size:
            self.line.show()
            self._level_marker.show()
            self.pp_label.show()
            self.size_label.show()

    def hide(self) -> None:
        self.pp_label.hide()
        self._level_marker.hide()
        self.size_label.hide()
        if self.line:
            self.line.hide()

    def hide_info(self) -> None:
        '''Hide details of position.

        '''
        # TODO: add remove status bar widgets here
        self.size_label.hide()

    def level_marker(
        self,
        size: float,

    ) -> QGraphicsPathItem:

        if self._level_marker:
            self._level_marker.delete()

        # arrow marker
        # scale marker size with dpi-aware font size
        font_size = _font.font.pixelSize()

        # scale marker size with dpi-aware font size
        arrow_size = floor(1.375 * font_size)

        if size > 0:
            style = '|<'
            direction = 'up'

        elif size < 0:
            style = '>|'
            direction = 'down'

        arrow = LevelMarker(
            chart=self.chart,
            style=style,
            get_level=self.level,
            size=arrow_size,
        )
        # _, marker_right, _ = marker_right_points(self.chart)
        # arrow.scene_x = marker_right

        # monkey-cache height for sizing on pp nav-hub
        # arrow._height = path_br.height()
        # arrow._width = path_br.width()
        arrow._direction = direction

        self.chart.getViewBox().scene().addItem(arrow)
        arrow.show()

        # arrow.label = self.pp_label

        # inside ``LevelLine.pain()`` this is updates...
        # we need a better way to have the label updated as frequenty
        # as every paint call? Maybe use a better slot then the range
        # change?
        # self._level_marker.label = self.pp_label

        return arrow

    def position_line(
        self,

        size: float,
        level: float,

        orient_v: str = 'bottom',

    ) -> LevelLine:
        '''Convenience routine to add a line graphic representing an order
        execution submitted to the EMS via the chart's "order mode".

        '''
        self.line = line = level_line(
            self.chart,
            level,
            color=self._color,
            add_label=False,
            hl_on_hover=False,
            movable=False,
            hide_xhair_on_hover=False,
            use_marker_margin=True,
            only_show_markers_on_hover=False,
            always_show_labels=True,
        )

        if size > 0:
            style = '|<'
        elif size < 0:
            style = '>|'

        marker = self._level_marker
        marker.style = style

        # set marker color to same as line
        marker.setPen(line.currentPen)
        marker.setBrush(fn.mkBrush(line.currentPen.color()))
        marker.level = level
        marker.update()
        marker.show()

        # show position marker on view "edge" when out of view
        vb = line.getViewBox()
        vb.sigRangeChanged.connect(marker.position_in_view)

        line.set_level(level)

        return line

    # order line endpoint anchor
    def align_to_marker(self) -> QPointF:

        pp_line = self.line
        if pp_line:

            # line_ep = pp_line.scene_endpoint()
            # print(line_ep)

            # y_level_scene = line_ep.y()
            # pp_y = pp_label.txt.pos().y()

            # if y_level_scene > pp_y:
            #     y_level_scene = pp_y

            # elif y_level_scene
            mkr_pos = self._level_marker.pos()

            left_of_mkr = QPointF(
                # line_ep.x() - self.size_label.w,
                mkr_pos.x() - self.size_label.w,
                mkr_pos.y(),
                # self._level_marker
                # max(0, y_level_scene),
                # min(
                #     pp_label.txt.pos().y()
                # ),
            )
            return left_of_mkr

            # return QPointF(

            #     marker_right_points(chart)[2] - pp_label.w ,
            #     view.height() - pp_label.h,
            #     # br.x() - pp_label.w,
            #     # br.y(),
            # )

        else:
            # pp = _lines._pp_label.txt
            # scene_rect = pp.mapToScene(pp.boundingRect()).boundingRect()
            # br = scene_rect.bottomRight()

            return QPointF(0, 0)

    def update_line(
        self,

        price: float,
        size: float,

    ) -> None:
        '''Update personal position level line.

        '''
        # do line update
        line = self.line

        if line is None and size:

            # create and show a pp line
            line = self.line = self.position_line(
                level=price,
                size=size,
            )
            line.show()

        elif line:

            if size != 0.0:
                line.set_level(price)
                self._level_marker.level = price
                self._level_marker.update()
                # line.update_labels({'size': size})
                line.show()

            else:
                # remove pp line from view
                line.delete()
                self.line = None
