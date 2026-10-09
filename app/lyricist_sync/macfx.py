"""macOS helpers without PyObjC (ctypes on the Objective-C runtime): the native title bar with
the traffic lights over the glass (full-size content view, transparent title bar), behind-window
vibrancy (NSVisualEffectView), the window appearance (Aqua / Dark Aqua), Finder reveal and the
hardware facts the engine setup needs. Every call is a no-op (False) off macOS or on failure, so
the painted glass of the other platforms is always the fallback."""
import ctypes
import ctypes.util
import os
import platform
import subprocess
import sys

IS_MAC = sys.platform == 'darwin'
TITLEBAR_H = 28          # height of the standard title bar strip (points)
TRAFFIC_W = 78           # room the three traffic-light buttons need at the left of that strip

_objc = None


def _rt():
    global _objc
    if _objc is None:
        lib = ctypes.cdll.LoadLibrary(ctypes.util.find_library('objc'))
        lib.objc_getClass.restype = ctypes.c_void_p
        lib.objc_getClass.argtypes = [ctypes.c_char_p]
        lib.sel_registerName.restype = ctypes.c_void_p
        lib.sel_registerName.argtypes = [ctypes.c_char_p]
        ctypes.cdll.LoadLibrary(ctypes.util.find_library('AppKit'))   # NSVisualEffectView, NSAppearance
        _objc = lib
    return _objc


class CGRect(ctypes.Structure):
    _fields_ = [('x', ctypes.c_double), ('y', ctypes.c_double), ('w', ctypes.c_double), ('h', ctypes.c_double)]


def _send(obj, sel, *args, restype=ctypes.c_void_p, argtypes=None):
    """objc_msgSend with an exact prototype (required on arm64, where variadic calls differ)."""
    rt = _rt()
    if argtypes is None:
        argtypes = [type(a) if isinstance(a, (ctypes._SimpleCData, ctypes.Structure)) else ctypes.c_void_p for a in args]
    f = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes)(('objc_msgSend', rt))
    return f(obj, rt.sel_registerName(sel.encode()), *args)


def _cls(name):
    return _rt().objc_getClass(name.encode())


def _nsstring(s):
    return _send(_cls('NSString'), 'stringWithUTF8String:', ctypes.c_char_p(s.encode('utf-8')))


def _window(widget):
    view = ctypes.c_void_p(int(widget.winId()))
    w = _send(view, 'window')
    return view, w


# NSWindowStyleMaskFullSizeContentView, NSWindowTitleHidden, NSWindowBelow, blending/state constants
FULL_SIZE_CONTENT = 1 << 15
MATERIALS = {'under_window': 21, 'hud': 13, 'sidebar': 7, 'window': 12, 'popover': 6}


def native_titlebar(widget):
    """Keep the real title bar (traffic lights, green-button full screen, double-click zoom,
    window snapping) but let the content run underneath it, transparent and without a title."""
    if not IS_MAC:
        return False
    try:
        _view, w = _window(widget)
        if not w:
            return False
        mask = _send(w, 'styleMask', restype=ctypes.c_ulong, argtypes=[])
        _send(w, 'setStyleMask:', ctypes.c_ulong(mask | FULL_SIZE_CONTENT))
        _send(w, 'setTitlebarAppearsTransparent:', ctypes.c_bool(True))
        _send(w, 'setTitleVisibility:', ctypes.c_long(1))
        # the window gets the full-screen button behaviour (NSWindowCollectionBehaviorFullScreenPrimary)
        cb = _send(w, 'collectionBehavior', restype=ctypes.c_ulong, argtypes=[])
        _send(w, 'setCollectionBehavior:', ctypes.c_ulong(cb | (1 << 7)))
        return True
    except Exception:
        return False


def set_appearance(widget, dark):
    """Aqua or Dark Aqua for this window (title bar buttons, vibrancy and native menus follow it)."""
    if not IS_MAC:
        return False
    try:
        _view, w = _window(widget)
        ap = _send(_cls('NSAppearance'), 'appearanceNamed:', ctypes.c_void_p(_nsstring('NSAppearanceNameDarkAqua' if dark else 'NSAppearanceNameAqua')))
        _send(w, 'setAppearance:', ctypes.c_void_p(ap))
        return True
    except Exception:
        return False


