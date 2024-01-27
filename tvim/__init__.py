import queue
import shutil
import threading
import typing

import tvision as tv
from pynvim import Nvim, attach

CMD_DUMP = 200


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
            _, w, h = args[0]
            self._resize(w, h)
        elif kind == "grid_line":
            attr = tv.TColorAttr(
                tv.TColorDesired(tv.TColorRGB(0xff, 0xff, 0xff)),
                tv.TColorDesired(tv.TColorRGB(0x00, 0x00, 0x00)),
            )
            for _, row, col_start, cells, _ in args:
                x, y = col_start, row
                for c in cells:
                    r = [" ", 0, 1]
                    r[: len(c)] = c
                    txt, _, repeat = r
                    for _ in range(repeat):
                        cell = tv.TScreenCell()
                        cell._ch.moveStr(txt)
                        cell.attr = attr
                        self[x, y] = cell
                        x += 1
        elif kind == "grid_clear":
            self.clear()
        elif kind == "grid_scroll":
            _, top, bot, left, right, rows, cols = args[0]
            assert cols == 0
            rng = range(top, bot) if rows > 0 else reversed(range(top, bot))
            for sr in rng:
                dr = sr - rows
                if dr >= 0:
                    for x in range(self._cols):
                        self[x, dr] = self[x, sr]
        else:
            return False

        return True


class GridView(tv.TSurfaceView):
    def __init__(self, bounds: tv.TRect, *args, **kwargs):
        self._surface = GridSurface()
        super().__init__(bounds, self._surface, *args, **kwargs)
        self._cx, self._cy = -1, -1
        self.setState(tv.sfCursorVis, True)
        self.setState(tv.sfFocused, True)

    def redraw_event(self, kind: str, args: list[typing.Any]):
        if self._surface.process_grid_event(kind, args):
            return
        elif kind == "grid_cursor_goto":
            _, self._cy, self._cx = args[0]
            self.setCursor(self._cx, self._cy)
        elif kind == "flush":
            self.drawView()


class DemoWindow(tv.TWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        bounds = self.getExtent()
        self.grid = self._make_grid(bounds)
        self.insert(self.grid)

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
}


class Application(tv.TApplication):
    def __init__(self, nvim: Nvim):
        super().__init__()
        self._nvim = nvim
        self._w = DemoWindow(tv.TRect(0, 0, 102, 27), "NeoVim", tv.wnNoNumber)
        self.deskTop.insert(self._w)
        self._g = self._w.grid
        self._notification_queue = queue.Queue()

    def run(self) -> int:
        self._nvim_thread = threading.Thread(
            target=self._nvim.run_loop,
            kwargs={
                "request_cb": self._nvim_request_cb,
                "notification_cb": self._nvim_notification_cb,
                "setup_cb": self._nvim_setup_cb,
            },
        )
        self._nvim_thread.start()
        try:
            return super().run()
        finally:
            self._nvim.async_call(self._nvim.quit)
            self._nvim.stop_loop()
            self._nvim_thread.join(0.1)

    def idle(self) -> None:
        while not self._notification_queue.empty():
            name, args = self._notification_queue.get()
            if name == "redraw":
                for event in args:
                    self._g.redraw_event(event[0], event[1:])

    def _nvim_setup_cb(self) -> None:
        self._nvim.ui_attach(100, 25, rgb=True, ext_linegrid=True)
        self._nvim.command(f"e {__file__}")

    def _nvim_request_cb(self, name: str, args: list[typing.Any]) -> typing.Any:
        # print(f"req: n: {name!r}, a: {args!r}")
        pass

    def _nvim_notification_cb(self, name: str, args: list[typing.Any]) -> typing.Any:
        self._notification_queue.put((name, args))

    def _dump(self):
        print("xx")

    def handleEvent(self, event: tv.TEvent):
        super().handleEvent(event)
        if event.what == tv.evCommand:
            cmd = event.message.command
            if cmd == CMD_DUMP:
                self._dump()
            self.clearEvent(event)
        elif event.what == tv.evKeyDown:
            if event.keyDown.controlKeyState == tv.kbInsState:
                txt = _SPECIAL_KEYS.get(event.keyDown.keyCode, event.keyDown.getText())
                self._nvim.async_call(self._insert, txt)
            self.clearEvent(event)

    def _insert(self, txt: str):
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
