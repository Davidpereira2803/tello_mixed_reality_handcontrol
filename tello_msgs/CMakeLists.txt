cmake_minimum_required(VERSION 3.5)
project(tello_msgs)

# Default to C99
if(NOT CMAKE_C_STANDARD)
  set(CMAKE_C_STANDARD 99)
endif()

# Default to C++14
if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 14)
endif()

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# find dependencies
find_package(ament_cmake REQUIRED)

find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/FlightStats.msg"
  "msg/FlipControl.msg"
  "msg/PS4Buttons.msg"
  "msg/ModeStatus.msg"
  "msg/FacePosition.msg"
  "msg/Game.msg"
  "msg/GameStatus.msg"
)

ament_package()
