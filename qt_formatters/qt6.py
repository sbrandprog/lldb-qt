"""Форматтеры для структур Qt6.

Qt6 использует единый QArrayDataPointer<T> с прямым указателем на данные:

    template <class T> struct QArrayDataPointer {
        QTypedArrayData<T> *d;
        T *ptr;
        qsizetype size;
    };

Это проще Qt5: данные лежат по ptr, длина в size, offset не используется.
QString использует char16_t, QByteArray — char.
"""

from . import common, misc
from .providers import ListSynthetic

import lldb

# ---------------------------------------------------------------------------
# Хелперы для QArrayDataPointer
# ---------------------------------------------------------------------------


def _adp_read(value):
    """Возвращает (data_addr, size) из поля d типа QArrayDataPointer<T>."""
    d = common.get_child_by_name(common.raw_value(value), "d")
    if not d or not d.IsValid():
        return None, None
    ptr = common.get_child_by_name(d, "ptr")
    size = common.get_child_by_name(d, "size")
    data_addr = common.read_pointer(ptr) if ptr else None
    size_v = common.read_pointer(size) if size else 0
    return data_addr, size_v


def format_qstring(valobj, internal_dict):
    """Summary для QString (Qt6): UTF-16 -> строка."""
    data_addr, size = _adp_read(valobj)
    if not isinstance(size, int) or size is None or size < 0:
        return "<invalid>"
    if size == 0 or not data_addr:
        return '""'
    proc = valobj.GetProcess()
    err = lldb.SBError()
    count = min(int(size) * 2, 1 << 20)
    buf = proc.ReadMemory(data_addr, count, err)
    if not buf or err.Fail():
        return "<unreadable>"
    raw = buf.decode("utf-16-le", errors="replace")
    if len(raw) > 256:
        raw = raw[:256] + "…"
    return repr(raw)


def format_qbytearray(valobj, internal_dict):
    """Summary для QByteArray (Qt6): ASCII/hex."""
    data_addr, size = _adp_read(valobj)
    if not isinstance(size, int) or size is None or size < 0:
        return "<invalid>"
    if size == 0 or not data_addr:
        return '""'
    proc = valobj.GetProcess()
    err = lldb.SBError()
    buf = proc.ReadMemory(data_addr, int(size), err)
    if not buf or err.Fail():
        return "<unreadable>"
    try:
        s = buf.decode("ascii", errors="replace")
    except Exception:
        s = repr(buf.hex())
    if len(s) > 128:
        s = s[:128] + "…"
    return repr(s) if s else '""'


# ---------------------------------------------------------------------------
# QList / контейнеры (Qt6)
# ---------------------------------------------------------------------------


class QListSynthetic(ListSynthetic):
    """Synthetic для QList<T> / QVector / QStringList в Qt6."""

    def _adp(self):
        d = common.get_child_by_name(common.raw_value(self.value), "d")
        if not d or not d.IsValid():
            return None
        return d

    def _elements(self):
        d = self._adp()
        if d is None:
            return None, 0
        ptr = common.get_child_by_name(d, "ptr")
        size = common.get_child_by_name(d, "size")
        data_addr = common.read_pointer(ptr) if ptr else None
        size_v = common.read_pointer(size) if size else 0
        if not isinstance(size_v, int):
            size_v = 0
        return data_addr, size_v

    def count(self):
        _, n = self._elements()
        return n if n and n > 0 else 0

    def item_at(self, index):
        data_addr, n = self._elements()
        if data_addr is None:
            return None
        base = common.raw_value(self.value)
        if base is None:
            return None
        elem_type = common.get_template_arg_type(base.GetType())
        if not elem_type or not elem_type.IsValid():
            return None
        size = elem_type.GetByteSize()
        target = self.value.GetTarget()
        addr = data_addr + index * size
        sbaddr = lldb.SBAddress(addr, target)
        return target.CreateValueFromAddress(f"[{index}]", sbaddr, elem_type)


