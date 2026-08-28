cmake_minimum_required(VERSION 3.20)
project(Eloi VERSION 1.0.0 LANGUAGES CXX)

include(CheckIPOSupported)

# CMake 3.29 predates the CXX26 dialect label. Request the compiler's C++26
# mode directly until CMake's standardized CXX26 feature is widely available.
if(MSVC)
  add_compile_options(/std:c++latest)
else()
  add_compile_options(-std=c++2c)
endif()

set(SKIA_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/.deps/skia108/ucrt64"
    CACHE PATH "Root of the Skia UCRT64 package")
if(WIN32 AND NOT EXISTS "${SKIA_ROOT}/lib/libskia.a")
  message(FATAL_ERROR "Skia was not found in .deps/skia/ucrt64. See README.md.")
endif()

add_library(eloi_core STATIC src/chess.cpp src/nnue.cpp src/book.cpp)
target_include_directories(eloi_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
if(MSVC)
  target_compile_options(eloi_core PRIVATE /W4 /permissive-)
else()
  target_compile_options(eloi_core PRIVATE -Wall -Wextra -Wpedantic)
endif()

# Eloi is the sole production executable: GUI, UCI and perft are runtime modes.
add_executable(Eloi src/main.cpp src/driver.cpp src/gui.cpp)
target_link_libraries(Eloi PRIVATE eloi_core)

check_ipo_supported(RESULT ELOI_IPO_SUPPORTED OUTPUT ELOI_IPO_ERROR)
if(ELOI_IPO_SUPPORTED)
  set_property(TARGET eloi_core Eloi PROPERTY INTERPROCEDURAL_OPTIMIZATION_RELEASE TRUE)
endif()
if(NOT MSVC)
  target_compile_options(eloi_core PRIVATE
    $<$<CONFIG:Release>:-O3;-ffunction-sections;-fdata-sections>)
  target_compile_options(Eloi PRIVATE
    $<$<CONFIG:Release>:-O3;-ffunction-sections;-fdata-sections>)
  target_link_options(Eloi PRIVATE
    $<$<CONFIG:Release>:-Wl,--gc-sections;-s>)
endif()

if(WIN32)
  set(RUNTIME_DEPS_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/.deps/skia/ucrt64")
  target_include_directories(Eloi PRIVATE
    "${SKIA_ROOT}/include/skia"
    "${CMAKE_CURRENT_SOURCE_DIR}/.deps/nanosvg"
  )
  target_link_libraries(Eloi PRIVATE
    "${SKIA_ROOT}/lib/libskia.a"
    "${RUNTIME_DEPS_ROOT}/lib/libjpeg.dll.a"
    "${RUNTIME_DEPS_ROOT}/lib/libpng16.dll.a"
    "${RUNTIME_DEPS_ROOT}/lib/libwebpdemux.dll.a"
    "${RUNTIME_DEPS_ROOT}/lib/libwebpmux.dll.a"
    "${RUNTIME_DEPS_ROOT}/lib/libwebp.dll.a"
    "${RUNTIME_DEPS_ROOT}/lib/libz.dll.a"
    gdi32 user32 shell32 ole32 oleaut32 uuid usp10 opengl32
  )
  set(ELOI_RUNTIME_DLL_NAMES
    libgcc_s_seh-1.dll
    libwinpthread-1.dll
    libstdc++-6.dll
    libjpeg-8.dll
    libpng16-16.dll
    libwebp-7.dll
    libwebpdemux-2.dll
    libwebpmux-3.dll
    libsharpyuv-0.dll
    zlib1.dll
  )
  set(ELOI_RUNTIME_DLLS)
  foreach(DLL_NAME IN LISTS ELOI_RUNTIME_DLL_NAMES)
    list(APPEND ELOI_RUNTIME_DLLS "${RUNTIME_DEPS_ROOT}/bin/${DLL_NAME}")
  endforeach()
  add_custom_command(TARGET Eloi POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
            ${ELOI_RUNTIME_DLLS} $<TARGET_FILE_DIR:Eloi>
    COMMAND ${CMAKE_COMMAND} -E copy_directory
            "${CMAKE_CURRENT_SOURCE_DIR}/assets/chess_maestro_bw"
            "$<TARGET_FILE_DIR:Eloi>/assets/chess_maestro_bw"
    COMMENT "Bundling attributed Maestro BW chess pieces"
  )
endif()

option(ELOI_BUILD_TESTS "Build the separate Eloi test runner" OFF)
if(ELOI_BUILD_TESTS)
  enable_testing()
  add_executable(eloi_tests tests/tests.cpp)
  target_link_libraries(eloi_tests PRIVATE eloi_core)
  add_test(NAME eloi_tests COMMAND eloi_tests)
endif()
