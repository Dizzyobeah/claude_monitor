#pragma once
#include "animation.h"
#include "../session_store.h"
#include "../util.h"

// =============================================================================
// ClawdAnimation — single class that handles all 6 session states.
//
// Character is built from 7 fillRect calls on a ~16×11 logical pixel grid.
// S = 11px per logical pixel → character body ~110×88px on screen,
// centered in the 240×240 animation zone.
//
// Coordinate system: all draws are sprite-relative, origin (0,0) = top-left
// of the 240×240 animation canvas passed in via draw().
//
// Eye modes:
//   EYE_OPEN   — standard dark hole rectangles
//   EYE_CLOSED — thin horizontal bar (blink frame)
//   EYE_WIDE   — taller eye rect (alarmed)
//   EYE_X      — X drawn over holes (error)
// =============================================================================

class ClawdAnimation : public Animation {
public:
    // Called by DisplayManager on every state transition
    void setState(SessionState s) { _state = s; }

    // Returns true if the animation phase has advanced enough to produce a new
    // visual frame. DisplayManager uses this to skip pushSprite on still frames,
    // saving ~15ms of SPI bandwidth per skipped frame.
    bool isDirty() const { return _dirty; }

    void begin() override {
        _phase = 0;
        _dirty = true;
    }

    void update(uint32_t elapsed_ms) override {
        uint32_t prev = _phase;
        _phase += elapsed_ms;

        // Determine whether the phase change is large enough to move a pixel.
        // Use the fastest animation period in any state (PERMISSION shake = 200ms,
        // TOOL_USE walk = 400ms) as the threshold: if phase advanced by at least
        // 1/256th of the fastest period, something has moved.
        static constexpr uint32_t MIN_DIRTY_DELTA = 200 / 256 + 1; // ~1ms
        _dirty = (_phase - prev) >= MIN_DIRTY_DELTA;
    }

    void draw(lgfx::LovyanGFX* canvas, int16_t x, int16_t y, int16_t w, int16_t h) override {
        // Character logical pixel size
        static constexpr int16_t S = 11;

        // Character center in the sprite canvas (sprite-relative)
        // Body is 10 logical wide → 110px. Center at x=120, margin=10 each side.
        // Body is 8 logical tall  →  88px. Center at y=100.
        int16_t cx = x + w / 2;  // 120
        int16_t cy = y + h / 2;  // 100  (used as vertical center of body)

        // --- Per-state derived values ---
        int16_t shakeX = 0;
        int16_t shakeY = 0;
        uint16_t bodyColor = Colors::BODY_DEFAULT;
        uint8_t eyeMode = EYE_OPEN;
        int8_t  legPhase = 0;  // 0 = standing; signed offset for walk cycle

        switch (_state) {

            // ------------------------------------------------------------------
            case SessionState::IDLE: {
                // Slow vertical sine bob ±3px
                uint8_t bobAngle = (uint8_t)((_phase * 256) / 3000);
                shakeY = (isin(bobAngle) * 3) / 127;
                eyeMode = EYE_OPEN;
                legPhase = 0;
                break;
            }

            // ------------------------------------------------------------------
            case SessionState::THINKING: {
                // Slow walk cycle: legs alternate, period 800ms
                uint8_t walkAngle = (uint8_t)((_phase * 256) / 800);
                legPhase = (isin(walkAngle) * S) / 127; // ±S vertical offset on legs
                eyeMode = ((_phase % 3000) < 150) ? EYE_CLOSED : EYE_OPEN; // blink briefly every 3s
                break;
            }

            // ------------------------------------------------------------------
            case SessionState::TOOL_USE: {
                // Fast walk cycle, period 400ms
                uint8_t walkAngle = (uint8_t)((_phase * 256) / 400);
                legPhase = (isin(walkAngle) * S) / 127;
                eyeMode = EYE_OPEN;
                // Purple body tint
                bodyColor = Colors::BODY_TOOL;
                break;
            }

            // ------------------------------------------------------------------
            case SessionState::PERMISSION: {
                // Fast horizontal shake ±S pixels, period 200ms
                uint8_t shakeAngle = (uint8_t)((_phase * 256) / 200);
                shakeX = (isin(shakeAngle) * S) / 127;
                eyeMode = EYE_WIDE;
                legPhase = 0;
                break;
            }

            // ------------------------------------------------------------------
            case SessionState::INPUT_NEEDED: {
                eyeMode = ((_phase % 1200) < 100) ? EYE_CLOSED : EYE_OPEN; // brief blink every 1.2s
                legPhase = 0;
                break;
            }

            // ------------------------------------------------------------------
            case SessionState::ERROR: {
                // Decaying shake — strongest at begin(), fades over 500ms, repeats every 2s
                uint32_t shakePhase = _phase % 2000;
                if (shakePhase < 500) {
                    uint8_t sa = (uint8_t)((shakePhase * 256) / 100);
                    int32_t decay = (int32_t)(500 - shakePhase);
                    shakeX = (int16_t)((isin(sa) * decay * 6) / (127 * 500));
                }
                eyeMode = EYE_X;
                bodyColor = Colors::BODY_ERROR;
                legPhase = 0;
                break;
            }

            default:
                break;
        }

        // --- State-specific extras drawn BEHIND the character ---
        drawStateExtrasBack(canvas, cx + shakeX, cy + shakeY, S, bodyColor);

        // --- Draw the Clawd character ---
        drawClawd(canvas, cx + shakeX, cy + shakeY, S, bodyColor, eyeMode, legPhase);

        // --- State-specific extras drawn IN FRONT of the character ---
        drawStateExtrasFront(canvas, cx + shakeX, cy + shakeY, S, w, h);
    }

private:
    // -------------------------------------------------------------------------
    // Eye mode constants
    static constexpr uint8_t EYE_OPEN   = 0;
    static constexpr uint8_t EYE_CLOSED = 1;
    static constexpr uint8_t EYE_WIDE   = 2;
    static constexpr uint8_t EYE_X      = 3;

