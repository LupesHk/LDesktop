import ctypes
import os
import threading
from ctypes import wintypes

try:
    from windows_capture import WindowsCapture
    _WGC_IMPORT_ERROR = None
except Exception as error:
    WindowsCapture = None
    _WGC_IMPORT_ERROR = error


if os.name != "nt":
    raise RuntimeError("A captura de janelas está disponível somente no Windows.")


user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PW_RENDERFULLCONTENT = 0x00000002
DIB_RGB_COLORS = 0
BI_RGB = 0


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class RGBQUAD(ctypes.Structure):
    _fields_ = [
        ("rgbBlue", wintypes.BYTE),
        ("rgbGreen", wintypes.BYTE),
        ("rgbRed", wintypes.BYTE),
        ("rgbReserved", wintypes.BYTE),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", RGBQUAD * 1),
    ]


user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.PrintWindow.restype = wintypes.BOOL

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD)
]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL

gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD
]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
gdi32.SelectObject.restype = wintypes.HANDLE
gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL



class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class CURSORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hCursor", wintypes.HANDLE),
        ("ptScreenPos", POINT),
    ]


class ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HANDLE),
        ("hbmColor", wintypes.HANDLE),
    ]


CURSOR_SHOWING = 0x00000001
DI_NORMAL = 0x0003
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
GW_OWNER = 4

user32.GetCursorInfo.argtypes = [ctypes.POINTER(CURSORINFO)]
user32.GetCursorInfo.restype = wintypes.BOOL
user32.GetIconInfo.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(ICONINFO)
]
user32.GetIconInfo.restype = wintypes.BOOL
user32.DrawIconEx.argtypes = [
    wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.HANDLE,
    ctypes.c_int, ctypes.c_int, wintypes.UINT,
    wintypes.HANDLE, wintypes.UINT
]
user32.DrawIconEx.restype = wintypes.BOOL
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetWindow.restype = wintypes.HWND
user32.GetShellWindow.restype = wintypes.HWND
user32.GetClassNameW.argtypes = [
    wintypes.HWND, wintypes.LPWSTR, ctypes.c_int
]
user32.GetClassNameW.restype = ctypes.c_int

_get_window_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
_get_window_long.argtypes = [wintypes.HWND, ctypes.c_int]
_get_window_long.restype = ctypes.c_ssize_t

user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int

gdi32.BitBlt.argtypes = [
    wintypes.HDC, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, wintypes.HDC,
    ctypes.c_int, ctypes.c_int, wintypes.DWORD
]
gdi32.BitBlt.restype = wintypes.BOOL

SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000


def _draw_cursor(dc, origin_x, origin_y, width, height):
    info = CURSORINFO()
    info.cbSize = ctypes.sizeof(CURSORINFO)

    if not user32.GetCursorInfo(ctypes.byref(info)):
        return False
    if not (info.flags & CURSOR_SHOWING) or not info.hCursor:
        return False

    icon = ICONINFO()
    if not user32.GetIconInfo(info.hCursor, ctypes.byref(icon)):
        return False

    try:
        x = int(info.ptScreenPos.x) - int(icon.xHotspot) - origin_x
        y = int(info.ptScreenPos.y) - int(icon.yHotspot) - origin_y

        # Evita desenhar quando o ponteiro está muito distante da fonte.
        if x < -96 or y < -96 or x >= width or y >= height:
            return False

        return bool(user32.DrawIconEx(
            dc, x, y, info.hCursor, 0, 0, 0, None, DI_NORMAL
        ))
    finally:
        if icon.hbmMask:
            gdi32.DeleteObject(icon.hbmMask)
        if icon.hbmColor:
            gdi32.DeleteObject(icon.hbmColor)


def _process_path(pid):
    handle = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )
    if not handle:
        return ""

    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        if kernel32.QueryFullProcessImageNameW(
            handle, 0, buffer, ctypes.byref(size)
        ):
            return buffer.value
        return ""
    finally:
        kernel32.CloseHandle(handle)


