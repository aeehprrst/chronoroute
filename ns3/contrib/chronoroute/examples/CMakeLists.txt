build_lib_example(
  NAME tcrh-wire-check
  SOURCE_FILES tcrh-wire-check.cc
  LIBRARIES_TO_LINK
    ${libchronoroute}
    ${libinternet}
    ${libpoint-to-point}
    ${libnetwork}
    ${libcore}
)

# Course milestone: the REAL Starlink 463 km sub-shell from a scenario bundle,
# with link delays/states every 100 ms and a time-varying schedule. NetAnim
# (slice run) and mobility (positions for the slice) are linked here only.
build_lib_example(
  NAME chronoroute-leo
  SOURCE_FILES chronoroute-leo.cc
  LIBRARIES_TO_LINK
    ${libchronoroute}
    ${libinternet}
    ${libpoint-to-point}
    ${libnetwork}
    ${libmobility}
    ${libnetanim}
    ${libcore}
)
