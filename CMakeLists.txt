cmake_minimum_required (VERSION 3.5)

project(tvim)

find_package(msgpack REQUIRED)
find_package(boost REQUIRED COMPONENTS process)

add_subdirectory(vendor/tvision)

add_executable(
  tvim
  src/main.cpp
)
target_link_libraries(tvim PUBLIC tvision msgpackc)