def _window_bounds(hwnd):
    rect = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise RuntimeError("Não foi possível obter as dimensões da janela.")

    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width < 160 or height < 100:
        raise RuntimeError("A janela possui dimensões muito pequenas.")

    return rect.left, rect.top, width, height


def _window_rect(hwnd):
    _, _, width, height = _window_bounds(hwnd)
    return width, height

def list_capture_windows():
    windows = []
    seen = set()
    shell_hwnd = user32.GetShellWindow()

    excluded_processes = {
        "textinputhost.exe",
        "searchhost.exe",
        "searchapp.exe",
        "shellexperiencehost.exe",
        "startmenuexperiencehost.exe",
        "lockapp.exe",
        "applicationframehost.exe",
        "runtimebroker.exe",
        "widgets.exe",
        "securityhealthsystray.exe",
    }

    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True

        if shell_hwnd and hwnd == shell_hwnd:
            return True

        # Ignora popups pertencentes a outras janelas e tool windows.
        if user32.GetWindow(hwnd, GW_OWNER):
            return True

        ex_style = _get_window_long(hwnd, GWL_EXSTYLE)
        if ex_style & (WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE):
            return True

        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True

        title_buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
        title = title_buffer.value.strip()

        if not title or title.casefold() == "program manager":
            return True

        class_buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))
        class_name = class_buffer.value

        if class_name in {"Progman", "WorkerW", "Shell_TrayWnd"}:
            return True

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value or pid.value == os.getpid():
            return True

        path = _process_path(pid.value)
        process_name = os.path.basename(path) if path else "Aplicativo"

        if process_name.casefold() in excluded_processes:
            return True

        try:
            left, top, width, height = _window_bounds(hwnd)
        except RuntimeError:
            return True

        key = (int(pid.value), title.casefold())
        if key in seen:
            return True
        seen.add(key)

        windows.append({
            "hwnd": int(hwnd),
            "pid": int(pid.value),
            "title": title,
            "process_name": process_name,
            "process_path": path,
            "left": left,
            "top": top,
            "width": width,
            "height": height,
            "display": f"{title} — {process_name}",
        })
        return True

    enum_proc = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
    )(callback)

    user32.EnumWindows(enum_proc, 0)
    windows.sort(key=lambda item: item["title"].casefold())
    return windows

class WindowCapture:
    def __init__(self, hwnd):
        self.hwnd = wintypes.HWND(int(hwnd))
        self.width = 0
        self.height = 0
        self.dc = None
        self.bitmap = None
        self.previous_bitmap = None
        self.bits = ctypes.c_void_p()

        if not user32.IsWindow(self.hwnd):
            raise RuntimeError("A janela selecionada não existe mais.")
        if user32.IsIconic(self.hwnd):
            raise RuntimeError("A janela selecionada está minimizada.")

        self.left, self.top, self.width, self.height = (
            _window_bounds(self.hwnd)
        )
        self.dc = gdi32.CreateCompatibleDC(None)
        if not self.dc:
            raise RuntimeError("Não foi possível criar o contexto de captura.")

        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = self.width
        info.bmiHeader.biHeight = -self.height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = BI_RGB
        info.bmiHeader.biSizeImage = self.width * self.height * 4

        self.bitmap = gdi32.CreateDIBSection(
            self.dc, ctypes.byref(info), DIB_RGB_COLORS,
            ctypes.byref(self.bits), None, 0
        )
        if not self.bitmap or not self.bits.value:
            self.close()
            raise RuntimeError("Não foi possível criar o buffer de imagem.")

        self.previous_bitmap = gdi32.SelectObject(self.dc, self.bitmap)

    def grab(self):
        if not user32.IsWindow(self.hwnd):
            raise RuntimeError("A janela foi fechada durante a transmissão.")
        if user32.IsIconic(self.hwnd):
            raise RuntimeError("A janela foi minimizada durante a transmissão.")

        left, top, width, height = _window_bounds(self.hwnd)
        if (width, height) != (self.width, self.height):
            raise RuntimeError(
                "A janela mudou de tamanho. Encerre e reinicie a transmissão."
            )

        self.left, self.top = left, top

        success = user32.PrintWindow(
            self.hwnd, self.dc, PW_RENDERFULLCONTENT
        )
        if not success:
            success = user32.PrintWindow(self.hwnd, self.dc, 0)

        if not success:
            raise RuntimeError(
                "O Windows não conseguiu capturar esta janela. "
                "O aplicativo pode bloquear captura externa."
            )

        _draw_cursor(
            self.dc, self.left, self.top, self.width, self.height
        )

        return ctypes.string_at(
            self.bits.value, self.width * self.height * 4
        )

    def close(self):
        if self.dc and self.previous_bitmap:
            gdi32.SelectObject(self.dc, self.previous_bitmap)
            self.previous_bitmap = None

        if self.bitmap:
            gdi32.DeleteObject(self.bitmap)
            self.bitmap = None

        if self.dc:
            gdi32.DeleteDC(self.dc)
            self.dc = None

        self.bits = ctypes.c_void_p()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


