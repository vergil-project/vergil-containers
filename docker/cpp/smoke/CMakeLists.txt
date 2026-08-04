cmake_minimum_required(VERSION 3.20)
project(cpp_smoke CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(fmt REQUIRED)

add_executable(cpp_smoke src/main.cpp)
target_link_libraries(cpp_smoke PRIVATE fmt::fmt)