def add_vibrancy(widget, material='under_window'):
    """An NSVisualEffectView (behind-window blending) under Qt's content view, sized with the
    window. Qt paints a translucent tint over it. Returns the effect view pointer or None."""
    if not IS_MAC:
        return None
    try:
        view, w = _window(widget)
        if not w:
            return None
        frame = _send(view, 'superview')            # the window's frame view (title bar + content)
        if not frame:
            return None
        ev = _send(_send(_cls('NSVisualEffectView'), 'alloc'), 'init')
        _send(ev, 'setMaterial:', ctypes.c_long(MATERIALS.get(material, 21)))
        _send(ev, 'setBlendingMode:', ctypes.c_long(0))     # NSVisualEffectBlendingModeBehindWindow
        _send(ev, 'setState:', ctypes.c_long(1))            # NSVisualEffectStateActive (also when inactive)
        _send(ev, 'setAutoresizingMask:', ctypes.c_ulong(2 | 16))   # width + height sizable
        g = widget.frameGeometry()
        _send(ev, 'setFrame:', CGRect(0, 0, float(g.width()), float(g.height())))
        _send(frame, 'addSubview:positioned:relativeTo:', ctypes.c_void_p(ev), ctypes.c_long(-1), ctypes.c_void_p(view.value))
        _send(w, 'setOpaque:', ctypes.c_bool(False))
        _send(w, 'setBackgroundColor:', ctypes.c_void_p(_send(_cls('NSColor'), 'clearColor')))
        return ev
    except Exception:
        return None


def reveal(path):
    """Finder: select the file (or open the folder)."""
    if os.path.isdir(path):
        return subprocess.Popen(['open', path])
    return subprocess.Popen(['open', '-R', path])


# ---------------------------------------------------------------- hardware (no Qt, no torch)
def _sysctl(name):
    try:
        return subprocess.run(['/usr/sbin/sysctl', '-n', name], capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ''


def machine_arch():
    """'arm64' on Apple Silicon even when this process runs under Rosetta, else 'x86_64'."""
    if not IS_MAC:
        return platform.machine()
    if _sysctl('hw.optional.arm64') == '1':
        return 'arm64'
    return 'x86_64'


def memory_gb():
    try:
        return round(int(_sysctl('hw.memsize')) / 2 ** 30, 1)
    except ValueError:
        return 0.0


def chip_name():
    return _sysctl('machdep.cpu.brand_string') or platform.machine()


def macos_version():
    v = platform.mac_ver()[0] if IS_MAC else ''
    return tuple(int(x) for x in (v.split('.') + ['0', '0'])[:3] if x.isdigit()) if v else (0, 0, 0)


def strip_quarantine(path):
    """Files the app downloads itself are not quarantined (only browsers and apps that opt in
    with LSFileQuarantineEnabled tag downloads), but make sure: a quarantined engine Python
    would be stopped by Gatekeeper. Returns how many files carried the attribute."""
    if not IS_MAC or not os.path.exists(path):
        return 0
    try:
        out = subprocess.run(['/usr/bin/xattr', '-r', '-l', path], capture_output=True, text=True, timeout=300).stdout
        n = out.count('com.apple.quarantine')
        if n:
            subprocess.run(['/usr/bin/xattr', '-r', '-d', 'com.apple.quarantine', path], capture_output=True, timeout=300)
        return n
    except Exception:
        return 0


# ---------------------------------------------------------------- cross-platform wording / folder opening
FOLDER_LABEL = 'Reveal in Finder' if IS_MAC else 'Open folder'
MOD = '⌘' if IS_MAC else 'Ctrl+'


def open_folder(path):
    """Show a folder (or a file in its folder): Finder reveal on macOS, the file manager elsewhere."""
    if IS_MAC and path and os.path.exists(path):
        try:
            reveal(path)
            return True
        except OSError:
            pass
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    return QDesktopServices.openUrl(QUrl.fromLocalFile(path if os.path.isdir(path) else os.path.dirname(path)))


def disable_auto_fullscreen_item():
    """AppKit adds its own "Enter Full Screen" to the View menu; the app adds one with ⌃⌘F itself."""
    if not IS_MAC:
        return False
    try:
        d = _send(_cls('NSUserDefaults'), 'standardUserDefaults')
        _send(d, 'setBool:forKey:', ctypes.c_bool(False), ctypes.c_void_p(_nsstring('NSFullScreenMenuItemEverywhere')))
        return True
    except Exception:
        return False