class MONITORINFOEX(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


MONITORINFOF_PRIMARY = 1

user32.GetMonitorInfoW.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(MONITORINFOEX),
]
user32.GetMonitorInfoW.restype = wintypes.BOOL


def list_capture_monitors():
    monitors = []

    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HANDLE,
        wintypes.HDC,
        ctypes.POINTER(RECT),
        ctypes.c_ssize_t,
    )

    def callback(hmonitor, _hdc, _rect, _data):
        info = MONITORINFOEX()
        info.cbSize = ctypes.sizeof(MONITORINFOEX)

        if not user32.GetMonitorInfoW(
            hmonitor, ctypes.byref(info)
        ):
            return True

        rect = info.rcMonitor
        width = rect.right - rect.left
        height = rect.bottom - rect.top

        if width <= 0 or height <= 0:
            return True

        monitors.append({
            "id": info.szDevice,
            "device": info.szDevice,
            "left": int(rect.left),
            "top": int(rect.top),
            "width": int(width),
            "height": int(height),
            "primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
        })
        return True

    callback_ref = callback_type(callback)

    if not user32.EnumDisplayMonitors(
        None, None, callback_ref, 0
    ):
        raise RuntimeError(
            "Não foi possível enumerar os monitores do Windows."
        )

    monitors.sort(
        key=lambda item: (
            not item["primary"],
            item["top"],
            item["left"],
        )
    )

    for index, monitor in enumerate(monitors, start=1):
        primary_label = " — principal" if monitor["primary"] else ""
        monitor["display"] = (
            f"Tela inteira — Monitor {index} "
            f"({monitor['width']}x{monitor['height']})"
            f"{primary_label}"
        )

    return monitors


