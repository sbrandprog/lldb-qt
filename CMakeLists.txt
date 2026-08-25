cmake_minimum_required(VERSION 3.16)
project(lldb_qt_formatters LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

option(BUILD_QT5 "Собирать тест под Qt5" ON)
option(BUILD_QT6 "Собирать тест под Qt6" ON)

if(BUILD_QT5)
    find_package(Qt5 REQUIRED COMPONENTS Core)
endif()

if(BUILD_QT6)
    find_package(Qt6 REQUIRED COMPONENTS Core)
endif()

add_subdirectory(tests)
