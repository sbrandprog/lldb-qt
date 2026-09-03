"""Версия-независимый обход QMap.

QMap<K,V> и QMultiMap<K,V> в Qt5 и Qt6 устроены по-разному:

  - Qt5: d — QMapData<K,V>*; внутри красно-чёрное дерево из QMapNode<K,V>
    (header.left — корень, узлы с полями left/right/key/value).
  - Qt6: d — QExplicitlySharedDataPointerV2<QMapData<std::map<K,V>>>;
    std::map оборачивает std::_Rb_tree с _M_header/_M_node_count, узлы
    _Rb_tree_node<std::pair<const K,V>>, пара лежит в _M_value_field.

iter_map_nodes выдаёт узлы-записи (SBValue) в отсортированном порядке ключей
(in-order обход): QMapNode<K,V> в Qt5 (поля key/value), std::pair<const K,V>
в Qt6 (поля first/second). Единый доступ к ключу/значению — через entry_key /
entry_value, которые понимают оба варианта.
"""

from . import common

import lldb


def _read_ptr(value, field):
    """Читает поле-указатель узла как int (или 0)."""
    c = common.get_child_by_name(value, field)
    return common.read_pointer(c) or 0


def _qt5_mapdata(valobj):
    """Возвращает (dd, node_type, size) для Qt5 QMap, иначе None.

    Распознавание раскладки — по типу d (указатель) и разрешимости node_type.
    Пустой QMap (d == nullptr) даёт size == 0; dd в этом случае может быть
    невалидным, поэтому его использует только _qt5_nodes (для непустого дерева).
    """
    raw = common.raw_value(valobj)
    if raw is None or not raw.IsValid():
        return None
    d = common.find_deep(raw, "d")
    if d is None or not d.IsValid() or not d.GetType().IsPointerType():
        return None
    pointee = d.GetType().GetPointeeType()
    if pointee is None or not pointee.IsValid():
        return None
    key_type = pointee.GetTemplateArgumentType(0)
    val_type = pointee.GetTemplateArgumentType(1)
    if key_type is None or val_type is None or not key_type.IsValid() or not val_type.IsValid():
        return None
    node_type = valobj.GetTarget().FindFirstType(f"QMapNode<{key_type.GetName()}, {val_type.GetName()}>")
    if node_type is None or not node_type.IsValid():
        return None
    ptr = common.read_pointer(d)
    if not ptr:
        return None, node_type, 0
    dd = d.Dereference()
    if dd is None or not dd.IsValid():
        return None
    s = common.get_child_by_name(dd, "size")
    if s is None or not s.IsValid():
        return None
    return dd, node_type, s.GetValueAsUnsigned()


def _qt6_mapdata(valobj):
    """Возвращает (header, pair_type, size) для Qt6 QMap, иначе None.

    Распознавание требует все служебные поля std::map (_M_t, _M_header,
    _M_node_count) — это libstdc++-имена; при иной стандартной библиотеке
    (libc++) раскладка не распознаётся и возвращается None, чтобы map_size
    сигнализировал <invalid>, а не 0.
    """
    raw = common.raw_value(valobj)
    if raw is None or not raw.IsValid():
        return None
    d = common.find_deep(raw, "d")
    if d is None or not d.IsValid() or d.GetType().IsPointerType():
        return None
    rep = common.find_deep(d, "_M_t")
    if rep is None or not rep.IsValid():
        return None
    pair_type_name = rep.GetType().GetTemplateArgumentType(1).GetName()
    pair_type = valobj.GetTarget().FindFirstType(pair_type_name)
    if pair_type is None or not pair_type.IsValid():
        return None
    header = common.find_deep(d, "_M_header")
    if header is None or not header.IsValid():
        return None
    nc = common.find_deep(d, "_M_node_count")
    if nc is None or not nc.IsValid():
        return None
    return header, pair_type, nc.GetValueAsUnsigned()


