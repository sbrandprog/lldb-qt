#!/usr/bin/env python3
"""Автотесты для lldb-форматтеров Qt.

Запускает тестовый бинарник (собранный под Qt5 или Qt6) в lldb, регистрирует
форматтеры qt_formatters и сверяет Summary читаемых типов с ожидаемыми.

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
}


def expectations_for(qt_major):
    exp = dict(EXPECTATIONS)
    if qt_major == 6:
        # Маленький QList<int> в Qt6 хранится inline (union) — проверяем.
        exp["g_qlist_ints"] = "size=2 [7, 8]"
        # QHash (элементы пока не раскрываются, только размер)
        exp["g_hash"] = "size=2"
        # QVariant: null vs не-null
        exp["g_variant_null"] = "<null>"
        exp["g_variant_int"] = "<variant>"
    # Примечание: в Qt5 QList<int>/QHash/QVariant детально пока не покрыты.
    return exp


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    binary = sys.argv[1]
    qt_major = int(sys.argv[2])

    debugger = lldb.SBDebugger.Create()
    debugger.SetAsync(False)

    target, process = launch(debugger, binary)

    # Регистрируем форматеры ПОСЛЕ создания target: детекция версии Qt
    # полагается на типы в отлаживаемом процессе.
    debugger.HandleCommand("command script import qt_formatters")

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

    debugger.Terminate()
    if failures:
        print(f"\n{len(failures)} failure(s): {failures}")
        return 1
    print("\nAll passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
