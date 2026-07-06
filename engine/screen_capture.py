"""
Screen capture for Xenia emulator using Win32 PrintWindow.

Uses PrintWindow API to capture the window content directly, even when
the window is behind other windows or partially obscured. Falls back to
MSS screen-region capture if PrintWindow fails.
"""

import ctypes
import ctypes.wintypes
import numpy as np
import cv2
import time


# Win32 constants
PW_RENDERFULLCONTENT = 0x00000002
SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", ctypes.wintypes.WORD),
        ("biBitCount", ctypes.wintypes.WORD),
        ("biCompression", ctypes.wintypes.DWORD),
        ("biSizeImage", ctypes.wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", ctypes.wintypes.DWORD),
        ("biClrImportant", ctypes.wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", ctypes.wintypes.DWORD * 3),
    ]


def find_window(title_substring: str, timeout: int = 60, require_substring: str = None):
    """Find a window by title substring. Returns (hwnd, title, client_rect).

    Args:
        require_substring: If set, the window title must also contain this string.
    """
    import win32gui
    import win32con

    deadline = time.time() + timeout
    results = []

    while time.time() < deadline:
        results.clear()
        needle = title_substring.lower()
        req = require_substring.lower() if require_substring else None

        def callback(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if not title:
                    return
                t = title.lower()
                if t == needle or (t.startswith(needle) and len(t) > len(needle)
                                   and t[len(needle)] in (' ', '(')):
                    if req and req not in t:
                        return  # Skip windows that don't contain required substring
                    results.append((hwnd, title))

        win32gui.EnumWindows(callback, None)
        if results:
            break
        remaining = int(deadline - time.time())
        print(f"Waiting for '{title_substring}' window... ({remaining}s remaining)")
        time.sleep(2)

    if not results:
        raise RuntimeError(
            f"No visible window found matching '{title_substring}' after {timeout}s.")

    hwnd, title = results[0]
    print(f"Found window: '{title}' (hwnd={hwnd})")

    # Get client area dimensions
    rect = win32gui.GetClientRect(hwnd)
    width = rect[2] - rect[0]
    height = rect[3] - rect[1]
    print(f"Capture region: {width}x{height} (client area)")

    return hwnd, title, width, height


def capture_window(hwnd, width, height):
    """Capture window content using PrintWindow (works even when occluded).

    Returns BGR numpy array or None on failure.
    """
    # Get window DC
    hwnd_dc = user32.GetWindowDC(hwnd)
    if not hwnd_dc:
        return None

    try:
        # Create compatible DC and bitmap
        mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
        if not mem_dc:
            return None

        try:
            # We need the full window size (including title bar) for PrintWindow
            import win32gui
            win_rect = win32gui.GetWindowRect(hwnd)
            win_w = win_rect[2] - win_rect[0]
            win_h = win_rect[3] - win_rect[1]

            bitmap = gdi32.CreateCompatibleBitmap(hwnd_dc, win_w, win_h)
            if not bitmap:
                return None

            try:
                old_bmp = gdi32.SelectObject(mem_dc, bitmap)

                # PrintWindow captures the window content even when behind other windows
                result = user32.PrintWindow(hwnd, mem_dc, PW_RENDERFULLCONTENT)
                if not result:
                    # Fallback: try without PW_RENDERFULLCONTENT
                    result = user32.PrintWindow(hwnd, mem_dc, 0)

                if not result:
                    return None

                # Now extract just the client area
                # Client area offset within the window
                client_rect = win32gui.GetClientRect(hwnd)
                client_origin = win32gui.ClientToScreen(hwnd, (0, 0))
                window_origin = (win_rect[0], win_rect[1])
                offset_x = client_origin[0] - window_origin[0]
                offset_y = client_origin[1] - window_origin[1]

                # Set up bitmap info for GetDIBits
                bmi = BITMAPINFO()
                bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
                bmi.bmiHeader.biWidth = win_w
                bmi.bmiHeader.biHeight = -win_h  # Negative = top-down
                bmi.bmiHeader.biPlanes = 1
                bmi.bmiHeader.biBitCount = 32
                bmi.bmiHeader.biCompression = 0  # BI_RGB

                # Allocate buffer
                buf = ctypes.create_string_buffer(win_w * win_h * 4)
                gdi32.GetDIBits(mem_dc, bitmap, 0, win_h,
                                buf, ctypes.byref(bmi), DIB_RGB_COLORS)

                # Convert to numpy (BGRA)
                img = np.frombuffer(buf, dtype=np.uint8).reshape(win_h, win_w, 4)

                # Crop to client area
                client_w = client_rect[2] - client_rect[0]
                client_h = client_rect[3] - client_rect[1]
                img = img[offset_y:offset_y + client_h,
                          offset_x:offset_x + client_w]

                # Convert BGRA to BGR
                return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

            finally:
                gdi32.SelectObject(mem_dc, old_bmp)
                gdi32.DeleteObject(bitmap)
        finally:
            gdi32.DeleteDC(mem_dc)
    finally:
        user32.ReleaseDC(hwnd, hwnd_dc)


class ScreenCapture:
    """
    Captures the Xenia window content using Win32 PrintWindow API.
    Works even when the window is behind other windows or partially obscured.

    Returns frames as (success, numpy_bgr_frame) tuples.
    """

    def __init__(self, monitor: int = 1, region: dict = None,
                 width: int = 1280, height: int = 720,
                 window_title: str = None, require_substring: str = None):
        self.target_width = width
        self.target_height = height
        self.hwnd = None
        self.client_w = 0
        self.client_h = 0

        if window_title:
            self.hwnd, title, self.client_w, self.client_h = find_window(
                window_title, require_substring=require_substring)

        # Fallback: MSS for non-window captures
        self._mss = None
        self._mss_region = region

    def read(self) -> tuple:
        """Capture a frame. Returns (True, bgr_frame) or (False, None)."""
        try:
            if self.hwnd:
                frame = capture_window(self.hwnd, self.client_w, self.client_h)
                if frame is not None:
                    # Resize if needed
                    h, w = frame.shape[:2]
                    if (self.target_width and self.target_height
                            and (w != self.target_width or h != self.target_height)):
                        frame = cv2.resize(frame, (self.target_width, self.target_height))
                    return (True, frame)

            # Fallback to MSS
            return self._mss_read()
        except Exception as e:
            print(f"ScreenCapture error: {e}")
            return (False, None)

    def _mss_read(self):
        """Fallback MSS capture."""
        import mss
        if self._mss is None:
            self._mss = mss.mss()
        try:
            if self._mss_region:
                grab_area = self._mss_region
            else:
                grab_area = self._mss.monitors[1]
            screenshot = self._mss.grab(grab_area)
            frame = np.array(screenshot)
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            h, w = frame.shape[:2]
            if (self.target_width and self.target_height
                    and (w != self.target_width or h != self.target_height)):
                frame = cv2.resize(frame, (self.target_width, self.target_height))
            return (True, frame)
        except Exception:
            return (False, None)

    def release(self):
        """Release resources."""
        if self._mss:
            self._mss.close()
            self._mss = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.release()
