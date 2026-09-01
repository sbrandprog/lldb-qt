"""Универсальные форматтеры дат/времени/геометрии.

Эти типы устроены в Qt5 и Qt6 практически одинаково:
  - QDate:  qint64 jd
  - QTime:  int mds
  - QSize/QPoint:   поля wd/ht/xp/yp (в Qt5 напрямую int, в Qt6 через m_i)
  - QRect:  x1, y1, x2, y2 (прямые int либо обёртки m_i)
  - QLine:  QPoint pt1, pt2

Поэтому форматтеры общие для обеих версий.
"""

from . import common


def _read_int_field(valobj, name):
    f = common.get_child_by_name(valobj, name)
    if not f or not f.IsValid():
        return None
    return f.GetValueAsUnsigned()


def _int_of(v):
    """Читает целое значение поля, обрабатывая Qt5 (прямой int)
    и Qt6 (обёртка c м_i). Знак учитывается."""
    if v is None or not v.IsValid():
        return None
    mi = common.get_child_by_name(v, "m_i")
    src = mi if mi and mi.IsValid() else v
    return src.GetValueAsSigned()


def _jdn_to_date(jdn):
    """Конверсия юлианского дня (QDate::toJulianDay) в (year, month, day)."""
    a = jdn + 32044
    b = (4 * a + 3) // 146097
    c = a - (146097 * b) // 4
    d = (4 * c + 3) // 1461
    e = c - (1461 * d) // 4
    m = (5 * e + 2) // 153
    day = e - (153 * m + 2) // 5 + 1
    month = m + 3 - 12 * (m // 10)
    year = 100 * b + d - 4800 + m // 10
    return year, month, day


def format_qdate(valobj, internal_dict):
    """Summary для QDate: YYYY-MM-DD."""
    jd = _read_int_field(valobj, "jd")
    if jd is None or jd == 0:
        return "<invalid>"
    y, m, d = _jdn_to_date(int(jd))
    return f"{y:04d}-{m:02d}-{d:02d}"


def format_qtime(valobj, internal_dict):
    """Summary для QTime: HH:MM:SS.mmm."""
    mds = _read_int_field(valobj, "mds")
    if mds is None:
        return "<invalid>"
    mds = int(mds)
    ms = mds % 1000
    total_s = mds // 1000
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


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
    """Summary для QRect: (x, y, w, h)."""
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
    return f"({x1}, {y1}, {w}, {h})"


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


DEFS = {
    "format_qdate": format_qdate,
    "format_qtime": format_qtime,
    "format_qsize": format_qsize,
    "format_qpoint": format_qpoint,
    "format_qrect": format_qrect,
    "format_qline": format_qline,
}
