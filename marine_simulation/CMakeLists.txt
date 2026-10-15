cmake_minimum_required(VERSION 3.14.4)
project(marine_simulation)

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)

# marine_simulation.roster and marine_simulation.demo_support: the helpers the launch manager's
# starter and the launch files of its groups import (nothing is loaded by file path)
ament_python_install_package(${PROJECT_NAME})

install(DIRECTORY config DESTINATION share/${PROJECT_NAME})
install(DIRECTORY launch DESTINATION share/${PROJECT_NAME})
install(PROGRAMS
  scripts/check_multi_boat_graph.py
  scripts/demo_boats_selftest.py
  scripts/demo_manager.py
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
  ament_add_pytest_test(test_demo_boats_selftest test/test_demo_boats_selftest.py)
  ament_add_pytest_test(test_demo_manager test/test_demo_manager.py)
  # host-only and slow (about two minutes): the default 60 s CTest timeout would kill it
  ament_add_pytest_test(test_demo_manager_live test/test_demo_manager_live.py TIMEOUT 900)
  ament_add_pytest_test(test_place_windows test/test_place_windows.py)
  ament_add_pytest_test(test_demo_support test/test_demo_support.py)
  ament_add_pytest_test(test_demo_launch test/test_demo_launch.py)
  ament_add_pytest_test(test_run_demo test/test_run_demo.py)
  ament_add_pytest_test(test_publish_survey_area test/test_publish_survey_area.py)
endif()

ament_package()
