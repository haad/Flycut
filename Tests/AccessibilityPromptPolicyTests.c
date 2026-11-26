#include "../AccessibilityPromptPolicy.h"

#include <assert.h>
#include <stdbool.h>
#include <stdio.h>

static void test_launch_does_not_show_explanation(void) {
    assert(!FlycutShouldShowAccessibilityExplanation(false, false, false));
}

static void test_first_untrusted_paste_shows_explanation(void) {
    assert(FlycutShouldShowAccessibilityExplanation(true, false, false));
}

static void test_repeated_untrusted_paste_does_not_repeat_explanation(void) {
    assert(!FlycutShouldShowAccessibilityExplanation(true, false, true));
}

static void test_trusted_paste_does_not_show_explanation(void) {
    assert(!FlycutShouldShowAccessibilityExplanation(true, true, false));
}

int main(void) {
    test_launch_does_not_show_explanation();
    test_first_untrusted_paste_shows_explanation();
    test_repeated_untrusted_paste_does_not_repeat_explanation();
    test_trusted_paste_does_not_show_explanation();
    puts("AccessibilityPromptPolicyTests: PASS");
    return 0;
}
