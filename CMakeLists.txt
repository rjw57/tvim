cmake_minimum_required (VERSION 3.5)

project(tvim)

add_subdirectory(vendor/tvision)

add_executable(
  tvim
  src/main.cpp
)
target_link_libraries(tvim tvision)
