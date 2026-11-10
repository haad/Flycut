#!/usr/bin/env python3
"""Native regression test for remember-limit store selection."""

from __future__ import annotations

import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]

FIXTURE = r'''
#import <Cocoa/Cocoa.h>
#import "AppController.h"

@interface AppController (RememberLimitTesting)
- (int)checkRememberNumPref:(int)newRemember forPrimaryStore:(BOOL)isPrimaryStore;
- (void)checkFavoritesRememberNumPref:(int)newRemember;
@end

@interface FCRecordingOperator : NSObject {
    BOOL _lastPrimaryStore;
    BOOL _favoritesStoreSelected;
    int _callCount;
    int _switchCount;
    int _restoreCount;
}
@property(nonatomic, assign) BOOL lastPrimaryStore;
@property(nonatomic, assign) BOOL favoritesStoreSelected;
@property(nonatomic, assign) int callCount;
@property(nonatomic, assign) int switchCount;
@property(nonatomic, assign) int restoreCount;
@end

@implementation FCRecordingOperator
@synthesize lastPrimaryStore = _lastPrimaryStore;
@synthesize favoritesStoreSelected = _favoritesStoreSelected;
@synthesize callCount = _callCount;
@synthesize switchCount = _switchCount;
@synthesize restoreCount = _restoreCount;

- (int)rememberNum {
    return 40;
}

- (int)setRememberNum:(int)newRemember forPrimaryStore:(BOOL)isPrimaryStore {
    self.lastPrimaryStore = isPrimaryStore;
    self.callCount += 1;
    return newRemember + (isPrimaryStore ? 1000 : 2000);
}

- (BOOL)favoritesStoreIsSelected {
    return self.favoritesStoreSelected;
}

- (void)switchToFavoritesStore {
    self.switchCount += 1;
    self.favoritesStoreSelected = YES;
}

- (BOOL)restoreStashedStore {
    self.restoreCount += 1;
    self.favoritesStoreSelected = NO;
    return YES;
}
@end

int main(void) {
    @autoreleasepool {
        AppController *controller = [[AppController alloc] init];
        FCRecordingOperator *operator = [[FCRecordingOperator alloc] init];
        [controller setValue:operator forKey:@"flycutOperator"];

        int favoriteResult = [controller checkRememberNumPref:7 forPrimaryStore:NO];
        if (operator.callCount != 1 || operator.lastPrimaryStore != NO) {
            fprintf(stderr, "favorite limit was forwarded as primary\n");
            return 11;
        }
        if (favoriteResult != 2007) {
            fprintf(stderr, "favorite result was not returned: %d\n", favoriteResult);
            return 12;
        }

        int primaryResult = [controller checkRememberNumPref:9 forPrimaryStore:YES];
        if (operator.callCount != 2 || operator.lastPrimaryStore != YES) {
            fprintf(stderr, "primary limit was not forwarded as primary\n");
            return 13;
        }
        if (primaryResult != 1009) {
            fprintf(stderr, "primary result was not returned: %d\n", primaryResult);
            return 14;
        }

        operator.favoritesStoreSelected = YES;
        operator.callCount = 0;
        operator.switchCount = 0;
        operator.restoreCount = 0;
        [controller checkFavoritesRememberNumPref:5];
        if (operator.switchCount != 0 || operator.restoreCount != 0 ||
            operator.favoritesStoreSelected != YES) {
            fprintf(stderr, "already-selected favorites store was switched re-entrantly\n");
            return 15;
        }
        if (operator.callCount != 1 || operator.lastPrimaryStore != NO) {
            fprintf(stderr, "favorites limit did not target the active favorites store\n");
            return 16;
        }

        operator.favoritesStoreSelected = NO;
        operator.callCount = 0;
        operator.switchCount = 0;
        operator.restoreCount = 0;
        [controller checkFavoritesRememberNumPref:6];
        if (operator.switchCount != 1 || operator.restoreCount != 1 ||
            operator.favoritesStoreSelected != NO) {
            fprintf(stderr, "primary store was not restored after temporary favorites edit\n");
            return 17;
        }
        if (operator.callCount != 1 || operator.lastPrimaryStore != NO) {
            fprintf(stderr, "temporary favorites edit targeted the primary store\n");
            return 18;
        }
    }
    return 0;
}
'''


class FavoritesRememberPreferenceTests(unittest.TestCase):
    def test_controller_forwards_store_and_returns_effective_limit(self) -> None:
        sources = [
            ROOT / path
            for path in subprocess.check_output(
                ["/usr/bin/git", "ls-files", "*.m"], cwd=ROOT, text=True
            ).splitlines()
            if path != "main.m"
            and not path.startswith("FlycutHelper/")
            and not path.startswith("Tests/")
        ]
        include_dirs = sorted({ROOT, *(path.parent for path in sources)})

        with tempfile.TemporaryDirectory(prefix="flycut-favorites-limit-") as temp_dir:
            temp = pathlib.Path(temp_dir)
            fixture = temp / "FavoritesRememberFixture.m"
            binary = temp / "FavoritesRememberFixture"
            fixture.write_text(FIXTURE)

            command = [
                "/usr/bin/xcrun",
                "clang",
                "-fno-objc-arc",
                "-fobjc-weak",
                "-fblocks",
                "-fmodules",
                "-DFLYCUT_MAC=1",
                "-mmacosx-version-min=13.5",
                "-arch",
                "arm64",
                "-include",
                str(ROOT / "Flycut_Prefix.pch"),
            ]
            for include_dir in include_dirs:
                command.extend(["-I", str(include_dir)])
            command.extend(str(source) for source in sources)
            command.append(str(fixture))
            for framework in ("Cocoa", "Carbon", "ServiceManagement", "CloudKit"):
                command.extend(["-framework", framework])
            command.extend(["-o", str(binary)])

            build = subprocess.run(
                command,
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=120,
            )
            self.assertEqual(build.returncode, 0, build.stderr)

            run = subprocess.run(
                [str(binary)],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            self.assertEqual(run.returncode, 0, run.stderr)


if __name__ == "__main__":
    unittest.main()
