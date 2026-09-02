"""Общий версия-независимый обход QHash.

QSet<T> — обёртка над QHash<T, QHashDummyValue> (член q_hash), а QHash<K,V>
сам является QHash. Обоим нужен обход узлов, чтобы выдать ключи (QSet) или
пары ключ/значение (QHash). Раскладка различается по версиям Qt:

  - Qt5: d — QHashData* (buckets/numBuckets); узлы QHashNode<Key,T> связаны
    списками по каждому bucket; сенсорная нода = адрес самого QHashData.
  - Qt6: d — QHashPrivate::Data<Node>* (numBuckets/spans); таблица разбита на
    Spans по 128 buckets (offsets-массив байт + массив entries с узлами).

iter_hash_nodes выдаёт типизированные SBValue-узлы, из которых вызывающий
читает key/value через GetChildMemberWithName, поэтому смещения полей не
считаются вручную.
"""

from . import common

import lldb


def _qt5_nodes(q_hash, d, dd, target, proc):
    """Генератор узлов QHashNode в раскладке Qt5.

    Тип узла берём из union-члена e (QHashNode<Key,T>*), чтобы читать поля
    узла через систему типов lldb.
    """
    d_addr = common.read_pointer(d)
    if not d_addr:
        return
    buckets = common.get_child_by_name(dd, "buckets")
    num = common.get_child_by_name(dd, "numBuckets")
    buckets_addr = common.read_pointer(buckets)
    nb = num.GetValueAsUnsigned() if num and num.IsValid() else 0
    if not buckets_addr or not nb:
        return
    e = common.get_child_by_name(q_hash, "e")
    node_type = None
    if e is not None and e.IsValid() and e.GetType().IsValid():
        node_type = e.GetType().GetPointeeType()
    if node_type is None or not node_type.IsValid():
        return
    step = target.addr_size
    err = lldb.SBError()
    for i in range(int(nb)):
        node_ptr = proc.ReadPointerFromMemory(buckets_addr + i * step, err)
        if err.Fail() or not node_ptr:
            continue
        guard = 0
        while node_ptr and node_ptr != d_addr and guard < 1024:
            node = target.CreateValueFromAddress("node", lldb.SBAddress(node_ptr, target), node_type)
            if node is None or not node.IsValid():
                break
            yield node
            nxt = node.GetChildMemberWithName("next")
            node_ptr = nxt.GetValueAsUnsigned() if nxt is not None and nxt.IsValid() else 0
            guard += 1


def _qt6_nodes(d, dd, target, proc):
    """Генератор узлов QHashPrivate::Node в раскладке Qt6.

    Тип узла достаём как первый шаблонный аргумент Data<Node> (d — указатель
    на Data). Его GetByteSize даёт шаг между узлами (entries хранит узлы
    подряд). Раскладка Span: offsets[128] по смещению 0, entries по смещению 128.
    """
    node_type = d.GetType().GetPointeeType().GetTemplateArgumentType(0)
    if node_type is None or not node_type.IsValid():
        return
    node_size = node_type.GetByteSize()
    if not node_size:
        return
    num = common.get_child_by_name(dd, "numBuckets")
    spans = common.get_child_by_name(dd, "spans")
    nb = num.GetValueAsUnsigned() if num and num.IsValid() else 0
    spans_addr = common.read_pointer(spans)
    if not nb or not spans_addr:
        return
    span_type = spans.GetType().GetPointeeType() if spans.GetType().IsValid() else None
    if span_type is not None and span_type.IsValid():
        span_size = span_type.GetByteSize()
    else:
        # Fallback по раскладке Span: offsets[128] + указатель entries +
        # allocated/nextFree (2 байта), выравнивание по размеру указателя.
        step = target.addr_size
        span_size = (128 + step + 2 + step - 1) // step * step
    err = lldb.SBError()
    n_spans = int(nb) >> 7
    for s in range(n_spans):
        span_addr = spans_addr + s * span_size
        entries_addr = proc.ReadPointerFromMemory(span_addr + 128, err)
        if err.Fail() or not entries_addr:
            continue
        for i in range(128):
            buf = proc.ReadMemory(span_addr + i, 1, err)
            if err.Fail() or not buf:
                continue
            off = buf[0]
            if off == 0xFF:
                continue
            node = target.CreateValueFromAddress(
                "node", lldb.SBAddress(entries_addr + off * node_size, target), node_type
            )
            if node is not None and node.IsValid():
                yield node


def _data(q_hash):
    """Возвращает (raw, d, dd) для QHash (или None, если раскладка не распознана)."""
    raw = common.raw_value(q_hash)
    if raw is None or not raw.IsValid():
        return None
    d = common.get_child_by_name(raw, "d")
    if d is None or not d.IsValid():
        return None
    if not common.read_pointer(d):
        # Пустой QHash/QSet в Qt6 имеет d == nullptr; Dereference() по
        # нулевому указателю вернёт значение по LLDB_INVALID_ADDRESS.
        return None
    dd = d.Dereference()
    if dd is None or not dd.IsValid():
        return None
    return raw, d, dd


def hash_size(q_hash):
    """Число элементов QHash из d->size (Qt5 QHashData.size / Qt6 Data.size).

    Возвращает None, если раскладка не распознана.
    """
    raw = common.raw_value(q_hash)
    if raw is None or not raw.IsValid():
        return None
    d = common.get_child_by_name(raw, "d")
    if d is None or not d.IsValid():
        return None
    if not common.read_pointer(d):
        return 0
    dd = d.Dereference()
    if dd is None or not dd.IsValid():
        return None
    s = common.get_child_by_name(dd, "size")
    if s is None or not s.IsValid():
        return None
    return s.GetValueAsUnsigned()


def iter_hash_nodes(q_hash):
    """Генератор типизированных узлов QHash (SBValue) для обеих версий Qt.

    q_hash — SBValue самого QHash (для QSet это член q_hash). Диспетчеризация
    по наличию поля buckets (Qt5) или spans (Qt6) у разыменованного d.
    """
    info = _data(q_hash)
    if info is None:
        return
    raw, d, dd = info
    target = raw.GetTarget()
    proc = raw.GetProcess()
    if common.get_child_by_name(dd, "buckets"):
        yield from _qt5_nodes(raw, d, dd, target, proc)
    else:
        yield from _qt6_nodes(d, dd, target, proc)
