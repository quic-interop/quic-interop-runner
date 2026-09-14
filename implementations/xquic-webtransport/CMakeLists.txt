cmake_minimum_required(VERSION 3.16)
project(xquic_webtransport_interop C)

set(XQUIC_SOURCE "" CACHE PATH "XQUIC source checkout")
set(XQUIC_BUILD "" CACHE PATH "Directory containing libxquic-static.a")
set(BORINGSSL_ROOT "" CACHE PATH "BoringSSL source and build directory")
option(XQUIC_COVERAGE "Link a coverage-instrumented XQUIC archive" OFF)

if(NOT EXISTS "${XQUIC_SOURCE}/include/xquic/xqc_webtransport.h")
    message(FATAL_ERROR "XQUIC_SOURCE must identify a WebTransport checkout")
endif()
find_library(XQUIC_LIBRARY NAMES xquic-static
    PATHS "${XQUIC_BUILD}" NO_DEFAULT_PATH REQUIRED)
find_library(BORINGSSL_SSL NAMES ssl PATHS
    "${BORINGSSL_ROOT}/build" "${BORINGSSL_ROOT}/build/ssl"
    NO_DEFAULT_PATH REQUIRED)
find_library(BORINGSSL_CRYPTO NAMES crypto PATHS
    "${BORINGSSL_ROOT}/build" "${BORINGSSL_ROOT}/build/crypto"
    NO_DEFAULT_PATH REQUIRED)
find_path(LIBEVENT_INCLUDE_DIR event2/event.h REQUIRED)
find_library(LIBEVENT_LIBRARY NAMES event REQUIRED)
find_package(Threads REQUIRED)

add_library(interop_dependencies INTERFACE)
target_include_directories(interop_dependencies INTERFACE
    "${XQUIC_SOURCE}/include" "${BORINGSSL_ROOT}/include"
    "${LIBEVENT_INCLUDE_DIR}")
target_link_libraries(interop_dependencies INTERFACE
    "${XQUIC_LIBRARY}" "${BORINGSSL_SSL}" "${BORINGSSL_CRYPTO}"
    "${LIBEVENT_LIBRARY}" Threads::Threads ${CMAKE_DL_LIBS} m stdc++)
if(XQUIC_COVERAGE)
    target_link_options(interop_dependencies INTERFACE --coverage)
endif()

foreach(role client server)
    add_executable(wt_interop_${role}
        runtime.c xqc_wt_interop.c xqc_wt_interop_protocol.c)
    target_compile_features(wt_interop_${role} PRIVATE c_std_11)
    target_compile_options(wt_interop_${role} PRIVATE
        -Wall -Wextra -Werror -Wno-unused-parameter)
    target_link_libraries(wt_interop_${role} PRIVATE interop_dependencies)
    install(TARGETS wt_interop_${role} RUNTIME DESTINATION bin)
endforeach()

enable_testing()
add_executable(wt_interop_protocol_test
    test_protocol.c xqc_wt_interop_protocol.c)
add_executable(wt_interop_application_test
    test_application.c xqc_wt_interop_protocol.c)
target_link_libraries(wt_interop_application_test PRIVATE interop_dependencies)
add_test(NAME wt_interop_protocol COMMAND wt_interop_protocol_test)
add_test(NAME wt_interop_application COMMAND wt_interop_application_test)