    SessionState _state = SessionState::IDLE;
    uint32_t     _phase = 0;
    bool         _dirty = true;

    // -------------------------------------------------------------------------
    // drawClawd — renders the character at logical-pixel center (cx, cy).
    //
    // Layout (logical grid, S px per cell):
    //
    //   col:    0  1  2  3  4  5  6  7  8  9  10  11
    //           |  |  |  |  |  |  |  |  |  |  |   |
    //   row 0:        [  B  O  D  Y     (10W)    ]
    //   row 1:        [                          ]
    //   row 2:        [  lE ]           [  rE ]
    //   row 3:        [    ]            [    ]
    //   row 4:  [LA]  [                          ] [RA]
    //   row 5:  [  ]  [                          ] [  ]
    //   row 6:        [  lL ]           [  rL ]
    //   row 7:        [    ]            [    ]
    //   row 8:        [    ]            [    ]
    //
    // Body top-left in screen coords:  cx - 5*S,  cy - 4*S
    // (body is 10S wide × 8S tall, so center of body is cx, cy exactly)
    // -------------------------------------------------------------------------
    void drawClawd(lgfx::LovyanGFX* canvas,
                   int16_t cx, int16_t cy,
                   int16_t S,
                   uint16_t bodyColor,
                   uint8_t eyeMode,
                   int8_t legPhase)
    {
        uint16_t dark = canvas->color565(15, 1, 0);  // near-black eye holes / X lines

        int16_t bx = cx - 5 * S;  // body left
        int16_t by = cy - 4 * S;  // body top

        // 1. Main body: 10W × 8H
        canvas->fillRect(bx, by, 10 * S, 8 * S, bodyColor);

        // 2. Left arm: 2W × 2H at (bx - 2S, by + 4S)
        canvas->fillRect(bx - 2 * S, by + 4 * S, 2 * S, 2 * S, bodyColor);

        // 3. Right arm: 2W × 2H at (bx + 10S, by + 4S)
        canvas->fillRect(bx + 10 * S, by + 4 * S, 2 * S, 2 * S, bodyColor);

        // 4 & 5. Eyes — position depends on mode
        int16_t lEyeX = bx + 1 * S;
        int16_t rEyeX = bx + 6 * S;
        int16_t eyeY  = by + 2 * S;

        switch (eyeMode) {
            case EYE_OPEN:
                canvas->fillRect(lEyeX, eyeY, 2 * S, 2 * S, dark);
                canvas->fillRect(rEyeX, eyeY, 2 * S, 2 * S, dark);
                break;
            case EYE_CLOSED:
                // Thin horizontal bars — 1px tall, centered in the eye area
                canvas->fillRect(lEyeX, eyeY + S - 1, 2 * S, 2, dark);
                canvas->fillRect(rEyeX, eyeY + S - 1, 2 * S, 2, dark);
                break;
            case EYE_WIDE:
                // Taller: 2W × 3H (one extra row)
                canvas->fillRect(lEyeX, eyeY, 2 * S, 3 * S, dark);
                canvas->fillRect(rEyeX, eyeY, 2 * S, 3 * S, dark);
                break;
            case EYE_X:
                // Draw dark hole then overlay an X in red
                canvas->fillRect(lEyeX, eyeY, 2 * S, 2 * S, dark);
                canvas->fillRect(rEyeX, eyeY, 2 * S, 2 * S, dark);
                // X lines over each eye
                for (int t = -1; t <= 1; t++) {
                    canvas->drawLine(lEyeX + t,         eyeY,         lEyeX + 2*S-1 + t, eyeY + 2*S-1, 0xF800);
                    canvas->drawLine(lEyeX + 2*S-1 + t, eyeY,         lEyeX + t,         eyeY + 2*S-1, 0xF800);
                    canvas->drawLine(rEyeX + t,         eyeY,         rEyeX + 2*S-1 + t, eyeY + 2*S-1, 0xF800);
                    canvas->drawLine(rEyeX + 2*S-1 + t, eyeY,         rEyeX + t,         eyeY + 2*S-1, 0xF800);
                }
                break;
        }

        // 6 & 7. Legs: 2W × 3H each, anchored at base of body.
        // legPhase is a signed vertical offset; left leg rises when right descends.
        // We use abs(legPhase) for the extension magnitude and flip sign per leg so
        // neither leg ever moves ABOVE legBaseY, preventing ghost pixels above the
        // body that persist until the next fillScreen.
        int16_t lLegX   = bx + 1 * S;
        int16_t rLegX   = bx + 6 * S;
        int16_t legBaseY = by + 8 * S;  // top of leg rects when standing straight

        // Clamp: legs only extend downward from legBaseY (positive direction).
        // lp is always >= 0; one leg extends by lp, the other by (S - lp) so
        // the stride looks natural and symmetric.
        int16_t lp = (legPhase >= 0) ? legPhase : -legPhase; // abs
        canvas->fillRect(lLegX, legBaseY + lp,       2 * S, 3 * S, bodyColor);
        canvas->fillRect(rLegX, legBaseY + (S - lp), 2 * S, 3 * S, bodyColor);
    }

