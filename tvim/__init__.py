import queue
import shutil
import threading
import typing

import tvision as tv
from pynvim import Nvim, attach

CMD_DUMP = 200


class Grid(tv.TView):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cx, self._cy = -1, -1
        self._resize(80, 25)

    def draw(self):
        color = self.getColor(0x0301)
        for y, line in enumerate(self._grid):
            b = tv.TDrawBuffer()
            for x, c in enumerate(line):
                b.moveStr(x, c, color.at(0), 1)
            self.writeLine(0, y, len(line), 1, b)
        self.setCursor(self._cx, self._cy)
        self.showCursor()

    def redraw_event(self, kind: str, args: list[typing.Any]):
        if kind == "grid_resize":
            _, w, h = args
            self._resize(w, h)
        elif kind == "grid_line":
            _, row, col_start, cells, wrap = args
            chars = []
            for c in cells:
                r = [" ", 0, 1]
                r[: len(c)] = c
                txt, _, repeat = r
                chars.extend([txt] * repeat)
                if wrap and col_start + len(chars) == len(self._grid[row]):
                    self._grid[row][col_start : col_start + len(cells)] = chars
                    chars = []
                    row += 1
            self._grid[row][col_start : col_start + len(cells)] = chars
        elif kind == "grid_clear":
            for row in self._grid:
                row[:] = [" "] * len(row)
        elif kind == "grid_scroll":
            _, top, bot, left, right, rows, cols = args
            if rows > 0:
                for dr in range(top, bot + 1):
                    sr = dr - rows
                    if sr >= 0:
                        self._grid[sr] = [c for c in self._grid[dr]]
            else:
                for dr in range(bot, top - 1, -1):
                    sr = dr + rows
                    if sr >= 0:
                        self._grid[sr] = [c for c in self._grid[dr]]
        elif kind == "grid_cursor_goto":
            _, self._cy, self._cx = args
        elif kind == "flush":
            self.drawView()

    def _resize(self, cols: int, rows: int):
        self._grid = [[" "] * cols for _ in range(rows)]


class DemoWindow(tv.TWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        bounds = self.getExtent()
        self.grid = self._make_grid(bounds)
        self.insert(self.grid)

    def _make_grid(self, bounds: tv.TRect):
        bounds.grow(-1, -1)
        return Grid(bounds)


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
                    for event_args in event[1:]:
                        self._g.redraw_event(event[0], event_args)

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