def _summary_qlist(valobj, internal_dict):
    """Summary для QList<T> Qt6."""
    try:
        synth = QListSynthetic(common.raw_value(valobj), internal_dict)
        n = synth.count()
        if n == 0:
            return "[]"
        items = []
        for i in range(min(n, 8)):
            v = synth.item_at(i)
            if v is None:
                continue
            if v.IsValid():
                s = v.GetSummary()
                items.append(s if s else (v.GetValue() or "?"))
            else:
                items.append("?")
        tail = "…" if n > 8 else ""
        return "size=" + str(n) + " [" + ", ".join(items) + tail + "]"
    except Exception:
        return "<unreadable>"


# ---------------------------------------------------------------------------
# QHash / QMap (Qt6) — summary с размером
# ---------------------------------------------------------------------------


def format_qhash(valobj, internal_dict):
    """Summary для QHash<K,V> Qt6: size=N (элементы не раскрываются)."""
    d = common.get_child_by_name(common.raw_value(valobj), "d")
    if not d:
        return "<invalid>"
    dd = d.Dereference()
    size = None
    if dd and dd.IsValid():
        s = common.get_child_by_name(dd, "size")
        if s and s.IsValid():
            size = s.GetValueAsUnsigned()
    if size is None:
        return "<unavailable>"
    return f"size={size}"


def format_qmap(valobj, internal_dict):
    """Summary для QMap<K,V> Qt6.

    В Qt6 QMap построен поверх std::map, что требует обхода красно-чёрного
    дерева libstdc++. Пока выводим размер (если доступен) либо пометку.
    """
    d = common.get_child_by_name(common.raw_value(valobj), "d")
    if not d:
        return "<invalid>"
    try:
        wrapper = d.GetChildAtIndex(0)
        t = common.get_child_by_name(wrapper, "t")
        if t and t.IsValid():
            qm = t.Dereference()
            if qm and qm.IsValid():
                m = common.get_child_by_name(qm, "m")
                if m and m.IsValid():
                    mt = common.get_child_by_name(m, "_M_t")
                    mi = common.get_child_by_name(mt, "_M_impl") if mt else None
                    nc = common.get_child_by_name(mi, "_M_node_count") if mi else None
                    if nc and nc.IsValid():
                        return f"size={nc.GetValueAsUnsigned()}"
    except Exception:
        pass
    return "<unavailable>"


# ---------------------------------------------------------------------------
# QVariant
# ---------------------------------------------------------------------------


def format_qvariant(valobj, internal_dict):
    """Summary для QVariant Qt6 (базовый).

    Qt6 хранит данные в inline union и метатип в packedType-битах, что требует
    детального разбора QMetaType. Показываем только null/не-null состояние;
    детальный разбор значений — см. TODO.
    """
    d = common.get_child_by_name(common.raw_value(valobj), "d")
    if not d:
        return "<invalid>"
    is_null = common.get_child_by_name(d, "is_null")
    if is_null and is_null.IsValid() and is_null.GetValueAsUnsigned():
        return "<null>"
    return "<variant>"


# ---------------------------------------------------------------------------
# Регистрация
# ---------------------------------------------------------------------------


def register(debugger, internal_dict, rs, rh):
    m = __name__  # "qt_formatters.qt6"
    rs(debugger, ["QString"], f"{m}.format_qstring")
    rs(debugger, ["QByteArray"], f"{m}.format_qbytearray")

    # QList<T>, QVector<T>, QStringList
    rh(debugger, ["(QList<.*>|QVector<.*>|QStringList)$"], f"{m}.QListSynthetic")
    rs(debugger, ["(QList<.*>|QVector<.*>|QStringList)$"], f"{m}._summary_qlist", expand=True)

    # Дата / время / геометрия (общие на обе версии форматтеры)
    mm = misc.__name__
    rs(debugger, ["QDate"], f"{mm}.format_qdate")
    rs(debugger, ["QTime"], f"{mm}.format_qtime")
    rs(debugger, ["QSize"], f"{mm}.format_qsize")
    rs(debugger, ["QPoint"], f"{mm}.format_qpoint")
    rs(debugger, ["QRect"], f"{mm}.format_qrect")
    rs(debugger, ["QLine"], f"{mm}.format_qline")

    # Ассоциативные контейнеры / QVariant
    rs(debugger, ["QHash<.*>$"], f"{m}.format_qhash")
    rs(debugger, ["QMap<.*>$"], f"{m}.format_qmap")
    rs(debugger, ["QVariant"], f"{m}.format_qvariant")
