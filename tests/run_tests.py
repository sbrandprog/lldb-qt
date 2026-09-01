#!/usr/bin/env python3
"""Автотесты для lldb-форматтеров Qt.

Запускает тестовый бинарник (собранный под Qt5 или Qt6) в lldb, регистрирует
форматтеры lldb_qt и сверяет Summary читаемых типов с ожидаемыми.

Использование:
    python3 run_tests.py [path to test executable] [qt major: 5 or 6]
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lldb


def launch(debugger, binary):
    err = lldb.SBError()
    target = debugger.CreateTarget(binary)
    if not target or not target.IsValid():
        raise RuntimeError(f"cannot create target for {binary}")
    launch_info = lldb.SBLaunchInfo([binary])
    launch_info.SetLaunchFlags(lldb.eLaunchFlagStopAtEntry)
    debugger.SetAsync(False)
    process = target.Launch(launch_info, err)
    if err.Fail():
        raise RuntimeError(f"launch failed: {err}")
    if process.GetState() != lldb.eStateStopped:
        raise RuntimeError(f"process not stopped: {process.GetState()}")
    # Доходим до анкерной точки после инициализации глобальных данных
    target.BreakpointCreateByName("qt_break_anchor")
    process.Continue()
    state = process.GetState()
    if state != lldb.eStateStopped:
        raise RuntimeError(f"did not stop at qt_break_anchor: {state}")
    return target, process


def read_summary(frame, varpath):
    val = frame.GetValueForVariablePath(varpath)
    if not val or not val.IsValid():
        return None
    return val.GetSummary()


def read_children(frame, varpath):
    """Возвращает list[(display, fields)] для synthetic-детей переменной.

    display — summary или scalar-значение ребёнка; fields — dict имя->значение
    для структурных детей (None для элементов-структур с нестабильными полями).
    """
    val = frame.GetValueForVariablePath(varpath)
    if not val or not val.IsValid():
        return None
    out = []
    for i in range(val.GetNumChildren()):
        c = val.GetChildAtIndex(i)
        if not c or not c.IsValid():
            out.append((None, None))
            continue
        display = c.GetSummary() or c.GetValue()
        fields = {}
        for j in range(c.GetNumChildren()):
            f = c.GetChildAtIndex(j)
            if f and f.IsValid():
                fields[f.GetName()] = f.GetValue()
        out.append((display, fields))
    return out


EXPECTATIONS = {
    "g_string_ascii": "'hello world'",
    "g_string_unicode": "'привет мир ☺ 日本語'",
    "g_string_empty": '""',
    "g_bytes": "'byte-data-123'",
    "g_bytes_empty": '""',
    "g_stringlist": "size=4 ['alpha', 'beta', 'gamma', 'delta']",
    "g_stringlist_empty": "[]",
    "g_date": "2024-02-29",
    "g_time": "13:45:30.000",
    "g_size": "800x600",
    "g_point": "(12, -34)",
    "g_rect": "(0, 0, 640, 480)",
    "g_line": "(1, 2) -> (3, 4)",
    "g_qvector": "size=3 ['x', 'y', 'z']",
    "g_map": "size=3",
    "g_hash": "size=2",
    "g_variant_null": "<null>",
    "g_variant_int": "<variant>",
}

CHILD_EXPECTATIONS = {
    "g_stringlist": [
        ("'alpha'", None),
        ("'beta'", None),
        ("'gamma'", None),
        ("'delta'", None),
    ],
    "g_stringlist_empty": [],
    "g_qvector": [("'x'", None), ("'y'", None), ("'z'", None)],
    "g_qlist_ints": [("7", {}), ("8", {})],
}

# IndirectLayout в Qt5: элементы QList из plain-struct хранятся по указателю;
# проверяем не только count, но и поля структуры по разыменованному указателю.
CHILD_EXPECTATIONS_QT5 = {
    "g_qlist_pairs": [
        (None, {"a": "1", "b": "2"}),
        (None, {"a": "3", "b": "4"}),
    ],
}


def expectations_for(qt_major):
    exp = dict(EXPECTATIONS)
    if qt_major == 6:
        # Маленький QList<int> в Qt6 хранится inline (union) — проверяем.
        exp["g_qlist_ints"] = "size=2 [7, 8]"
    elif qt_major == 5:
        exp["g_qlist_ints"] = "size=2 [7, 8]"
        exp["g_qlist_pairs"] = "size=2 [?, ?]"
    return exp


def child_expectations_for(qt_major):
    exp = dict(CHILD_EXPECTATIONS)
    if qt_major == 5:
        exp.update(CHILD_EXPECTATIONS_QT5)
    return exp


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    binary = sys.argv[1]
    qt_major = int(sys.argv[2])

    debugger = lldb.SBDebugger.Create()
    debugger.SetAsync(False)

    debugger.HandleCommand("command script import lldb_qt")

    target, process = launch(debugger, binary)

    frame = process.GetSelectedThread().GetSelectedFrame()

    expected = expectations_for(qt_major)
    failures = []
    for varpath, want in expected.items():
        got = read_summary(frame, varpath)
        ok = got == want
        status = "OK " if ok else "FAIL"
        print(f"[{status}] {varpath}: {got!r}  (expected {want!r})")
        if not ok:
            failures.append(varpath)

    children_expected = child_expectations_for(qt_major)
    for varpath, want in children_expected.items():
        for index, (display, fields) in enumerate(want):
            got_children = read_children(frame, varpath)
            got_display = None
            got_fields = None
            ok = False
            if got_children is not None and index < len(got_children):
                got_display, got_fields = got_children[index]
                ok = got_display == display
                if fields is not None:
                    ok = ok and got_fields == fields
            status = "OK " if ok else "FAIL"
            print(
                f"[{status}] {varpath}[{index}]: display={got_display!r} "
                f"fields={got_fields!r}  (expected display={display!r} fields={fields!r})"
            )
            if not ok:
                failures.append(f"{varpath}[{index}]")

    debugger.Terminate()
    if failures:
        print(f"\n{len(failures)} failure(s): {failures}")
        return 1
    print("\nAll passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
