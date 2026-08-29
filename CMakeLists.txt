cmake_minimum_required(VERSION 3.20)
project(Eloi VERSION 1.0.0 LANGUAGES CXX)
set(ELOI_PRERELEASE "rc.1")
if(ELOI_PRERELEASE)
  set(ELOI_VERSION "${PROJECT_VERSION}-${ELOI_PRERELEASE}")
else()
  set(ELOI_VERSION "${PROJECT_VERSION}")
endif()

configure_file(
  include/eloi/version.hpp.in
  "${CMAKE_CURRENT_BINARY_DIR}/generated/eloi/version.hpp"
  @ONLY)
if(WIN32)
  enable_language(RC)
  configure_file(
    src/version.rc.in
    "${CMAKE_CURRENT_BINARY_DIR}/generated/version.rc"
    @ONLY)
endif()

include(CheckIPOSupported)

# CMake 3.29 predates the CXX26 dialect label. Request the compiler's C++26
# mode directly until CMake's standardized CXX26 feature is widely available.
if(MSVC)
  add_compile_options(/std:c++latest)
else()
  add_compile_options(-std=c++2c)
endif()

option(ELOI_BUILD_APP "Build the production Eloi executable" ON)

set(SKIA_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/.deps/skia108/ucrt64"
    CACHE PATH "Root of the Skia UCRT64 package")
if(WIN32 AND ELOI_BUILD_APP AND NOT EXISTS "${SKIA_ROOT}/lib/libskia.a")
  message(FATAL_ERROR "Skia was not found in .deps/skia108/ucrt64. See README.md.")
endif()

add_library(eloi_core STATIC src/chess.cpp src/nnue.cpp src/book.cpp src/config.cpp)
target_include_directories(eloi_core PUBLIC
  ${CMAKE_CURRENT_SOURCE_DIR}/include
  "${CMAKE_CURRENT_BINARY_DIR}/generated")
if(MSVC)
  target_compile_options(eloi_core PRIVATE /W4 /permissive-)
else()
  target_compile_options(eloi_core PRIVATE -Wall -Wextra -Wpedantic)
endif()

# Eloi is the sole production executable: GUI, UCI and perft are runtime modes.
if(ELOI_BUILD_APP)
  set(ELOI_APP_SOURCES
    src/main.cpp src/driver.cpp src/gui.cpp src/lichess.cpp src/resources.rc)
  if(WIN32)
    list(APPEND ELOI_APP_SOURCES
      "${CMAKE_CURRENT_BINARY_DIR}/generated/version.rc")
  endif()
  add_executable(Eloi ${ELOI_APP_SOURCES})
  target_link_libraries(Eloi PRIVATE eloi_core)
endif()

check_ipo_supported(RESULT ELOI_IPO_SUPPORTED OUTPUT ELOI_IPO_ERROR)
if(ELOI_IPO_SUPPORTED)
  set_property(TARGET eloi_core PROPERTY INTERPROCEDURAL_OPTIMIZATION_RELEASE TRUE)
  if(ELOI_BUILD_APP)
    set_property(TARGET Eloi PROPERTY INTERPROCEDURAL_OPTIMIZATION_RELEASE TRUE)
  endif()
endif()
if(NOT MSVC)
  target_compile_options(eloi_core PRIVATE
    $<$<CONFIG:Release>:-O3;-ffunction-sections;-fdata-sections>)
  if(ELOI_BUILD_APP)
    target_compile_options(Eloi PRIVATE
      $<$<CONFIG:Release>:-O3;-ffunction-sections;-fdata-sections>)
    target_link_options(Eloi PRIVATE
      $<$<CONFIG:Release>:-Wl,--gc-sections;-s>)
  endif()
endif()

if(WIN32 AND ELOI_BUILD_APP)
  set(ELOI_STATIC_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/.deps/static-runtime"
      CACHE PATH "Root containing Eloi's static codec libraries")
  if(NOT EXISTS "${ELOI_STATIC_ROOT}/lib/libjpeg.a" OR
     NOT EXISTS "${ELOI_STATIC_ROOT}/lib/libpng16.a" OR
     NOT EXISTS "${ELOI_STATIC_ROOT}/lib/libwebp.a" OR
     NOT EXISTS "${ELOI_STATIC_ROOT}/lib/libzs.a")
    message(FATAL_ERROR
      "Static codecs were not found under ${ELOI_STATIC_ROOT}. "
      "Run scripts/bootstrap-static-codecs.ps1.")
  endif()
  target_include_directories(Eloi PRIVATE
    "${SKIA_ROOT}/include/skia"
  )
  target_link_libraries(Eloi PRIVATE
    "${SKIA_ROOT}/lib/libskia.a"
    "${ELOI_STATIC_ROOT}/lib/libjpeg.a"
    "${ELOI_STATIC_ROOT}/lib/libpng16.a"
    "${ELOI_STATIC_ROOT}/lib/libwebpdemux.a"
    "${ELOI_STATIC_ROOT}/lib/libwebpmux.a"
    "${ELOI_STATIC_ROOT}/lib/libwebp.a"
    "${ELOI_STATIC_ROOT}/lib/libsharpyuv.a"
    "${ELOI_STATIC_ROOT}/lib/libzs.a"
    gdi32 user32 shell32 ole32 oleaut32 uuid usp10 opengl32 winhttp
  )
  target_link_options(Eloi PRIVATE
    $<$<CONFIG:Release>:-static;-static-libgcc;-static-libstdc++>)

  set(ELOI_RELEASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/dist/release")
  add_custom_target(release
    COMMAND ${CMAKE_COMMAND} -E remove_directory "${ELOI_RELEASE_DIR}"
    COMMAND ${CMAKE_COMMAND} -E make_directory "${ELOI_RELEASE_DIR}"
    COMMAND ${CMAKE_COMMAND} -E copy "$<TARGET_FILE:Eloi>"
            "${ELOI_RELEASE_DIR}/Eloi.exe"
    COMMAND ${CMAKE_COMMAND} -E copy
            "${CMAKE_CURRENT_SOURCE_DIR}/config.example.yml"
            "${ELOI_RELEASE_DIR}/config.yml"
    DEPENDS Eloi
    COMMENT "Staging the two-file Eloi release")
endif()

option(ELOI_BUILD_TESTS "Build the separate Eloi test runner" OFF)
if(ELOI_BUILD_TESTS)
  enable_testing()
  add_executable(eloi_tests tests/tests.cpp)
  target_link_libraries(eloi_tests PRIVATE eloi_core)
  add_test(NAME eloi_tests COMMAND eloi_tests)
endif()
