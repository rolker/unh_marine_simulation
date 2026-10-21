cmake_minimum_required(VERSION 3.14.4)
project(marine_simulation)

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)

# marine_simulation.roster and marine_simulation.demo_support: the helpers the launch manager's
# starter and the launch files of its groups import (nothing is loaded by file path)
ament_python_install_package(${PROJECT_NAME})

# LD_PRELOAD shim: shifts the ZeroMQ ports of one boat's nav2 processes (see the source)
add_library(demo_zmq_ports SHARED src/demo_zmq_ports.c)
target_link_libraries(demo_zmq_ports ${CMAKE_DL_LIBS})
install(TARGETS demo_zmq_ports LIBRARY DESTINATION lib/${PROJECT_NAME})

install(DIRECTORY config DESTINATION share/${PROJECT_NAME})
install(DIRECTORY launch DESTINATION share/${PROJECT_NAME})
install(PROGRAMS
  scripts/check_multi_boat_graph.py
  scripts/demo_boats_selftest.py
  scripts/demo_manager.py
  scripts/demo_watchdog.py
  scripts/install_demo_shortcut.sh
  scripts/place_windows.py
  scripts/run_demo.sh
  scripts/publish_survey_area.py
  DESTINATION lib/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()

  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(test_demo_boats_launch test/test_demo_boats_launch.py)
  ament_add_pytest_test(test_check_multi_boat_graph test/test_check_multi_boat_graph.py)
  ament_add_pytest_test(test_demo_nav test/test_demo_nav.py)
  ament_add_pytest_test(test_survey_sections test/test_survey_sections.py)
  ament_add_pytest_test(test_demo_zmq_ports test/test_demo_zmq_ports.py)
  ament_add_pytest_test(test_watchdog_core test/test_watchdog_core.py)
  ament_add_pytest_test(test_demo_watchdog test/test_demo_watchdog.py)
  ament_add_pytest_test(test_demo_boats_selftest test/test_demo_boats_selftest.py)
  ament_add_pytest_test(test_demo_manager test/test_demo_manager.py)
  # host-only and slow (about two minutes): the default 60 s CTest timeout would kill it
  ament_add_pytest_test(test_demo_manager_live test/test_demo_manager_live.py TIMEOUT 900)
  ament_add_pytest_test(test_place_windows test/test_place_windows.py)
  ament_add_pytest_test(test_demo_support test/test_demo_support.py)
  ament_add_pytest_test(test_demo_perspective test/test_demo_perspective.py)
  ament_add_pytest_test(test_run_demo test/test_run_demo.py)
  ament_add_pytest_test(test_publish_survey_area test/test_publish_survey_area.py)
endif()

ament_package()
