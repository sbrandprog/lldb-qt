"""Форматтеры геометрических типов.

Эти типы устроены в Qt5 и Qt6 практически одинаково:
  - QSize/QPoint:   поля wd/ht/xp/yp (в Qt5 напрямую int, в Qt6 через m_i)
  - QRect:  x1, y1, x2, y2 (прямые int либо обёртки m_i)
  - QLine:  QPoint pt1, pt2

Поэтому форматтеры общие для обеих версий.
"""

from . import common


def _int_of(v):
    """Читает целое значение поля, обрабатывая Qt5 (прямой int)
    и Qt6 (обёртка c м_i). Знак учитывается."""
    if v is None or not v.IsValid():
        return None
    mi = common.get_child_by_name(v, "m_i")
    src = mi if mi and mi.IsValid() else v
    return src.GetValueAsSigned()


def _read_qsize_hw(valobj):
    wd = common.get_child_by_name(valobj, "wd")
    ht = common.get_child_by_name(valobj, "ht")
    w = _int_of(wd) if wd else None
    h = _int_of(ht) if ht else None
    return w, h


def format_qsize(valobj, internal_dict):
    """Summary для QSize: WxH."""
    w, h = _read_qsize_hw(valobj)
    if w is None or h is None:
        return "<invalid>"
    return f"{w}x{h}"


def _qpoint_xy(v):
    xp = common.get_child_by_name(v, "xp")
    yp = common.get_child_by_name(v, "yp")
    return (_int_of(xp) if xp else None), (_int_of(yp) if yp else None)


def format_qpoint(valobj, internal_dict):
    """Summary для QPoint: (x, y)."""
    x, y = _qpoint_xy(valobj)
    if x is None or y is None:
        return "<invalid>"
    return f"({x}, {y})"


def format_qrect(valobj, internal_dict):
    """Summary для QRect: (x, y, WxH)."""
    x1v = common.get_child_by_name(valobj, "x1")
    y1v = common.get_child_by_name(valobj, "y1")
    x2v = common.get_child_by_name(valobj, "x2")
    y2v = common.get_child_by_name(valobj, "y2")
    x1 = _int_of(x1v) if x1v else None
    y1 = _int_of(y1v) if y1v else None
    x2 = _int_of(x2v) if x2v else None
    y2 = _int_of(y2v) if y2v else None
    if x1 is None or y1 is None or x2 is None or y2 is None:
        return "<invalid>"
    w, h = int(x2) - int(x1) + 1, int(y2) - int(y1) + 1
    return f"({x1}, {y1}, {w}x{h})"


def _qreal_of(v):
    """Читает qreal (double) поле. В Qt5 и Qt6 qreal — обычный double."""
    if v is None or not v.IsValid():
        return None
    val = v.GetValue()
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _fmt_qreal(v):
    """Форматирует qreal: отбрасывает лишние нули через :g, но с точностью,
    достаточной для round-trip double (16 значащих цифр)."""
    if v is None:
        return "?"
    return f"{v:.16g}"


def format_qline(valobj, internal_dict):
    """Summary для QLine: (x1, y1) -> (x2, y2)."""
    p1 = common.get_child_by_name(valobj, "pt1")
    p2 = common.get_child_by_name(valobj, "pt2")
    if p1 and p1.IsValid() and p2 and p2.IsValid():
        x1, y1 = _qpoint_xy(p1)
        x2, y2 = _qpoint_xy(p2)
        if x1 is not None and y1 is not None and x2 is not None and y2 is not None:
            return f"({x1}, {y1}) -> ({x2}, {y2})"
    return "<invalid>"


def _qsizef_wh(valobj):
    wd = common.get_child_by_name(valobj, "wd")
    ht = common.get_child_by_name(valobj, "ht")
    w = _qreal_of(wd) if wd else None
    h = _qreal_of(ht) if ht else None
    return w, h


def _qpointf_xy(valobj):
    xp = common.get_child_by_name(valobj, "xp")
    yp = common.get_child_by_name(valobj, "yp")
    return (_qreal_of(xp) if xp else None), (_qreal_of(yp) if yp else None)


def format_qsizef(valobj, internal_dict):
    """Summary для QSizeF: WxH."""
    w, h = _qsizef_wh(valobj)
    if w is None or h is None:
        return "<invalid>"
    return f"{_fmt_qreal(w)}x{_fmt_qreal(h)}"


def format_qpointf(valobj, internal_dict):
    """Summary для QPointF: (x, y)."""
    x, y = _qpointf_xy(valobj)
    if x is None or y is None:
        return "<invalid>"
    return f"({_fmt_qreal(x)}, {_fmt_qreal(y)})"


def format_qrectf(valobj, internal_dict):
    """Summary для QRectF: (x, y, WxH)."""
    xp = common.get_child_by_name(valobj, "xp")
    yp = common.get_child_by_name(valobj, "yp")
    w = common.get_child_by_name(valobj, "w")
    h = common.get_child_by_name(valobj, "h")
    x = _qreal_of(xp) if xp else None
    y = _qreal_of(yp) if yp else None
    width = _qreal_of(w) if w else None
    height = _qreal_of(h) if h else None
    if x is None or y is None or width is None or height is None:
        return "<invalid>"
    return f"({_fmt_qreal(x)}, {_fmt_qreal(y)}, {_fmt_qreal(width)}x{_fmt_qreal(height)})"


def format_qlinef(valobj, internal_dict):
    """Summary для QLineF: (x1, y1) -> (x2, y2)."""
    p1 = common.get_child_by_name(valobj, "pt1")
    p2 = common.get_child_by_name(valobj, "pt2")
    if p1 and p1.IsValid() and p2 and p2.IsValid():
        x1, y1 = _qpointf_xy(p1)
        x2, y2 = _qpointf_xy(p2)
        if x1 is not None and y1 is not None and x2 is not None and y2 is not None:
            return f"({_fmt_qreal(x1)}, {_fmt_qreal(y1)}) -> ({_fmt_qreal(x2)}, {_fmt_qreal(y2)})"
    return "<invalid>"


DEFS = {
    "format_qsize": format_qsize,
    "format_qpoint": format_qpoint,
    "format_qrect": format_qrect,
    "format_qline": format_qline,
    "format_qsizef": format_qsizef,
    "format_qpointf": format_qpointf,
    "format_qrectf": format_qrectf,
    "format_qlinef": format_qlinef,
}
