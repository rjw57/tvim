import collections
import weakref
from typing import Any, NamedTuple, Optional, Sequence

import numpy as np
import tvision as tv
from pynvim import Nvim


class HighlightAttrMap:
    _attr_map: dict[int, tv.TColorAttr]
    _default_attr: tv.TColorAttr
    _attr_dict_map: dict[int, dict[str, Any]]
    _default_attr_dict: dict[str, Any]
    _cache_dirty: bool

    def __init__(self):
        self._default_attr_dict = {}
        self._default_attr = self._dict_to_tattrpair(self._default_attr_dict)
        self._attr_map = {}
        self._attr_dict_map = {}
        self._cache_dirty = False

    def default_colors_set(self, rgb_fg: str, rgb_bg: str, rgb_sp: str):
        self._default_attr_dict.update(
            {"foreground": rgb_fg, "background": rgb_bg, "special": rgb_sp}
        )
        self._cache_dirty = True

    def hl_attr_define(self, id: int, attr_dict: dict[str, Any]):
        self._attr_dict_map[id] = attr_dict
        self._cache_dirty = True

    def _refresh_cache(self):
        self._default_attr = self._dict_to_tattrpair(self._default_attr_dict)
        for hl_id, attr_dict in self._attr_dict_map.items():
            self._attr_map[hl_id] = self._dict_to_tattrpair(
                collections.ChainMap(attr_dict, self._default_attr_dict)
            )
        self._cache_dirty = False

    def __getitem__(self, id: int):
        if self._cache_dirty:
            self._refresh_cache()
        try:
            return self._attr_map[id]
        except KeyError:
            return self._default_attr

    @staticmethod
    def _dict_to_tattrpair(attr_dict: dict[str, Any]) -> tv.TColorAttr:
        foreground = attr_dict.get("foreground", 0xFFFFFF)
        background = attr_dict.get("background", 0x000000)
        style = 0
        if attr_dict.get("reverse", False):
            style |= tv.slReverse
        if attr_dict.get("bold", False):
            style |= tv.slBold
        if attr_dict.get("underline", False):
            style |= tv.slUnderline
        if attr_dict.get("italic", False):
            style |= tv.slItalic
        if attr_dict.get("strikethrough", False):
            style |= tv.slStrike
        return tv.TColorAttr(
            tv.TColorDesired(
                tv.TColorRGB(
                    (foreground >> 16) & 0xFF, (foreground >> 8) & 0xFF, foreground & 0xFF
                )
            ),
            tv.TColorDesired(
                tv.TColorRGB(
                    (background >> 16) & 0xFF, (background >> 8) & 0xFF, background & 0xFF
                )
            ),
            style,
        )


class Cell(NamedTuple):
    text: str
    highlight_id: Optional[int]


class Grid:
    _handle: int
    _nvim: Nvim
    _cells: np.ndarray[Cell]
    _views: set["GridView"]
    _cursor: tv.TPoint

    def __init__(self, nvim: Nvim, handle: int, width: int = 80, height: int = 25):
        self._handle = handle
        self._nvim = nvim
        self._cells = np.empty((height, width), dtype=object)
        self._cells.fill(Cell(text=" ", highlight_id=None))
        self._views = weakref.WeakSet()
        self._cursor = tv.TPoint()
        self._cursor.x = self._cursor.y = 0

    @property
    def handle(self) -> int:
        return self._handle

    def _register_grid_view(self, view: "GridView"):
        self._views.add(view)

    def resize(self, width: int, height: int):
        np.resize(self._cells, (height, width))

    def grid_line_event(self, row: int, col_start: int, cells: Sequence[Any], wrap: bool):
        x = col_start
        highlight_id = None
        for cell_record in cells:
            text = cell_record[0]
            if len(cell_record) > 1:
                highlight_id = cell_record[1]
            repeat = cell_record[2] if len(cell_record) > 2 else 1
            self._cells[row, x : x + repeat].fill(Cell(text=text, highlight_id=highlight_id))
            x += repeat

    def grid_cursor_goto_event(self, row: int, column: int):
        self._cursor.x = column
        self._cursor.y = row

    def grid_scroll(self, top: int, bot: int, left: int, right: int, rows: int, cols: int):
        assert cols == 0
        self._cells[top:bot, left:right] = np.roll(self._cells[top:bot, left:right], -rows, 0)

    def flush_event(self):
        for v in self._views:
            v.drawView()


class GridView(tv.TView):
    def __init__(self, grid: Grid, bounds: tv.TRect):
        super().__init__(bounds)
        self._grid = grid
        self._grid._register_grid_view(self)
        self.showCursor()

    def draw(self):
        self.setCursor(self._grid._cursor.x, self._grid._cursor.y)
        cells = self._grid._cells
        buf = tv.TDrawBuffer()
        for row_idx, row in enumerate(cells):
            for indent, cell in enumerate(row):
                attr = HIGHLIGHT_ATTR_MAP[cell.highlight_id]
                buf.moveStr(indent, cell.text, attr)
            self.writeBuf(0, row_idx, cells.shape[1], 1, buf)


HIGHLIGHT_ATTR_MAP = HighlightAttrMap()
