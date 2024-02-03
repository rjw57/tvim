import queue
import random
import shutil
import threading
import typing

import tvision as tv
from pynvim import Nvim, attach

from .grid import HIGHLIGHT_ATTR_MAP, Grid, GridView

CMD_DUMP = 200


class GridWindow(tv.TWindow):
    _grid_view: GridView

    def __init__(self, grid: Grid, *args, **kwargs):
        super().__init__(*args, **kwargs)
        extent = self.getExtent()
        extent.grow(-1, -1)
        self._grid_view = GridView(grid, extent)
        self._grid_view.growMode = tv.gfGrowHiX | tv.gfGrowHiY
        self._grid_view.options = tv.ofSelectable | tv.ofFramed
        self.insert(self._grid_view)
        self._grid_view.select()


_SPECIAL_KEYS = {
    tv.kbEnter: "<CR>",
    tv.kbEsc: "<Esc>",
    tv.kbLeft: "<Left>",
    tv.kbRight: "<Right>",
    tv.kbUp: "<Up>",
    tv.kbDown: "<Down>",
    tv.kbBack: "<BS>",
}


class Application(tv.TApplication):
    _grid_map: dict[int, Grid]
    _grids_to_refresh: set[int]

    def __init__(self, nvim: Nvim):
        super().__init__()
        self._nvim = nvim
        self._input_queue = queue.Queue()
        self._grid_map = {}
        self._grids_to_refresh = set()
        self._redraw_set = set()
        self._nvim_err = None
        self._get_grid(1)

    def _get_grid(self, grid_handle: int) -> Grid:
        try:
            return self._grid_map[grid_handle]
        except KeyError:
            grid = Grid(self._nvim, grid_handle)
            self._grid_map[grid_handle] = grid
            r = tv.TRect(0, 0, 85, 28)
            r.move(random.randint(0, 10), random.randint(0, 5))
            w = GridWindow(grid, r, "NeoVim", tv.wnNoNumber)
            self.deskTop.insert(w)
            return grid

    def run(self) -> int:
        self._nvim_thread = threading.Thread(target=self._nvim_loop)
        self._nvim_thread.start()
        try:
            return super().run()
        finally:
            self._nvim.async_call(self._nvim.quit)
            self._nvim.stop_loop()
            self._nvim_thread.join(0.1)

    def idle(self) -> None:
        if self._nvim_err is not None:
            err, self._nvim_err = self._nvim_err, None
            raise RuntimeError(err)

    def _nvim_loop(self):
        self._nvim.run_loop(
            request_cb=self._nvim_request_cb,
            notification_cb=self._nvim_notification_cb,
            setup_cb=self._nvim_setup_cb,
            err_cb=self._nvim_error_cb,
        )

    def _nvim_setup_cb(self) -> None:
        self._nvim.ui_attach(100, 25, rgb=True, ext_linegrid=True)
        self._nvim.command(f"e {__file__}")

    def _nvim_request_cb(self, name: str, args: list[typing.Any]) -> typing.Any:
        print(f"req: n: {name!r}, a: {args!r}")

    def _nvim_error_cb(self, err: str):
        self._nvim_err = err

    def _nvim_notification_cb(self, name: str, args: list[typing.Any]) -> typing.Any:
        if name == "redraw":
            for event in args:
                kind = event[0]
                for event_args in event[1:]:
                    self._nvim_redraw_event(kind, event_args)

    def _nvim_redraw_event(self, kind: str, args: typing.Sequence[typing.Any]):
        if kind == "grid_line":
            grid, row, col_start, cells, wrap = args[:5]
            self._get_grid(grid).grid_line_event(row, col_start, cells, wrap)
            self._grids_to_refresh.add(grid)
        elif kind == "grid_cursor_goto":
            grid, row, column = args[:3]
            self._get_grid(grid).grid_cursor_goto_event(row, column)
            self._grids_to_refresh.add(grid)
        elif kind == "grid_destroy":
            pass  # TODO
        elif kind == "grid_scroll":
            grid, top, bot, left, right, rows, cols = args[:7]
            self._get_grid(grid).grid_scroll(top, bot, left, right, rows, cols)
            self._grids_to_refresh.add(grid)
        elif kind == "grid_clear":
            pass  # TODO
        elif kind == "flush":
            for handle in self._grids_to_refresh:
                self._get_grid(handle).flush_event()
            self._grids_to_refresh.clear()
        elif kind == "default_colors_set":
            rgb_fg, rgb_bg, rgb_sp = args[:3]
            HIGHLIGHT_ATTR_MAP.default_colors_set(rgb_fg, rgb_bg, rgb_sp)
        elif kind == "hl_attr_define":
            id, attr_dict = args[:2]
            HIGHLIGHT_ATTR_MAP.hl_attr_define(id, attr_dict)

    def _dump(self):
        for r in self._get_grid(1)._cells:
            print("".join(c.text for c in r))
        print("xx")

    def handleEvent(self, event: tv.TEvent):
        super().handleEvent(event)
        if event.what == tv.evCommand:
            cmd = event.message.command
            if cmd == CMD_DUMP:
                self._dump()
        elif event.what == tv.evKeyDown:
            txt = None
            if event.keyDown.controlKeyState == tv.kbInsState:
                txt = _SPECIAL_KEYS.get(event.keyDown.keyCode, event.keyDown.getText())
            elif event.keyDown.keyCode >= tv.kbCtrlA and event.keyDown.keyCode <= tv.kbCtrlZ:
                txt = f"<C-{chr(ord('A') + event.keyDown.keyCode - tv.kbCtrlA)}>"
            if txt is not None:
                self._input_queue.put(txt)
                self._nvim.async_call(self._insert)

    def _insert(self):
        while not self._input_queue.empty():
            txt = self._input_queue.get()
            self._nvim.feedkeys(self._nvim.replace_termcodes(txt), "t", False)

    @staticmethod
    def initStatusLine(r: tv.TRect) -> tv.TStatusLine:
        r.a.y = r.b.y - 1
        return tv.TStatusLine(
            r,
            [
                tv.TStatusDef(
                    0,
                    0xFFFF,
                    [
                        tv.TStatusItem("~Alt-X~ Exit", tv.kbAltX, tv.cmQuit),
                        tv.TStatusItem("~Alt-D~ Dump", tv.kbAltD, CMD_DUMP),
                        tv.TStatusItem(None, tv.kbF10, tv.cmMenu),
                    ],
                )
            ],
        )


def main():
    nvim = attach("child", argv=[shutil.which("nvim"), "--embed", "--headless"])
    app = Application(nvim)
    app.run()
