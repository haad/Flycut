#ifndef ACCESSIBILITY_PROMPT_POLICY_H
#define ACCESSIBILITY_PROMPT_POLICY_H

#include <stdbool.h>

static inline bool FlycutShouldShowAccessibilityExplanation(
    bool isPasteAttempt,
    bool isTrusted,
    bool didShowThisSession
) {
    return isPasteAttempt && !isTrusted && !didShowThisSession;
}

#endif
