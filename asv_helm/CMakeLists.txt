cmake_minimum_required(VERSION 3.5.1)

project(asv_helm)

set(CMAKE_CXX_STANDARD 17)
if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)

find_package(geometry_msgs REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(marine_autonomy REQUIRED)
find_package(marine_interfaces REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rclcpp_lifecycle REQUIRED)
find_package(std_msgs REQUIRED)

add_executable(${PROJECT_NAME} src/asv_helm_node.cpp)

target_link_libraries(${PROJECT_NAME}
  ${geometry_msgs_TARGETS}
  ${nav_msgs_TARGETS}
  ${marine_interfaces_TARGETS}
  ${std_msgs_TARGETS}
  marine_autonomy::marine_autonomy
  rclcpp::rclcpp
  rclcpp_lifecycle::rclcpp_lifecycle
)

install(TARGETS ${PROJECT_NAME}
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY launch DESTINATION share/${PROJECT_NAME})

ament_package()
