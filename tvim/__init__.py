import collections
import queue
import shutil
import threading
import typing

import tvision as tv
from pynvim import Nvim, attach

CMD_DUMP = 200

HL_GROUPS = {}
DEFAULT_HL_ATTR_DICT = {}
HL_ATTR_DICTS = {}
HL_ATTRS = {}


def attr_dict_to_tcolorattr(attr_dict: dict[str, typing.Any]):
    foreground = attr_dict.get("foreground", 0xFFFFFF)
    background = attr_dict.get("background", 0xFFFFFF)
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
            tv.TColorRGB((foreground >> 16) & 0xFF, (foreground >> 8) & 0xFF, foreground & 0xFF)
        ),
        tv.TColorDesired(
            tv.TColorRGB((background >> 16) & 0xFF, (background >> 8) & 0xFF, background & 0xFF)
        ),
        style,
    )


class GridSurface(tv.TDrawSurface):
    _cols: int
    _rows: int

    def __init__(self):
        super().__init__()
        self._resize(80, 25)

    @property
    def size(self):
        pt = tv.TPoint()
        pt.x, pt.y = self._cols, self._rows
        return pt

    def __setitem__(self, pos: tuple[int, int], cell: tv.TScreenCell):
        x, y = pos
        if x < 0 or x >= self._cols or y < 0 or y >= self._rows:
            raise IndexError("Access out of bounds")
        self.at(y, x).assign(cell)

    def __getitem__(self, pos: tuple[int, int]) -> tv.TScreenCell:
        x, y = pos
        if x < 0 or x >= self._cols or y < 0 or y >= self._rows:
            raise IndexError("Access out of bounds")
        return self.at(y, x)

    def _resize(self, cols: int, rows: int):
        self._cols = cols
        self._rows = rows
        self.resize(self.size)

    def process_grid_event(self, kind: str, args: list[typing.Any]) -> bool:
        if kind == "grid_resize":
            w, h = args
            self._resize(w, h)
        elif kind == "grid_line":
            row, col_start, cells, wrap = args
            x, y = col_start, row
            attr = HL_ATTRS[None]
            for c in cells:
                r = [" ", None, 1]
                r[: len(c)] = c
                txt, hl_id, repeat = r
                if hl_id is not None:
                    attr = HL_ATTRS.get(hl_id, HL_ATTRS[None])
                for _ in range(repeat):
                    cell = self[x, y]
                    cell._ch.moveStr(txt)
                    cell.attr.assign(attr)
                    x += 1
        elif kind == "grid_clear":
            for y in range(self._rows):
                for x in range(self._cols):
                    cell = self[x, y]
                    cell._ch.moveStr(" ")
                    cell.attr.assign(HL_ATTRS[None])
        elif kind == "grid_scroll":
            top, bot, left, right, rows, cols = args
            assert cols == 0
            rng = range(top, bot) if rows > 0 else reversed(range(top, bot))
            for dr in rng:
                sr = dr + rows
                if sr >= 0 and sr < self._rows:
                    for x in range(left, right):
                        self[x, dr] = self[x, sr]
        else:
            return False

        return True


class GridView(tv.TSurfaceView):
    def __init__(self, bounds: tv.TRect, *args, **kwargs):
        self._surface = GridSurface()
        super().__init__(bounds, self._surface, *args, **kwargs)
        self.options |= tv.ofSelectable
        self.showCursor()

    def redraw_event(self, kind: str, args: list[typing.Any]) -> bool:
        if self._surface.process_grid_event(kind, args):
            return True
        elif kind == "grid_cursor_goto":
            cy, cx = args
            self.setCursor(cx, cy)
        else:
            return False
        return True


class DemoWindow(tv.TWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        bounds = self.getExtent()
        self.grid = self._make_grid(bounds)
        self.insert(self.grid)
        self.grid.select()

    def _make_grid(self, bounds: tv.TRect):
        bounds.grow(-1, -1)
        return GridView(bounds)


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
    def __init__(self, nvim: Nvim):
        super().__init__()
        self._nvim = nvim
        self._input_queue = queue.Queue()
        self._grid_map = {}
        self._redraw_set = set()
        self._nvim_err = None

    def _get_grid(self, handle: int):
        g = self._grid_map.get(handle)
        if g is not None:
            return g
        w = DemoWindow(tv.TRect(0, 0, 102, 27), "NeoVim", tv.wnNoNumber)
        self.deskTop.insert(w)
        self._grid_map[handle] = w.grid
        return w.grid

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
                    if kind in {
                        "grid_resize",
                        "grid_line",
                        "grid_clear",
                        "grid_destroy",
                        "grid_cursor_goto",
                        "grid_scroll",
                    }:
                        g = self._get_grid(event_args[0])
                        g.redraw_event(kind, event_args[1:])
                        self._redraw_set.add(g)
                    elif kind == "flush":
                        for v in self._redraw_set:
                            v.drawView()
                        self._redraw_set = set()
                    elif kind == "default_colors_set":
                        rgb_fg, rgb_bg, rgb_sp = event_args[:3]
                        DEFAULT_HL_ATTR_DICT.update(
                            {
                                "foreground": rgb_fg,
                                "background": rgb_bg,
                                "special": rgb_sp,
                            }
                        )
                        HL_ATTRS[None] = attr_dict_to_tcolorattr(DEFAULT_HL_ATTR_DICT)
                        for k, v in HL_ATTR_DICTS.items():
                            HL_ATTRS[k] = attr_dict_to_tcolorattr(
                                collections.ChainMap(v, DEFAULT_HL_ATTR_DICT)
                            )
                    elif kind == "hl_attr_define":
                        id, rgb_attr = event_args[:2]
                        HL_ATTR_DICTS[id] = rgb_attr
                        HL_ATTRS[id] = attr_dict_to_tcolorattr(
                            collections.ChainMap(rgb_attr, DEFAULT_HL_ATTR_DICT)
                        )

    def _dump(self):
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