class MonitorCapture:
    """Captura somente o monitor escolhido, incluindo o cursor."""

    def __init__(self, monitor_info):
        self.left = int(monitor_info["left"])
        self.top = int(monitor_info["top"])
        self.width = int(monitor_info["width"])
        self.height = int(monitor_info["height"])
        self.device = str(monitor_info.get("device", ""))

        self.screen_dc = None
        self.dc = None
        self.bitmap = None
        self.previous_bitmap = None
        self.bits = ctypes.c_void_p()

        if self.width <= 0 or self.height <= 0:
            raise RuntimeError("Dimensões de monitor inválidas.")

        try:
            self.screen_dc = user32.GetDC(None)
            if not self.screen_dc:
                raise RuntimeError("Não foi possível acessar a tela.")

            self.dc = gdi32.CreateCompatibleDC(self.screen_dc)
            if not self.dc:
                raise RuntimeError(
                    "Não foi possível criar o contexto de captura."
                )

            info = BITMAPINFO()
            info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            info.bmiHeader.biWidth = self.width
            info.bmiHeader.biHeight = -self.height
            info.bmiHeader.biPlanes = 1
            info.bmiHeader.biBitCount = 32
            info.bmiHeader.biCompression = BI_RGB
            info.bmiHeader.biSizeImage = self.width * self.height * 4

            self.bitmap = gdi32.CreateDIBSection(
                self.dc,
                ctypes.byref(info),
                DIB_RGB_COLORS,
                ctypes.byref(self.bits),
                None,
                0,
            )

            if not self.bitmap or not self.bits.value:
                raise RuntimeError(
                    "Não foi possível criar o buffer do monitor."
                )

            self.previous_bitmap = gdi32.SelectObject(
                self.dc, self.bitmap
            )

        except Exception:
            self.close()
            raise

    def grab(self):
        success = gdi32.BitBlt(
            self.dc,
            0,
            0,
            self.width,
            self.height,
            self.screen_dc,
            self.left,
            self.top,
            SRCCOPY | CAPTUREBLT,
        )

        if not success:
            raise RuntimeError(
                "Não foi possível capturar o monitor selecionado."
            )

        _draw_cursor(
            self.dc,
            self.left,
            self.top,
            self.width,
            self.height,
        )

        return ctypes.string_at(
            self.bits.value,
            self.width * self.height * 4,
        )

    def close(self):
        if self.dc and self.previous_bitmap:
            gdi32.SelectObject(self.dc, self.previous_bitmap)
            self.previous_bitmap = None

        if self.bitmap:
            gdi32.DeleteObject(self.bitmap)
            self.bitmap = None

        if self.dc:
            gdi32.DeleteDC(self.dc)
            self.dc = None

        if self.screen_dc:
            user32.ReleaseDC(None, self.screen_dc)
            self.screen_dc = None

        self.bits = ctypes.c_void_p()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


