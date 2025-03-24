cmake_minimum_required(VERSION 3.5)
project(romea_path_tools)

# Find dependencies
find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
find_package(rclpy REQUIRED)

# Install Python modules
ament_python_install_package(${PROJECT_NAME})

# Install Python executables
install(PROGRAMS
  scripts/annotate
  scripts/convert
  scripts/show
  scripts/record
  scripts/path_from_swaths
  scripts/planner
  DESTINATION lib/${PROJECT_NAME}
)

ament_package()
