
set default-list := true

python_exe := ".venv/bin/python3"

run_tests_template target_name qt_major:
    cmake --preset default
    cmake --build out/build/default --target {{target_name}}
    {{python_exe}} tests/run_tests.py ./out/build/default/tests/{{target_name}} {{qt_major}}

run_tests_qt5: (run_tests_template "test_qt5" "5")
run_tests_qt6: (run_tests_template "test_qt6" "6")

run_tests: run_tests_qt5 run_tests_qt6
