cmake_minimum_required(VERSION 3.16)
project(jetson_llm_harness CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(jetson_runtime src/main.cpp)
target_include_directories(jetson_runtime PRIVATE src)

add_executable(oled_demo src/oled_demo.cpp)
target_include_directories(oled_demo PRIVATE src)
