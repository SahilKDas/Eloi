cmake_minimum_required(VERSION 3.20)
project(Eloi VERSION 2.7.5 LANGUAGES CXX)
set(ELOI_PRERELEASE "")
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

# CMake 3.29 predates the CXX26 dialect label. Request the compiler's C++26
# mode directly until CMake's standardized CXX26 feature is widely available.
if(MSVC)
  add_compile_options(/std:c++latest)
else()
  add_compile_options(-std=c++2c)
endif()

option(ELOI_BUILD_APP "Build the production Eloi executable" ON)
option(ELOI_SPLIT_PACKAGE
  "Build the Defender-friendly external-assets Windows release package" OFF)
if(ELOI_SPLIT_PACKAGE AND NOT WIN32)
  message(FATAL_ERROR "The Exoskeleton package is Windows-only")
endif()

set(SKIA_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/.deps/skia108/ucrt64"
    CACHE PATH "Root of the Skia UCRT64 package")
if(WIN32 AND ELOI_BUILD_APP AND NOT EXISTS "${SKIA_ROOT}/lib/libskia.a")
  message(FATAL_ERROR "Skia was not found in .deps/skia108/ucrt64. See README.md.")
endif()

add_library(eloi_core STATIC src/chess.cpp src/nnue.cpp src/book.cpp src/config.cpp)
set(ELOI_NNUE_INCLUDE_DIR "" CACHE PATH
    "Experimental NNUE include root; empty preserves the production network")
if(ELOI_NNUE_INCLUDE_DIR)
  if(NOT EXISTS "${ELOI_NNUE_INCLUDE_DIR}/eloi/nnue_weights.hpp")
    message(FATAL_ERROR "Experimental NNUE include root lacks eloi/nnue_weights.hpp")
  endif()
  target_include_directories(eloi_core BEFORE PUBLIC "${ELOI_NNUE_INCLUDE_DIR}")
endif()

# The experimental v3 brain layer is linked separately so merely compiling its
# adapters cannot change the production v2.7.5 executable. Caissa donor files
# are admitted through an explicit audited allowlist in a later stage; never
# glob third_party/caissa.
add_library(eloi_brains STATIC
  src/eloi_brain.cpp
  src/caissa_brain.cpp
  src/hybrid_brain.cpp)
target_link_libraries(eloi_brains PUBLIC eloi_core)
target_include_directories(eloi_brains PUBLIC
  ${CMAKE_CURRENT_SOURCE_DIR}/include
  "${CMAKE_CURRENT_BINARY_DIR}/generated")
if(MSVC)
  target_compile_options(eloi_brains PRIVATE /W4 /permissive-)
else()
  target_compile_options(eloi_brains PRIVATE -Wall -Wextra -Wpedantic)
endif()
target_include_directories(eloi_core PUBLIC
  ${CMAKE_CURRENT_SOURCE_DIR}/include
  "${CMAKE_CURRENT_BINARY_DIR}/generated")
if(MSVC)
  target_compile_options(eloi_core PRIVATE /W4 /permissive-)
else()
  target_compile_options(eloi_core PRIVATE -Wall -Wextra -Wpedantic)
endif()

# Eloi is the sole production executable unless the Exoskeleton release
# option is selected. The default standalone target remains unchanged.
if(ELOI_BUILD_APP)
  set(ELOI_APP_SOURCES
    src/main.cpp
    src/driver.cpp
    src/search_diagnostic.cpp
    src/gui.cpp
    src/version_match.cpp)
  if(ELOI_SPLIT_PACKAGE)
    target_sources(eloi_core PRIVATE src/config_writer.cpp)
    add_compile_definitions(ELOI_EXTERNAL_ASSETS ELOI_SEPARATE_LICHESS_EXE)
  else()
    list(APPEND ELOI_APP_SOURCES src/lichess.cpp src/resources.rc)
  endif()
  if(WIN32)
    list(APPEND ELOI_APP_SOURCES
      "${CMAKE_CURRENT_BINARY_DIR}/generated/version.rc")
  endif()
  add_executable(Eloi ${ELOI_APP_SOURCES})
  target_link_libraries(Eloi PRIVATE eloi_core)
  if(ELOI_SPLIT_PACKAGE)
    configure_file(
      src/version-lichess.rc.in
      "${CMAKE_CURRENT_BINARY_DIR}/generated/version-lichess.rc"
      @ONLY)
    add_executable(EloiLichess
      src/lichess_main.cpp
      src/lichess.cpp
      src/lichess_config_gui.cpp
      "${CMAKE_CURRENT_BINARY_DIR}/generated/version-lichess.rc")
    target_link_libraries(EloiLichess PRIVATE eloi_core)
  endif()
endif()

