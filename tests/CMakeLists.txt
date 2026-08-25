
if(BUILD_QT5)
    add_executable(test_qt5 test_qt5.cpp)
    target_link_libraries(test_qt5 PRIVATE Qt5::Core)
endif()

if(BUILD_QT6)
    add_executable(test_qt6 test_qt6.cpp)
    target_link_libraries(test_qt6 PRIVATE Qt6::Core)
endif()
