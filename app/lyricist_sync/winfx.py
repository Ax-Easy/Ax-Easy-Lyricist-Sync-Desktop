"""Windows-only window effects through ctypes: acrylic (Windows 10), Mica (Windows 11),
rounded window region, and the native frame bits that keep a frameless window
resizable/snappable (Aero Snap, Win+arrows). Every call fails soft and returns False."""
import ctypes
import os
import sys

IS_WIN = os.name == 'nt'
WM_NCCALCSIZE, WM_NCHITTEST, WM_NCACTIVATE = 0x0083, 0x0084, 0x0086
HTCLIENT, HTCAPTION, HTTRANSPARENT = 1, 2, -1
HTLEFT, HTRIGHT, HTTOP, HTTOPLEFT, HTTOPRIGHT, HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 10, 11, 12, 13, 14, 15, 16, 17


def build():
    try:
        return sys.getwindowsversion().build if IS_WIN else 0
    except Exception:
        return 0


if IS_WIN:
    from ctypes import wintypes

    class ACCENT_POLICY(ctypes.Structure):
        _fields_ = [('AccentState', ctypes.c_int), ('AccentFlags', ctypes.c_int),
                    ('GradientColor', ctypes.c_uint), ('AnimationId', ctypes.c_int)]

    class WINCOMPATTRDATA(ctypes.Structure):
        _fields_ = [('Attribute', ctypes.c_int), ('Data', ctypes.c_void_p), ('SizeOfData', ctypes.c_size_t)]

    class MARGINS(ctypes.Structure):
        _fields_ = [('l', ctypes.c_int), ('r', ctypes.c_int), ('t', ctypes.c_int), ('b', ctypes.c_int)]

    class NCCALCSIZE_PARAMS(ctypes.Structure):
        _fields_ = [('rgrc', wintypes.RECT * 3), ('lppos', ctypes.c_void_p)]

    user32 = ctypes.windll.user32
    try:
        dwm = ctypes.windll.dwmapi
    except OSError:
        dwm = None
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]


def _abgr(argb):
    a, r, g, b = (argb >> 24) & 255, (argb >> 16) & 255, (argb >> 8) & 255, argb & 255
    return (a << 24) | (b << 16) | (g << 8) | r


def set_acrylic(hwnd, tint_argb=0xB0141820, enable=True):
    """Windows 10 1803+: ACCENT_ENABLE_ACRYLICBLURBEHIND with a tint (ARGB).
    Not used since 1.1.0: it blurs the whole rectangular window (square edges outside the
    rounded corners). Kept for reference/diagnostics."""
    if not IS_WIN:
        return False
    try:
        acc = ACCENT_POLICY(4 if enable else 0, 2 if enable else 0, _abgr(tint_argb), 0)
        data = WINCOMPATTRDATA(19, ctypes.cast(ctypes.pointer(acc), ctypes.c_void_p), ctypes.sizeof(acc))
        return bool(user32.SetWindowCompositionAttribute(int(hwnd), ctypes.byref(data)))
    except Exception:
        return False


def set_mica(hwnd, dark=True):
    """Windows 11: Mica backdrop (22621+: DWMWA_SYSTEMBACKDROP_TYPE; 22000: legacy attribute)."""
    if not IS_WIN or dwm is None or build() < 22000:
        return False
    try:
        h = int(hwnd)
        val = ctypes.c_int(1 if dark else 0)
        dwm.DwmSetWindowAttribute(h, 20, ctypes.byref(val), 4)  # immersive dark mode
        m = MARGINS(-1, -1, -1, -1)
        dwm.DwmExtendFrameIntoClientArea(h, ctypes.byref(m))
        corner = ctypes.c_int(2)  # DWMWCP_ROUND
        dwm.DwmSetWindowAttribute(h, 33, ctypes.byref(corner), 4)
        if build() >= 22621:
            v = ctypes.c_int(2)  # DWMSBT_MAINWINDOW (Mica)
            return dwm.DwmSetWindowAttribute(h, 38, ctypes.byref(v), 4) == 0
        v = ctypes.c_int(1)
        return dwm.DwmSetWindowAttribute(h, 1029, ctypes.byref(v), 4) == 0
    except Exception:
        return False


def set_round_region(hwnd, w, h, radius):
    """Clip the window (and its acrylic) to a rounded rect; radius 0 removes the region."""
    if not IS_WIN:
        return False
    try:
        gdi32 = ctypes.windll.gdi32
        if radius <= 0:
            return bool(user32.SetWindowRgn(int(hwnd), None, True))
        rgn = gdi32.CreateRoundRectRgn(0, 0, int(w) + 1, int(h) + 1, int(radius * 2), int(radius * 2))
        return bool(user32.SetWindowRgn(int(hwnd), rgn, True))
    except Exception:
        return False


def enable_native_frame(hwnd, dwm_frame=False):
    """Add the style bits Windows needs for Aero Snap, Win+arrows, min/max animations.
    dwm_frame: extend the DWM frame (Windows 11 path only: Mica + DWM shadow). On the
    painted Windows 10 path it must stay off, or DWM draws a rectangular shadow/edge
    around the transparent shadow margin."""
    if not IS_WIN:
        return False
    try:
        h = int(hwnd)
        GWL_STYLE = -16
        WS_CAPTION, WS_THICKFRAME, WS_MINIMIZEBOX, WS_MAXIMIZEBOX, WS_SYSMENU = 0x00C00000, 0x00040000, 0x00020000, 0x00010000, 0x00080000
        st = user32.GetWindowLongPtrW(h, GWL_STYLE)
        user32.SetWindowLongPtrW(h, GWL_STYLE, st | WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU)
        user32.SetWindowPos(h, None, 0, 0, 0, 0, 0x0020 | 0x0002 | 0x0001 | 0x0004 | 0x0010)  # FRAMECHANGED|NOMOVE|NOSIZE|NOZORDER|NOACTIVATE
        if dwm is not None and dwm_frame:
            m = MARGINS(-1, -1, -1, -1)
            dwm.DwmExtendFrameIntoClientArea(h, ctypes.byref(m))
        elif dwm is not None:
            pol = ctypes.c_int(1)  # DWMNCRP_DISABLED: no DWM non-client rendering (no square shadow)
            dwm.DwmSetWindowAttribute(h, 2, ctypes.byref(pol), 4)
        return True
    except Exception:
        return False


def frame_thickness(hwnd):
    try:
        dpi = user32.GetDpiForWindow(int(hwnd))
        return user32.GetSystemMetricsForDpi(32, dpi) + user32.GetSystemMetricsForDpi(92, dpi)
    except Exception:
        return 8


def read_msg(message):
    return wintypes.MSG.from_address(int(message))


def fix_maximized_rect(msg, hwnd):
    """WM_NCCALCSIZE while maximized: keep the client area inside the monitor."""
    p = NCCALCSIZE_PARAMS.from_address(msg.lParam)
    t = frame_thickness(hwnd)
    r = p.rgrc[0]
    r.left += t
    r.top += t
    r.right -= t
    r.bottom -= t


def apps_use_dark():
    """True/False from the Windows app theme, None when unknown."""
    if not IS_WIN:
        return None
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize')
        return winreg.QueryValueEx(k, 'AppsUseLightTheme')[0] == 0
    except Exception:
        return None
