#pragma once

// Board configuration abstraction for Cheap Yellow Display variants
// Selected at compile time via PlatformIO build flags

#if defined(BOARD_E32R28T)
    #include "cyd_e32r28t.h"
#elif defined(BOARD_CYD_2432S028R)
    #include "cyd_2432s028r.h"
#elif defined(BOARD_CYD_2432S028_V2)
    #include "cyd_2432s028_v2.h"
#elif defined(BOARD_CYD_2432S028C)
    #include "cyd_2432s028c.h"
#else
    #error "No board defined! Add -DBOARD_xxx to build_flags in platformio.ini"
#endif