    // -------------------------------------------------------------------------
    // Extras drawn BEHIND the character (e.g. glow rings, red glow)
    // -------------------------------------------------------------------------
    void drawStateExtrasBack(lgfx::LovyanGFX* canvas,
                              int16_t cx, int16_t cy,
                              int16_t S,
                              uint16_t /*bodyColor*/)
    {
        switch (_state) {

            case SessionState::IDLE: {
                // Subtle glow ring under feet
                int16_t S8 = 8 * S; // body height
                int16_t feetY = cy + S8 / 2 + 3 * S; // bottom of legs
                uint8_t glowAngle = (uint8_t)((_phase * 256) / 3000);
                int8_t gp = isin(glowAngle);
                uint8_t glowBright = 30 + (gp + 127) * 20 / 254;
                for (int r = 5 * S; r >= 3 * S; r -= S) {
                    uint8_t fade = glowBright * (r - 2 * S) / (3 * S);
                    uint16_t gc = canvas->color565(fade / 4, fade / 3, fade);
                    canvas->drawEllipse(cx, feetY, r, S / 2, gc);
                }
                break;
            }

            case SessionState::ERROR: {
                // Red glow underneath — pulsing
                uint8_t glowAngle = (uint8_t)((_phase * 256) / 2000);
                int8_t gp = isin(glowAngle);
                int16_t glowR = 4 * S + (gp * S) / 127;
                uint8_t glowBright = 50 + (gp + 127) * 30 / 254;
                int16_t feetY = cy + 4 * S + 3 * S;
                canvas->fillEllipse(cx, feetY, glowR, glowR / 3,
                                    canvas->color565(glowBright, 0, 0));
                break;
            }

            default:
                break;
        }
    }

