"""Форматтеры для типов даты/времени (QDate, QTime, QDateTime).

Эти типы устроены в Qt5 и Qt6 практически одинаково:
  - QDate:  qint64 jd (юлианский день)
  - QTime:  int mds (миллисекунды с начала суток)
  - QDateTime: union Data с ShortData (inline) или QDateTimePrivate* (heap)

Поэтому форматтеры общие для обеих версий.
"""

import lldb

from . import common
from . import strings


def _read_int_field(valobj, name):
    f = common.get_child_by_name(valobj, name)
    if not f or not f.IsValid():
        return None
    return f.GetValueAsUnsigned()


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


_UNIX_EPOCH_JDN = 2440588


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


def _msecs_to_datetime(msecs):
    """Конвертирует миллисекунды с UTC-эпохи в (year, month, day, h, m, s, ms)."""
    ms_per_day = 86400000
    days = msecs // ms_per_day
    day_ms = msecs % ms_per_day
    jdn = days + _UNIX_EPOCH_JDN
    year, month, day = _jdn_to_date(jdn)
    h = day_ms // 3600000
    day_ms %= 3600000
    m = day_ms // 60000
    day_ms %= 60000
    s = day_ms // 1000
    ms = day_ms % 1000
    return year, month, day, h, m, s, ms


def _read_shortdata(d):
    """Читает ShortData inline-оптимизацию. Возвращает (status, msecs) или None."""
    data = common.get_child_by_name(d, "data")
    if not data or not data.IsValid():
        return None
    status_field = common.get_child_by_name(data, "status")
    msecs_field = common.get_child_by_name(data, "msecs")
    if not status_field or not status_field.IsValid():
        return None
    if not msecs_field or not msecs_field.IsValid():
        return None
    status = status_field.GetValueAsUnsigned()
    msecs = msecs_field.GetValueAsSigned()
    return status, msecs


def _read_private(d_ptr):
    """Читает QDateTimePrivate по указателю. Возвращает (status, msecs) или None.

    QDateTimePrivate — opaque-тип в debug info (lldb не может его разыменовать
    через Dereference()), поэтому читаем поля напрямую из памяти. Раскладка:
    QSharedData (4 байта refcount) → m_status (int) → m_msecs (qint64) →
    m_offsetFromUtc (int).
    """
    status = common.read_int_at(d_ptr, 4, size=4, signed=False)
    msecs = common.read_int_at(d_ptr, 8, size=8, signed=True)
    if status is None or msecs is None:
        return None
    return status, msecs


def _read_datetime(valobj):
    """Возвращает (is_valid, msecs, timespec) для QDateTime или None.

    timespec: 0=LocalTime, 1=UTC, 2=OffsetFromUTC, 3=TimeZone
    """
    raw = common.raw_value(valobj)
    if raw is None or not raw.IsValid():
        return None
    d = common.get_child_by_name(raw, "d")
    if d is None or not d.IsValid():
        return None

    data = common.get_child_by_name(d, "data")
    if data and data.IsValid():
        status_field = common.get_child_by_name(data, "status")
        if status_field and status_field.IsValid():
            if status_field.GetValueAsUnsigned() & 0x01:
                result = _read_shortdata(d)
                if result is None:
                    return None
                status, msecs = result
                timespec = (status >> 4) & 0x03
                is_valid = bool(status & 0x08)
                return is_valid, msecs, timespec

    d_ptr = common.get_child_by_name(d, "d")
    if d_ptr and d_ptr.IsValid():
        result = _read_private(d_ptr)
        if result is None:
            return None
        status, msecs = result
        timespec = (status >> 4) & 0x03
        is_valid = bool(status & 0x08)
        return is_valid, msecs, timespec

    return None


def _timespec_suffix(timespec, valobj):
    """Возвращает суффикс для timespec."""
    if timespec == 1:
        return "Z"
    if timespec == 2:
        raw = common.raw_value(valobj)
        d = common.get_child_by_name(raw, "d")
        d_ptr = common.get_child_by_name(d, "d")
        if d_ptr and d_ptr.IsValid():
            offset = common.read_int_at(d_ptr, 16, size=4, signed=True)
            if offset is not None:
                sign = "+" if offset >= 0 else "-"
                offset = abs(offset)
                h, m = offset // 3600, (offset % 3600) // 60
                return f"{sign}{h:02d}:{m:02d}"
    if timespec == 3:
        tz_id = _read_tz_id(valobj)
        if tz_id:
            return f"[{tz_id}]"
    return ""


def _read_tz_id(valobj):
    """Читает IANA-идентификатор часового пояса для QDateTime со spec TimeZone.

    Раскладка (64-bit): в QDateTimePrivate поле m_timeZone лежит по смещению 24
    (после ref@0, m_status@4, m_msecs@8, m_offsetFromUtc@16), это QTimeZone —
    union из QTimeZonePrivate* (heap, для TimeZone) и ShortData. Сам
    QTimeZonePrivate полиморфен: vtable@0, QSharedData.ref@8, m_id (QByteArray)@16.
    Возвращает строку id или None при любом сбое раскладки.
    """
    raw = common.raw_value(valobj)
    d = common.get_child_by_name(raw, "d")
    d_ptr = common.get_child_by_name(d, "d")
    if not d_ptr or not d_ptr.IsValid():
        return None
    tz_priv = common.read_int_at(d_ptr, 24, size=8, signed=False)
    if tz_priv is None or not tz_priv:
        return None
    target = d_ptr.GetTarget()
    if target is None:
        return None
    ba_type = target.FindFirstType("QByteArray")
    if ba_type is None or not ba_type.IsValid():
        return None
    ba = d_ptr.CreateValueFromAddress("m_id", tz_priv + 16, ba_type)
    if ba is None or not ba.IsValid():
        return None
    data_addr, size = strings._string_data(ba)
    if size is None or size <= 0 or not data_addr:
        return None
    proc = valobj.GetProcess()
    err = lldb.SBError()
    buf = proc.ReadMemory(data_addr, int(size), err)
    if not buf or err.Fail():
        return None
    try:
        return buf.decode("ascii", errors="replace")
    except Exception:
        return None


def format_qdatetime(valobj, internal_dict):
    """Summary для QDateTime: YYYY-MM-DDTHH:MM:SS.mmm[Z|+HH:MM]."""
    info = _read_datetime(valobj)
    if info is None:
        return "<invalid>"
    is_valid, msecs, timespec = info
    if not is_valid:
        return "<invalid>"
    year, month, day, h, m, s, ms = _msecs_to_datetime(msecs)
    suffix = _timespec_suffix(timespec, valobj)
    return f"{year:04d}-{month:02d}-{day:02d}T{h:02d}:{m:02d}:{s:02d}.{ms:03d}{suffix}"