class WgcMonitorCapture:
    """
    Captura de monitor por Windows Graphics Capture.

    Os quadros s?o copiados dentro do callback nativo para bytes
    independentes. O m?todo grab() entrega o quadro mais recente
    ? thread de captura j? existente no L Desktop.

    Se a sess?o WGC falhar durante a transmiss?o, troca para GDI.
    """

    def __init__(self, monitor_info, startup_timeout=10):
        if WindowsCapture is None:
            raise RuntimeError(
                f"Biblioteca Windows Capture indispon?vel: "
                f"{_WGC_IMPORT_ERROR}"
            )

        self.monitor_info = dict(monitor_info or {})
        self.width = int(self.monitor_info["width"])
        self.height = int(self.monitor_info["height"])
        self.device = str(
            self.monitor_info.get("device")
            or self.monitor_info.get("id")
            or ""
        )

        if self.width <= 0 or self.height <= 0:
            raise RuntimeError("Dimens?es inv?lidas do monitor WGC.")

        self.backend = "WGC"
        self._frame_lock = threading.Lock()
        self._ready_event = threading.Event()
        self._closing_event = threading.Event()
        self._latest_frame = None
        self._error = None
        self._capture = None
        self._control = None
        self._fallback = None

        self.monitor_index = self._resolve_monitor_index()

        try:
            capture = WindowsCapture(
                cursor_capture=True,
                draw_border=False,
                monitor_index=self.monitor_index,
            )
            self._capture = capture

            @capture.event
            def on_frame_arrived(frame, capture_control):
                try:
                    if self._closing_event.is_set():
                        capture_control.stop()
                        return

                    frame_width = int(frame.width)
                    frame_height = int(frame.height)

                    if (
                        frame_width != self.width
                        or frame_height != self.height
                    ):
                        raise RuntimeError(
                            "WGC selecionou uma resolu??o diferente: "
                            f"{frame_width}x{frame_height}; esperado "
                            f"{self.width}x{self.height}."
                        )

                    # frame_buffer ? uma vis?o da mem?ria nativa.
                    # tobytes() copia os pixels antes de o callback terminar.
                    raw = frame.frame_buffer.tobytes(order="C")

                    expected = self.width * self.height * 4
                    if len(raw) != expected:
                        raise RuntimeError(
                            f"Quadro WGC inv?lido: {len(raw)} bytes; "
                            f"esperado {expected}."
                        )

                    with self._frame_lock:
                        self._latest_frame = raw

                    self._ready_event.set()

                except Exception as error:
                    self._set_error(error)
                    capture_control.stop()

            @capture.event
            def on_closed():
                if not self._closing_event.is_set():
                    self._set_error(
                        RuntimeError(
                            "A sess?o Windows Graphics Capture foi encerrada."
                        )
                    )

            self._control = capture.start_free_threaded()

            if not self._ready_event.wait(startup_timeout):
                raise TimeoutError(
                    "WGC n?o entregou o primeiro quadro no prazo."
                )

            with self._frame_lock:
                startup_error = self._error
                first_frame = self._latest_frame

            if startup_error is not None:
                raise RuntimeError(
                    f"Falha ao iniciar captura WGC: {startup_error}"
                ) from startup_error

            if first_frame is None:
                raise RuntimeError(
                    "WGC iniciou sem entregar um quadro v?lido."
                )

            print(
                f"[LIVE STREAM] WGC ativo | monitor "
                f"{self.monitor_index} | {self.width}x{self.height}"
            )

        except Exception:
            self.close()
            raise

    def _resolve_monitor_index(self):
        monitors = list_capture_monitors()

        if not monitors:
            raise RuntimeError(
                "O Windows n?o informou monitores dispon?veis."
            )

        matches = []

        for candidate in range(1, len(monitors) + 1):
            probe = None
            control = None
            arrived = threading.Event()
            result = {}

            try:
                probe = WindowsCapture(
                    cursor_capture=False,
                    draw_border=False,
                    monitor_index=candidate,
                )

                @probe.event
                def on_frame_arrived(frame, capture_control):
                    result["resolution"] = (
                        int(frame.width),
                        int(frame.height),
                    )
                    arrived.set()
                    capture_control.stop()

                @probe.event
                def on_closed():
                    pass

                control = probe.start_free_threaded()

                if not arrived.wait(5):
                    continue

                if result.get("resolution") == (
                    self.width,
                    self.height,
                ):
                    matches.append(candidate)

            except Exception:
                continue

            finally:
                if control is not None:
                    try:
                        control.stop()
                        control.wait()
                    except Exception:
                        pass

                probe = None
                control = None

        if len(matches) == 1:
            return matches[0]

        if len(matches) > 1:
            raise RuntimeError(
                "Mais de um monitor WGC possui a mesma resolu??o. "
                "GDI ser? utilizado para evitar capturar a tela errada."
            )

        raise RuntimeError(
            "Nenhum ?ndice WGC corresponde ao monitor selecionado. "
            "GDI ser? utilizado."
        )

    def _set_error(self, error):
        with self._frame_lock:
            if self._error is None:
                self._error = error

        self._ready_event.set()

    def _stop_wgc(self):
        self._closing_event.set()

        control = self._control
        if control is None:
            return

        try:
            if not control.is_finished():
                control.stop()

            control.wait()

        except Exception as error:
            print(
                f"[LIVE STREAM] Aviso ao encerrar WGC: {error}"
            )

        finally:
            self._control = None

    def _activate_gdi_fallback(self, reason):
        if self._fallback is not None:
            return

        print(
            "[LIVE STREAM] WGC falhou durante a transmiss?o. "
            f"Ativando GDI: {reason}"
        )

        self._stop_wgc()
        self._fallback = MonitorCapture(self.monitor_info)
        self.backend = "GDI"

    def grab(self):
        if self._fallback is not None:
            return self._fallback.grab()

        with self._frame_lock:
            error = self._error
            frame = self._latest_frame

        if error is not None:
            self._activate_gdi_fallback(error)
            return self._fallback.grab()

        if frame is None:
            if not self._ready_event.wait(2):
                self._activate_gdi_fallback(
                    "Nenhum quadro WGC dispon?vel."
                )
                return self._fallback.grab()

            with self._frame_lock:
                error = self._error
                frame = self._latest_frame

            if error is not None or frame is None:
                self._activate_gdi_fallback(
                    error or "Quadro WGC vazio."
                )
                return self._fallback.grab()

        return frame

    def close(self):
        self._stop_wgc()

        if self._fallback is not None:
            try:
                self._fallback.close()
            finally:
                self._fallback = None
