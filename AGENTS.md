LLDB data formatters for Qt types (Qt5 + Qt6), written in Python. Loaded into lldb via `command script import lldb_qt`.

# Commands

- `just run_tests_qt5` / `just run_tests_qt6` — build one test binary + run its lldb assertions
- `just run_tests` — both
- Manual: `cmake --preset default && cmake --build out/build/default --target test_qt6 && .venv/bin/python3 tests/run_tests.py ./out/build/default/tests/test_qt6 6`

Build uses the CMake `default` preset (Ninja, gcc/g++, Debug, exports `compile_commands.json`).

# Environment

- `.venv` was created with `--system-site-packages` so `import lldb` resolves to the system LLDB (`/usr/lib/python3.14/site-packages/lldb`). Recreate it with `python3 -m venv --system-site-packages .venv` or lldb imports fail.
- Tests require the system `lldb` binary and both Qt5 + Qt6 dev packages (`find_package(Qt5|Qt6 COMPONENTS Core)`). Disable one with `-DBUILD_QT5=OFF` / `-DBUILD_QT6=OFF`.

# Architecture

- `lldb_qt/` is the product; `tests/` are C++ binaries built only to be inspected by lldb.
- `__init__.py` is the entrypoint (`__lldb_init_module`). It registers a single, version-agnostic set of formatters.
- `common.py`: low-level SBValue helpers — `raw_value()` (calls `GetNonSyntheticValue`) is essential; summary/providers receive synthetic-wrapped values and must read real fields via it.
- `providers.py`: synthetic-children providers. `SyntheticBase` implements lldb's duck-typed interface (`update`, `has_children`, `num_children`, `get_child_index`, `get_child_at_index`) and caches `self.values`; subclasses must implement `_build_values()`. Two concrete bases derive from it: `ListSynthetic` (random access — subclass implements `count()`/`item_at()`) and `IterSynthetic` (single pass — subclass implements `build_values()`). Helper `build_values(target, items)` builds `[(name, SBValue)]` from an iterator of `(addr, SBType)`.
- `datetime.py`: formatters for date/time types (QDate, QTime, QDateTime). QDate stores `jd` (Julian day), QTime stores `mds` (ms since midnight). QDateTime uses a union with ShortData (inline optimization) or QDateTimePrivate* (heap), dispatching on status flags.
- `geometry.py`: formatters for geometry types shared by both Qt versions. Integer types (QSize/QPoint/QRect/QLine) use `_int_of()` helper to handle Qt6's `m_i` wrapper. Float types (QSizeF/QPointF/QRectF/QLineF) use `_qreal_of()` for plain `double` fields.
- `strings.py`: `QString`/`QByteArray` summaries and `StringSynthetic` synthetic. `_string_data` dispatches on the runtime layout (Qt6 `QArrayDataPointer` has `d.ptr`; Qt5 `d` is a pointer to a header with `size`/`offset`).
- `containers.py`: single `QListSynthetic` + `_summary_qlist` for QList/QVector/QStringList. `_layout` dispatches on runtime structure (Qt6 `d.ptr`, Qt5 `QVectorData` vs `QListData` union).
- `assoc.py`: summaries + synthetics for `QHash`/`QMultiHash`/`QMap`/`QMultiMap`. `QHashSynthetic` (an `IterSynthetic` over hash nodes) is registered for both `QHash` and `QMultiHash`; `QMapSynthetic` (an `IterSynthetic` over map nodes) for `QMap` and `QMultiMap`. `QMultiHashNodeSynthetic` (for `QHashPrivate::MultiNode`, anchored `^...$`) expands a Qt6 `QMultiHash` node into `key` + chain values (nested children). `_iter_multihash_entries`/`_iter_chain_values` expand chains for summaries.
- `set.py`: `QSet<T>` — `format_qset` summary and `QSetSynthetic` (an `IterSynthetic` over the keys of the underlying `q_hash` member).
- `hash.py`: `hash_layout` — single entry point returning `(size, node_iter)` (Qt5 buckets/linked lists, Qt6 spans); `iter_hash_nodes` is a thin wrapper, `node_key`/`node_value` read fields via `raw_value`. Shared by `assoc.py` and `set.py`. Uses `find_deep` so it also works for Qt5 `QMultiHash` (which inherits `QHash`).
- `map.py`: `map_layout` — single entry point returning `(kind, size, node_iter)`; `entry_fields(kind)` maps `kind` to the key/value field names. Version-agnostic QMap node traversal (Qt5 `QMapData*` red-black tree with `QMapNode<K,V>` `key`/`value`; Qt6 `std::map` red-black tree with `std::pair<const K,V>` `first`/`second`), in sorted order.
- `variant.py`: `format_qvariant` + `QVariantSynthetic` for `QVariant` with correct detection of meta-type for both Qt majors. 

# Registration conventions

- Type names are registered via `type summary add -x` / `type synthetic add -l` under category `qt`, with names anchored `^Name$` (see `_anchor_re` in `__init__.py`) so `QString` doesn't also match `QStringList`/`QDateTime`.
- Regex patterns passed to the registration helpers are used as-is; exact names get anchored automatically.

# Qt layout gotchas

- Qt5 `QList<T>` element layout depends on `QTypeInfo<T>`: movable/small types are stored inline in `sizeof(void*)` slots, large/static types via pointer (IndirectLayout). `containers.is_movable_type` approximates this since compile-time type info is unavailable in the debugger.
- Qt5 `QList`/`QStringList` exposes its data through a union; `containers._find_d`/`_find_deep` recursively search children for the `d` field.
- Qt6 uses `QArrayDataPointer<T>` (`d` → `ptr` + `size`); QList/QVector/QStringList share one `QListSynthetic`.
- Qt5 `QHash`/`QMap` both store `d` as a pointer whose header has `size`; Qt6 `QMap` wraps std::map, so `map.map_layout` reads `_M_node_count` when `d` is not a raw pointer.
- Qt6 `QMap` stores each entry as `std::_Rb_tree_node<std::pair<const K,V>>`: the pair is at `node + sizeof(_Rb_tree_node_base)` and exposes `first`/`second` (not `key`/`value`); `map.entry_fields` normalizes the two naming schemes.
- Qt6 `QMultiHash` is a separate class (not a `QHash` subclass): `m_size` holds the real entry count, `d->size` counts only unique keys; each `MultiNode<K,V>` has `key` plus a `Chain*` linked list of values. Summaries flatten the chains (`assoc._iter_multihash_entries`); synthetic children are nested (a `MultiNode` child expanded by `QMultiHashNodeSynthetic` into `key` + values).
- QDateTime stores data in a union: ShortData (inline optimization with status byte + msecs in bitfields) or QDateTimePrivate* (heap with m_status, m_msecs, m_offsetFromUtc, m_timeZone). Dispatch on `status & 0x01`.

# Tests

- `tests/run_tests.py` launches the test binary in lldb, breaks at `qt_break_anchor()`, imports `lldb_qt`, and compares summaries/children against `EXPECTATIONS`/`CHILD_EXPECTATIONS` (version-specific via `expectations_for(qt_major)`).
- To add a formatter: declare a global instance in `tests/test_qt5.cpp`/`test_qt6.cpp`, add the expected summary in `run_tests.py`, register in the appropriate module.
- Docstrings/comments throughout are in Russian; follow that convention.
