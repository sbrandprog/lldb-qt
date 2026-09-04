"""Версия-независимые summary и synthetic для ассоциативных контейнеров."""

from itertools import islice

from . import common
from . import hash as hash_mod
from . import map as map_mod
from .providers import IterSynthetic, build_values

import lldb


def _format_items(size, entries):
    """Собирает строку 'size=N [(k: v), ...]' из итератора пар (k, v)."""
    if size == 0:
        return "[]"
    items = []
    for k, v in islice(entries, 8):
        items.append(f"({common.item_summary(k)}: {common.item_summary(v)})")
    tail = "…" if size > 8 else ""
    return "size=" + str(size) + " [" + ", ".join(items) + tail + "]"


def format_qhash(valobj, internal_dict):
    """Summary для QHash<K,V>: size=N [(k: v), ...].

    Пары ключ/значение читаются через общий обход hash.hash_layout
    (Qt5 — buckets/связанные списки, Qt6 — spans). Порядок не детерминирован.
    """
    try:
        info = hash_mod.hash_layout(valobj)
        if info is None:
            return "<invalid>"
        size, nodes = info
        entries = ((hash_mod.node_key(n), hash_mod.node_value(n)) for n in nodes)
        return _format_items(size, entries)
    except Exception:
        return "<unreadable>"


def _is_chain(value):
    """True, если value — указатель на MultiNodeChain (Qt6 QMultiHash).

    Поле value у MultiNode имеет тип typedef-алиаса Chain (QHashPrivate::
    MultiNode<...>::Chain), поэтому проверяем по имени указываемого типа, а не
    по подстроке "Chain", чтобы не зацепить пользовательские типы вроде
    FooChain* в Qt5 QMultiHash.
    """
    if value is None or not value.IsValid() or not value.GetType().IsPointerType():
        return False
    name = value.GetType().GetPointeeType().GetName() or ""
    return name.startswith("QHashPrivate::MultiNode") and name.endswith("::Chain")


def _iter_chain_values(chain):
    """Генератор SBValue значений цепочки MultiNodeChain<T> (Qt6 QMultiHash)."""
    guard = 0
    while chain is not None and chain.IsValid() and guard < 1024:
        ptr = common.read_pointer(chain)
        if not ptr:
            break
        cc = chain.Dereference()
        if cc is None or not cc.IsValid():
            break
        cv = cc.GetChildMemberWithName("value")
        if cv is not None and cv.IsValid():
            yield cv
        chain = cc.GetChildMemberWithName("next")
        guard += 1


def _iter_multihash_entries(nodes):
    """Генератор плоских пар (key, value) из итератора узлов QMultiHash.

    Qt5: QMultiHash наследует QHash, каждый узел — отдельная пара (value — T).
    Qt6: узлы MultiNode<K,V>, value — указатель на цепочку Chain<T>; раскрываем
    цепочку в отдельные записи.
    """
    for node in nodes:
        k = hash_mod.node_key(node)
        v = hash_mod.node_value(node)
        if _is_chain(v):
            yield from ((k, cv) for cv in _iter_chain_values(v))
        else:
            yield k, v


def format_qmultihash(valobj, internal_dict):
    """Summary для QMultiHash<K,V>: size=N [(k: v), ...].

    Qt6: реальное число пар — в m_size (d->size считает только уникальные
    ключи); это учитывает hash.hash_layout. Qt5: QMultiHash наследует QHash,
    размер в d->size.
    """
    try:
        info = hash_mod.hash_layout(valobj)
        if info is None:
            return "<invalid>"
        size, nodes = info
        return _format_items(size, _iter_multihash_entries(nodes))
    except Exception:
        return "<unreadable>"


def format_qmap(valobj, internal_dict):
    """Summary для QMap<K,V>: size=N [(k: v), ...].

    Пары читаются через map.map_layout (Qt5 — QMapNode, Qt6 — std::map).
    Порядок детерминирован (сортировка по ключу).
    """
    try:
        md = map_mod.map_layout(valobj)
        if md is None:
            return "<invalid>"
        kind, size, nodes = md
        key_field, val_field = map_mod.entry_fields(kind)
        entries = ((common.get_child_by_name(n, key_field), common.get_child_by_name(n, val_field)) for n in nodes)
        return _format_items(size, entries)
    except Exception:
        return "<unreadable>"


def format_qmultimap(valobj, internal_dict):
    """Summary для QMultiMap<K,V>.

    Раскладка повторяет QMap (Qt5 — базовый QMap с QMapData*, Qt6 — std::multimap),
    поэтому просто делегируем в format_qmap.
    """
    return format_qmap(valobj, internal_dict)


def _build_node_children(value):
    """Строит list[(имя, SBValue)] из узлов QHash для synthetic-детей."""
    return build_values(
        value.GetTarget(),
        ((node.GetLoadAddress(), node.GetType()) for node in hash_mod.iter_hash_nodes(value)),
    )


class QHashSynthetic(IterSynthetic):
    """Synthetic для QHash<K,V>/QMultiHash<K,V>: узлы как дочерние [i].

    Каждый ребёнок — узел-запись: QHashNode<Key,T> (поля key/value) в Qt5 и для
    Qt6 QHash; MultiNode<Key,T> (key + цепочка значений) для Qt6 QMultiHash.
    Цепочка раскрывается отдельным synthetic-провайдером QMultiHashNodeSynthetic.
    """

    def build_values(self):
        return _build_node_children(self.value)


class QMultiHashNodeSynthetic(IterSynthetic):
    """Synthetic для QHashPrivate::MultiNode<K,V> (Qt6 QMultiHash).

    Раскрывает узел в пару «ключ + значения цепочки»: дети key и [0], [1], …
    — вложенное представление, честное к памяти (ключ и значения лежат в
    разных аллокациях).
    """

    def build_values(self):
        raw = common.raw_value(self.value)
        if raw is None or not raw.IsValid():
            return []
        target = raw.GetTarget()
        values = []
        key = hash_mod.node_key(raw)
        if key is not None:
            values.append(("key", key))
        v = hash_mod.node_value(raw)
        if not _is_chain(v):
            return values
        i = 0
        for cv in _iter_chain_values(v):
            if cv is None or not cv.IsValid():
                continue
            addr = cv.GetLoadAddress()
            if not addr:
                continue
            child = target.CreateValueFromAddress(f"[{i}]", lldb.SBAddress(addr, target), cv.GetType())
            if child is not None and child.IsValid():
                values.append((f"[{i}]", child))
                i += 1
        return values


class QMapSynthetic(IterSynthetic):
    """Synthetic для QMap<K,V>/QMultiMap<K,V>: записи как дочерние [i].

    Каждый ребёнок — узел-запись: QMapNode<K,V> (поля key/value) в Qt5 или
    std::pair<const K,V> (поля first/second) в Qt6.
    """

    def build_values(self):
        md = map_mod.map_layout(self.value)
        if md is None:
            return []
        _kind, _size, nodes = md
        return build_values(
            self.value.GetTarget(),
            ((node.GetLoadAddress(), node.GetType()) for node in nodes),
        )