if(NOT MSVC)
  # Keep release code generation reproducible. CMake's IPO property expands to
  # -flto=auto with GCC, which makes the partition count host-dependent. A
  # single LTO partition is slower to link but stable across clean builds.
  set(ELOI_REPRO_COMPILE_FLAGS
    -O3
    -ffunction-sections
    -fdata-sections
    -flto=1
    "-ffile-prefix-map=${CMAKE_SOURCE_DIR}=."
    "-ffile-prefix-map=${CMAKE_BINARY_DIR}=."
    "-fdebug-prefix-map=${CMAKE_SOURCE_DIR}=."
    "-fdebug-prefix-map=${CMAKE_BINARY_DIR}=."
    "-frandom-seed=eloi-${ELOI_VERSION}")
  target_compile_options(eloi_core PRIVATE
    $<$<CONFIG:Release>:${ELOI_REPRO_COMPILE_FLAGS}>)
  if(ELOI_BUILD_APP)
    target_compile_options(Eloi PRIVATE
      $<$<CONFIG:Release>:${ELOI_REPRO_COMPILE_FLAGS}>)
    target_link_options(Eloi PRIVATE
      $<$<CONFIG:Release>:-flto=1;-Wl,--gc-sections,--no-insert-timestamp;-s>)
    if(ELOI_SPLIT_PACKAGE)
      target_compile_options(EloiLichess PRIVATE
        $<$<CONFIG:Release>:${ELOI_REPRO_COMPILE_FLAGS}>)
      target_link_options(EloiLichess PRIVATE
        $<$<CONFIG:Release>:-flto=1;-Wl,--gc-sections,--no-insert-timestamp;-s>)
    endif()
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
  set(ELOI_GUI_LIBRARIES
    "${SKIA_ROOT}/lib/libskia.a"
    "${ELOI_STATIC_ROOT}/lib/libjpeg.a"
    "${ELOI_STATIC_ROOT}/lib/libpng16.a"
    "${ELOI_STATIC_ROOT}/lib/libwebpdemux.a"
    "${ELOI_STATIC_ROOT}/lib/libwebpmux.a"
    "${ELOI_STATIC_ROOT}/lib/libwebp.a"
    "${ELOI_STATIC_ROOT}/lib/libsharpyuv.a"
    "${ELOI_STATIC_ROOT}/lib/libzs.a"
    gdi32 user32 comdlg32 shell32 ole32 oleaut32 uuid usp10 opengl32 bcrypt
  )
  target_link_libraries(Eloi PRIVATE ${ELOI_GUI_LIBRARIES})
  if(ELOI_SPLIT_PACKAGE)
    target_link_libraries(EloiLichess PRIVATE winhttp user32 gdi32)
  else()
    target_link_libraries(Eloi PRIVATE winhttp)
    target_link_options(Eloi PRIVATE
      $<$<CONFIG:Release>:-static;-static-libgcc;-static-libstdc++>)
  endif()

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
  add_executable(eloi_tests tests/tests.cpp src/config_writer.cpp)
  target_link_libraries(eloi_tests PRIVATE eloi_core)
  target_compile_definitions(eloi_tests PRIVATE
    ELOI_TEST_DATA_DIR="${CMAKE_CURRENT_SOURCE_DIR}/tests")
  if(NOT MSVC)
    target_link_options(eloi_tests PRIVATE $<$<CONFIG:Release>:-flto=1>)
  endif()
  add_test(NAME eloi_tests COMMAND eloi_tests)
  add_executable(eloi_hybrid_tests tests/hybrid_tests.cpp)
  target_link_libraries(eloi_hybrid_tests PRIVATE eloi_brains)
  add_test(NAME eloi_hybrid_tests COMMAND eloi_hybrid_tests)
  set_tests_properties(eloi_hybrid_tests PROPERTIES TIMEOUT 30)
  if(WIN32 AND ELOI_BUILD_APP)
    add_executable(eloi_gui_tests tests/gui_smoke.cpp src/version_match.cpp)
    target_link_libraries(eloi_gui_tests PRIVATE eloi_core ${ELOI_GUI_LIBRARIES})
    target_include_directories(eloi_gui_tests PRIVATE "${SKIA_ROOT}/include/skia")
    if(ELOI_SPLIT_PACKAGE)
      add_custom_command(TARGET eloi_gui_tests POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_directory
          "${CMAKE_CURRENT_SOURCE_DIR}/assets/chess_maestro_bw"
          "$<TARGET_FILE_DIR:eloi_gui_tests>/assets/chess_maestro_bw")
    else()
      target_sources(eloi_gui_tests PRIVATE src/resources.rc)
      target_link_options(eloi_gui_tests PRIVATE -static -static-libgcc -static-libstdc++)
    endif()
    add_test(NAME eloi_gui_tests COMMAND eloi_gui_tests)
    set_tests_properties(eloi_gui_tests PROPERTIES TIMEOUT 30)
  endif()
endif()