def _qt5_nodes(valobj, dd, node_type):
    """Генератор QMapNode<K,V> в отсортированном порядке (Qt5)."""
    target = valobj.GetTarget()
    header = common.get_child_by_name(dd, "header")
    if header is None or not header.IsValid():
        return
    root = _read_ptr(header, "left")
    if not root:
        return

    def make(addr):
        return target.CreateValueFromAddress("node", lldb.SBAddress(addr, target), node_type)

    stack = []
    cur = root
    while cur:
        stack.append(cur)
        cur = _read_ptr(make(cur), "left")
    while stack:
        addr = stack.pop()
        node = make(addr)
        if node is not None and node.IsValid():
            yield node
        cur = _read_ptr(node, "right")
        while cur:
            stack.append(cur)
            cur = _read_ptr(make(cur), "left")


def _qt6_nodes(valobj, header, pair_type):
    """Генератор std::pair<const K,V> в отсортированном порядке (Qt6)."""
    target = valobj.GetTarget()
    node_base_type = header.GetType()
    base_size = node_base_type.GetByteSize()
    header_addr = header.GetLoadAddress()
    if not header_addr or not base_size:
        return

    def make_base(addr):
        return target.CreateValueFromAddress("base", lldb.SBAddress(addr, target), node_base_type)

    root = _read_ptr(header, "_M_parent")
    stack = []
    cur = root
    while cur and cur != header_addr:
        stack.append(cur)
        cur = _read_ptr(make_base(cur), "_M_left")
    while stack:
        addr = stack.pop()
        pair = target.CreateValueFromAddress("pair", lldb.SBAddress(addr + base_size, target), pair_type)
        if pair is not None and pair.IsValid():
            yield pair
        cur = _read_ptr(make_base(addr), "_M_right")
        while cur and cur != header_addr:
            stack.append(cur)
            cur = _read_ptr(make_base(cur), "_M_left")


def _mapdata(valobj):
    """Общий диспетчер раскладки QMap: ("qt5"|"qt6", info) или None.

    Единая точка распознавания, чтобы map_size и iter_map_nodes не могли
    разойтись: если раскладка не распознана, обе функции согласованно
    возвращают None / ничего.
    """
    info = _qt5_mapdata(valobj)
    if info is not None:
        return "qt5", info
    info = _qt6_mapdata(valobj)
    if info is not None:
        return "qt6", info
    return None


def iter_map_nodes(valobj):
    """Генератор узлов-записей QMap в отсортированном порядке.

    Qt5 — QMapNode<K,V> (key/value), Qt6 — std::pair<const K,V> (first/second).
    Диспетчеризация по типу члена d (указатель в Qt5, shared-data-обёртка в Qt6).
    """
    md = _mapdata(valobj)
    if md is None:
        return
    kind, info = md
    if kind == "qt5":
        dd, node_type, _size = info
        if dd is not None and dd.IsValid():
            yield from _qt5_nodes(valobj, dd, node_type)
    else:
        header, pair_type, _size = info
        yield from _qt6_nodes(valobj, header, pair_type)


def map_size(valobj):
    """Число элементов QMap (Qt5: d->size, Qt6: std::map _M_node_count).

    Возвращает None, если раскладка не распознана (в т.ч. при чужой стандартной
    библиотеке), иначе 0 для пустого и фактический размер для непустого QMap.
    """
    md = _mapdata(valobj)
    if md is None:
        return None
    _kind, info = md
    return info[2]


def entry_key(node):
    """SBValue ключа узла-записи (Qt5 key, Qt6 first) или None."""
    k = common.get_child_by_name(node, "key")
    if k is None or not k.IsValid():
        k = common.get_child_by_name(node, "first")
    return k if k is not None and k.IsValid() else None


def entry_value(node):
    """SBValue значения узла-записи (Qt5 value, Qt6 second) или None."""
    v = common.get_child_by_name(node, "value")
    if v is None or not v.IsValid():
        v = common.get_child_by_name(node, "second")
    return v if v is not None and v.IsValid() else None