    // -------------------------------------------------------------------------
    // Extras drawn IN FRONT of the character.
    // w/h = canvas dimensions, used by _drawAttentionArrows.
    // -------------------------------------------------------------------------
    void drawStateExtrasFront(lgfx::LovyanGFX* canvas,
                               int16_t cx, int16_t cy,
                               int16_t S,
                               int16_t canvasW, int16_t canvasH)
    {
        switch (_state) {

            // ------------------------------------------------------------------
            case SessionState::THINKING: {
                // Animated "..." dots above head
                int16_t dotsY = cy - 4 * S - 18; // above body top
                for (int i = 0; i < 3; i++) {
                    uint8_t dotAngle = (uint8_t)((_phase * 256) / 600) + i * 85;
                    int16_t dy = (isin(dotAngle) * 5) / 127;
                    bool lit = ((_phase / 400 + i) % 3) == 0;
                    uint16_t dc = lit ? Colors::CLAUDE_ORANGE : Colors::TEXT_DIM;
                    canvas->fillCircle(cx - 12 + i * 12, dotsY + dy, 4, dc);
                }
                break;
            }

            // ------------------------------------------------------------------
            case SessionState::TOOL_USE: {
                // 4-spoke spinning cross/star icon — top-right of character
                int16_t gx = cx + 5 * S + 16; // right of body + margin
                int16_t gy = cy - 4 * S + 16; // near top
                uint8_t spinAngle = (uint8_t)((_phase * 256) / 1000);
                uint16_t spokeColor = Colors::PURPLE_TOOL;
                uint16_t hubColor   = Colors::CYAN_INFO;
                int16_t spokeLen = 12;
                // Draw 4 spokes at 0°, 90°, 180°, 270° + spin offset
                for (int s = 0; s < 4; s++) {
                    uint8_t a = spinAngle + (uint8_t)(s * 64);
                    int16_t ex = gx + (icos(a) * spokeLen) / 127;
                    int16_t ey = gy + (isin(a) * spokeLen) / 127;
                    // Thick spoke — 3 lines
                    for (int t = -1; t <= 1; t++) {
                        canvas->drawLine(gx + t, gy, ex + t, ey, spokeColor);
                        canvas->drawLine(gx, gy + t, ex, ey + t, spokeColor);
                    }
                }
                canvas->fillCircle(gx, gy, 4, hubColor);
                // Outer ring
                canvas->drawCircle(gx, gy, spokeLen + 3, spokeColor);
                break;
            }

            // ------------------------------------------------------------------
            case SessionState::PERMISSION: {
                // Pulsing red border around the character bounding box
                // Character: body 10S wide × 8S tall, arms add 2S each side,
                // legs add 3S below → bounding box: 14S wide × (8+3)S tall
                int16_t bx = cx - 5 * S;
                int16_t by = cy - 4 * S;
                int16_t bw = 10 * S;
                int16_t bh = 8 * S + 3 * S; // body + legs

                // include arms
                int16_t boxX = bx - 2 * S - 4;
                int16_t boxY = by - 4;
                int16_t boxW = bw + 4 * S + 8;
                int16_t boxH = bh + 8;

                uint8_t pulseAngle = (uint8_t)((_phase * 256) / 700);
                uint8_t intensity  = 128 + isin(pulseAngle);
                uint16_t borderColor = canvas->color565(intensity, 0, 0);
                for (int i = 0; i < 3; i++)
                    canvas->drawRect(boxX - i, boxY - i, boxW + 2*i, boxH + 2*i, borderColor);

                // Blinking inward-pointing arrows near bottom of sprite (above footer)
                _drawAttentionArrows(canvas, canvasW, canvasH, Colors::YELLOW_WARN);
                break;
            }

            // ------------------------------------------------------------------
            case SessionState::INPUT_NEEDED: {
                // Blinking cursor "_" to the right of the character
                if (((_phase / 500) % 2) == 0) {
                    int16_t curX = cx + 5 * S + 8;
                    int16_t curY = cy;
                    canvas->fillRect(curX, curY, 10, 3, Colors::CLAUDE_ORANGE);
                }

                // Blinking inward-pointing arrows near bottom of sprite (above footer)
                _drawAttentionArrows(canvas, canvasW, canvasH, Colors::CYAN_INFO);
                break;
            }

            default:
                break;
        }
    }

    // -------------------------------------------------------------------------
    // _drawAttentionArrows — blinking left/right inward arrows rendered into
    // the sprite near the bottom edge, so they live inside the double-buffered
    // zone and never cause footer tearing.
    //
    // canvasH is passed in from draw() instead of hardcoding 240, so this works
    // correctly if ANIM_H is ever changed.
    // -------------------------------------------------------------------------
    void _drawAttentionArrows(lgfx::LovyanGFX* canvas, int16_t canvasW, int16_t canvasH, uint16_t color) {
        // Clamp to the dirty-band sprite height so arrows are visible when the
        // sprite is smaller than canvasH (dirty-band optimization in DisplayManager).
        static constexpr int16_t BAND_H = ANIM_DIRTY_Y1 - ANIM_DIRTY_Y0;
        int16_t ay = min((int16_t)(canvasH - 12), (int16_t)(BAND_H - 8));
        bool visible = ((_phase / 300) % 2) == 0;
        uint16_t arrowColor = visible ? color : Colors::BG_DARK;
        // Left arrow (pointing right →)
        canvas->fillTriangle(5,            ay,     15,            ay - 5, 15,            ay + 5, arrowColor);
        // Right arrow (pointing left ←)
        canvas->fillTriangle(canvasW - 6,  ay,     canvasW - 16,  ay - 5, canvasW - 16,  ay + 5, arrowColor);
    }
};
