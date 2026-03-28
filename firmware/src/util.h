#pragma once

#include <string.h>
#include <stdint.h>

// Type-safe string copy: derives buffer size from the destination array type.
template<size_t N>
inline void safeCopy(char (&dst)[N], const char* src) {
    strncpy(dst, src, N - 1);
    dst[N - 1] = '\0';
}

// Rows within the animation sprite that contain the character + all decorations.
// Pushing only this band instead of the full 240-row sprite cuts SPI time by ~30%.
// Shared between display_manager (sprite allocation/push) and clawd_anim (arrow
// positioning) so both agree on the renderable bounds.
static constexpr int16_t ANIM_DIRTY_Y0 = 50;   // first dirty row in sprite coords
static constexpr int16_t ANIM_DIRTY_Y1 = 215;  // last dirty row  (exclusive)
