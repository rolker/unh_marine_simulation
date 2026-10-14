cmake_minimum_required(VERSION 3.14.4)
project(marine_simulation)

find_package(ament_cmake REQUIRED)

install(DIRECTORY config DESTINATION share/${PROJECT_NAME})
install(DIRECTORY launch DESTINATION share/${PROJECT_NAME})
install(PROGRAMS
  scripts/check_multi_boat_graph.py
  scripts/demo_boats_selftest.py
  scripts/demo_manager.py
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
endif()

ament_package()
