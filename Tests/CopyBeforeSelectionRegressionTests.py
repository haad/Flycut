#!/usr/bin/env python3
"""A copy made just before the bezel, the menu-bar list or the search window opens is in the
history first, and choosing an older clipping there never loses it.

Flycut polls the clipboard once a second. A copy made less than that before a selection opens was
not polled yet; the chosen clipping then took its place on the clipboard, Flycut never captures
its own write, and the copy was gone from both. The production -hitMainHotKey: and
-listControllerDidOpen: run on the real AppController and FlycutOperator of
FavoritesViewRegressionTests' fixture (in-memory clipboard, bezel and defaults). The catch-up runs
at once: the history is checked right after the call, before any queue is drained.

Rich text and image data are never read on the main thread there: a stand-in for a slow
provider (another device, an app that renders a promise) delivers the data it was asked for two
seconds later, and opening the bezel must not wait for it beyond a small bound. When the clipboard
changes while it waits, the stand-in answers as a real pasteboard does: with Flycut's own newer
write for that type or with nothing, never with the copy's data. Rows go in complete only: a copy
of plain text alone at once, a formatted copy and an image when their read ends with the copy
still on the clipboard, below every row of a newer copy. A read that spans a clipboard change (a
choice in the bezel, a newer copy) drops the copy: no row, never one of its text alone or with
another clipping's data, and one fixed log line. A row with the same text keeps its formatting
until the copy's own arrives, and no copy gets two rows.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import tempfile
import unittest

import FavoritesViewRegressionTests as base

ROOT = base.ROOT
APP_CONTROLLER = ROOT / "AppController.m"
CASES = r"""
        // The independent review's two probes (equal-top-wipe, stale-image-on-top), as they were written.
        if ([mode isEqualToString:@"equal-top-wipe"]) {
            FCTimedData([NSSet setWithObjects:NSPasteboardTypeRTF, NSPasteboardTypeHTML, nil], 0.0);
            [pasteboard copyText:@"same-rich"];
            [pasteboard setData:[@"{\\rtf1 old}" dataUsingEncoding:NSUTF8StringEncoding] forType:NSPasteboardTypeRTF];
            [controller pollPB:nil]; [controller drainCaptures];
            BOOL seeded = [[[Contents(historyStore) firstObject] description] isEqualToString:@"same-rich"] && RichRTF(0) != nil;
            FCTimedData([NSSet setWithObjects:NSPasteboardTypeRTF, NSPasteboardTypeHTML, nil], 2.0);
            timedQueueOnly = YES;
            [pasteboard copyText:@"same-rich"];
            [pasteboard setData:[@"{\\rtf1 new}" dataUsingEncoding:NSUTF8StringEncoding] forType:NSPasteboardTypeRTF];
            [controller hitMainHotKey:nil];
            BOOL richAtOpen = RichRTF(0) != nil;
            NSString *chosen = Selected();
            Key(@"\r", 36, 0);                      // the user pastes the newest row (same text)
            Spin(0.1);
            [controller pollPB:nil];
            [controller drainCaptures];
            Spin(0.3);
            [controller drainCaptures];
            BOOL richAfter = RichRTF(0) != nil;
            BOOL savedAfter = SavedRichRTF(0) != nil;
            BOOL clipboardRich = [pasteboard dataForType:NSPasteboardTypeRTF] != nil;
            printf("REPORT equal-top-wipe seeded=%d top=%s chosen=%s richAtOpen=%d richAfter=%d savedAfter=%d clipboardRTF=%d count=%lu\n",
                   seeded, [[Contents(historyStore) firstObject] UTF8String], [chosen UTF8String], richAtOpen, richAfter,
                   savedAfter, clipboardRich, (unsigned long)[Contents(historyStore) count]);
            if (!seeded) return Emit(301);
            if (!richAfter) return Emit(302);       // the newest row lost the formatting it had
            return Emit(0);
        }
        if ([mode isEqualToString:@"stale-image-on-top"]) {
            NSArray *before = Contents(historyStore);
            FCTimedData([NSSet setWithObjects:NSPasteboardTypeRTF, NSPasteboardTypeHTML, NSPasteboardTypePNG,
                                              NSPasteboardTypeTIFF, @"com.compuserve.gif", nil], 2.0);
            timedQueueOnly = YES;
            [pasteboard copyData:PNG(4) ofType:NSPasteboardTypePNG];
            [controller hitMainHotKey:nil];          // catch-up: the image read starts (2 s)
            Escape();
            [pasteboard copyText:@"newer-text"];      // the user copies again ...
            [controller hitMainHotKey:nil];          // ... and opens the bezel again: caught up inline
            NSArray *atSecondOpen = Contents(historyStore);
            Escape();
            Spin(0.1);
            [controller drainCaptures];
            Spin(0.3);
            [controller drainCaptures];
            NSArray *after = Contents(historyStore);
            NSString *clip = [pasteboard stringForType:NSPasteboardTypeString];
            printf("REPORT stale-image-on-top before=%lu atSecondOpen0=%s after0=%s after1=%s count=%lu clipboard=%s\n",
                   (unsigned long)[before count], [[atSecondOpen firstObject] UTF8String], [[after firstObject] UTF8String],
                   [after count] > 1 ? [[after objectAtIndex:1] UTF8String] : "-", (unsigned long)[after count],
                   clip ? [clip UTF8String] : "(no text)");
            if (![[atSecondOpen firstObject] isEqualToString:@"newer-text"]) return Emit(311);
            if (![[after firstObject] isEqualToString:@"newer-text"]) return Emit(312);   // an older copy above the newest
            return Emit(0);
        }
        if ([mode hasPrefix:@"catch-up-"]) {
            NSArray *before = Contents(historyStore);
            BOOL slow = [mode hasSuffix:@"-slow"];
            BOOL rich = [mode hasPrefix:@"catch-up-rich-"];
            BOOL gif = [mode hasPrefix:@"catch-up-gif-"];
            FCTimedData([NSSet setWithObjects:NSPasteboardTypeRTF, NSPasteboardTypeHTML, NSPasteboardTypePNG,
                                              NSPasteboardTypeTIFF, @"com.compuserve.gif", nil], slow ? 2.0 : 0.0);
            NSString *want = @"<image>";
            if (rich) {
                [pasteboard copyText:@"rich-just-before"];
                [pasteboard setData:[@"{\\rtf1 rich}" dataUsingEncoding:NSUTF8StringEncoding] forType:NSPasteboardTypeRTF];
                want = @"rich-just-before";
            } else {
                [pasteboard copyData:PNG(4) ofType:NSPasteboardTypePNG];
                if (gif) {
                    // A browser's "Copy Image" of an animated GIF: a still plus HTML naming the file.
                    [[NSUserDefaults standardUserDefaults] setBool:YES forKey:@"downloadAnimatedGIFs"];
                    [pasteboard setData:[@"<img src=\"https://example.test/anim.gif\">" dataUsingEncoding:NSUTF8StringEncoding]
                                forType:NSPasteboardTypeHTML];
                }
            }
            NSDate *start = [NSDate date];
            [controller hitMainHotKey:nil];
            NSTimeInterval opened = -[start timeIntervalSinceNow];
            Observe(@"1-bezel-open");
            report[@"0-timing"] = @{@"openSeconds": @(opened), @"mainThreadDataReads": @(timedMainThreadReads),
                                   @"queueDataReads": @(timedQueueReads), @"gifDownloads": @(gifDownloads)};
            NSArray *withCopy = [@[want] arrayByAddingObjectsFromArray:before];
            if (timedMainThreadReads != 0) return Emit(231);   // rich text, HTML or image data read on the main thread
            if (opened > 1.0) return Emit(232);                 // opening waited for the slow read
            if (gif) {
                if (gifDownloads != 0 || ![Contents(historyStore) isEqualToArray:before]) return Emit(237);
            } else if (!slow) {
                // Read in time: the newest row at once, complete.
                if (![Contents(historyStore) isEqualToArray:withCopy]) return Emit(233);
                if (rich && RichRTF(0) == nil) return Emit(238);   // a formatted copy's row is complete
            } else if (![Contents(historyStore) isEqualToArray:before]) return Emit(234);   // never a row of its text alone
            Escape();
            [controller drainCaptures];                         // the slow read ends and commits
            Observe(@"2-after-read");
            if (gif) {
                // The download (stubbed) starts once the HTML is read; it adds the GIF, not the still.
                if (gifDownloads != 1 || !gifDownloadOnMain || ![gifDownloadURL isEqualToString:@"https://example.test/anim.gif"])
                    return Emit(239);
                if (![Contents(historyStore) isEqualToArray:before] || timedMainThreadReads != 0) return Emit(240);
                return Emit(0);
            }
            if (![Contents(historyStore) isEqualToArray:withCopy]) return Emit(235);            // the copy was lost
            if (timedMainThreadReads != 0 || timedQueueReads == 0) return Emit(236);
            if (rich && (RichRTF(0) == nil || SavedRichRTF(0) == nil)) return Emit(241);   // its formatting was not added to its row and saved
            return Emit(0);
        }

        // The user chooses in the bezel before a slow read of the copy ends (a 2 s provider):
        // Return pastes the newest row the bezel shows, which replaces the copy on the clipboard
        // while it is read. The read then answers with the choice's data or with none, never with
        // the copy's: the copy gets no row (as on master), never one of its text alone or with the
        // choice's data, and the clipboard keeps the choice.
        if ([mode isEqualToString:@"late-image-both"] || [mode isEqualToString:@"late-image-queue-only"] ||
            [mode isEqualToString:@"late-rich-both"] || [mode isEqualToString:@"late-rich-queue-only"] ||
            [mode isEqualToString:@"late-image-own-write"]) {
            NSArray *before = Contents(historyStore);
            BOOL rich = [mode hasPrefix:@"late-rich-"];
            BOOL ownWrite = [mode isEqualToString:@"late-image-own-write"];
            if (ownWrite) {
                CopyImage(PNG(3));                              // an image Flycut holds, below the newest row ...
                Copy(@"over-the-image");
                before = Contents(historyStore);
            }
            timedQueueOnly = [mode hasSuffix:@"-queue-only"];
            FCTimedData([NSSet setWithObjects:NSPasteboardTypeRTF, NSPasteboardTypeHTML, NSPasteboardTypePNG,
                                              NSPasteboardTypeTIFF, @"com.compuserve.gif", nil], 2.0);
            NSString *want = @"<image>";
            if (rich) {
                [pasteboard copyText:@"rich-just-before"];
                [pasteboard setData:[@"{\\rtf1 rich}" dataUsingEncoding:NSUTF8StringEncoding] forType:NSPasteboardTypeRTF];
                want = @"rich-just-before";
            } else
                [pasteboard copyData:PNG(4) ofType:NSPasteboardTypePNG];
            [controller hitMainHotKey:nil];
            Observe(@"1-bezel-open");
            BOOL inAtOpen = [Contents(historyStore) count] != [before count];
            int mainReadsAtOpen = timedMainThreadReads;     // the choice's own paste may read the clipboard there
            if (ownWrite) Down();                               // ... is the one the user pastes: the read answers with it
            NSString *chosen = Selected();
            Key(@"\r", 36, 0);                      // the user pastes the newest row the bezel shows
            Spin(0.1);
            [controller pollPB:nil];
            [controller drainCaptures];
            Spin(0.3);
            [controller drainCaptures];
            Observe(@"2-after-paste");
            NSArray *after = Contents(historyStore);
            report[@"0-late"] = @{@"inAtOpen": @(inAtOpen), @"chosen": chosen, @"count": @([after count]),
                                 @"before": @([before count]), @"mainReadsAtOpen": @(mainReadsAtOpen),
                                 @"queueReads": @(timedQueueReads)};
            if (mainReadsAtOpen != 0) return Emit(171);         // rich text or image data read on the main thread
            if (inAtOpen) return Emit(173);                     // never a row of a formatted copy's text alone
            if (![after isEqualToArray:before]) return Emit(172);   // a row from a read that spanned the choice
            (void)want;
            // The clipboard holds the choice.
            if (!ownWrite && (![[pasteboard stringForType:NSPasteboardTypeString] isEqualToString:chosen] ||
                [pasteboard availableTypeFromArray:@[NSPasteboardTypePNG, NSPasteboardTypeRTF]] != nil)) return Emit(177);
            return Emit(0);
        }
        // Capture is paused, or image capture turned off, while a slow read of the copy runs; the
        // user closes the bezel, so the clipboard still holds the copy when the read ends: no row.
        if ([mode isEqualToString:@"late-image-paused"] || [mode isEqualToString:@"late-image-capture-off"] ||
            [mode isEqualToString:@"late-rich-paused"]) {
            NSArray *before = Contents(historyStore);
            BOOL rich = [mode hasPrefix:@"late-rich-"];
            BOOL imagesOff = [mode isEqualToString:@"late-image-capture-off"];
            timedQueueOnly = rich;
            FCTimedData([NSSet setWithObjects:NSPasteboardTypeRTF, NSPasteboardTypeHTML, NSPasteboardTypePNG,
                                              NSPasteboardTypeTIFF, @"com.compuserve.gif", nil], 2.0);
            if (rich) {
                [pasteboard copyText:@"rich-just-before"];
                [pasteboard setData:[@"{\\rtf1 rich}" dataUsingEncoding:NSUTF8StringEncoding] forType:NSPasteboardTypeRTF];
            } else
                [pasteboard copyData:PNG(4) ofType:NSPasteboardTypePNG];
            [controller hitMainHotKey:nil];
            Escape();
            if (imagesOff) [[NSUserDefaults standardUserDefaults] setBool:NO forKey:@"captureImages"];
            else [op setDisableStoreTo:YES];                     // capture paused before the read ends
            Spin(0.1);
            [controller drainCaptures];
            Spin(0.3);
            [controller drainCaptures];
            Observe(@"2-after-read");
            if (![Contents(historyStore) isEqualToArray:before]) return Emit(172);
            return Emit(0);
        }
        if ([mode isEqualToString:@"rich-equal-newest-late"]) {
            // A formatted copy whose text the newest row holds already (with formatting from an
            // earlier, identical copy); the user closes the bezel before the slow read ends. The
            // row keeps its formatting until the copy's own arrives, and then has the copy's.
            FCTimedData([NSSet setWithObjects:NSPasteboardTypeRTF, NSPasteboardTypeHTML, nil], 0.0);
            [pasteboard copyText:@"same-rich"];
            [pasteboard setData:[@"{\\rtf1 old}" dataUsingEncoding:NSUTF8StringEncoding] forType:NSPasteboardTypeRTF];
            [controller pollPB:nil]; [controller drainCaptures];
            if (![[Contents(historyStore) firstObject] isEqualToString:@"same-rich"] || RichRTF(0) == nil) return Emit(251);
            NSUInteger count = [Contents(historyStore) count];
            FCTimedData([NSSet setWithObjects:NSPasteboardTypeRTF, NSPasteboardTypeHTML, nil], 2.0);
            timedQueueOnly = YES;
            [pasteboard copyText:@"same-rich"];
            [pasteboard setData:[@"{\\rtf1 new}" dataUsingEncoding:NSUTF8StringEncoding] forType:NSPasteboardTypeRTF];
            [controller hitMainHotKey:nil];
            Observe(@"1-bezel-open");
            if (![RichRTF(0) isEqual:[@"{\\rtf1 old}" dataUsingEncoding:NSUTF8StringEncoding]]) return Emit(252);   // touched before its data came
            Escape();                               // the clipboard still holds the copy when the read ends
            Spin(0.1);
            [controller pollPB:nil];
            [controller drainCaptures];
            Spin(0.3);
            [controller drainCaptures];
            Observe(@"2-after-read");
            if ([Contents(historyStore) count] != count) return Emit(253);           // a second row for the same text
            if (![RichRTF(0) isEqual:[@"{\\rtf1 new}" dataUsingEncoding:NSUTF8StringEncoding]] || SavedRichRTF(0) == nil)
                return Emit(254);                   // the row lost its formatting, or did not get the copy's
            return Emit(0);
        }
        if ([mode isEqualToString:@"late-image-below-newer"] || [mode isEqualToString:@"late-rich-below-newer"] ||
            [mode isEqualToString:@"late-rich-repeated"]) {
            // A copy's slow catch-up read ends while the main thread is still busy, so its commit
            // waits; the user copies again and opens the bezel again: the newer copy is caught up at
            // once. When the older copy's commit runs, its row goes in below the newer one, never
            // above; a newer copy of the same text stands for it.
            NSArray *before = Contents(historyStore);
            BOOL image = [mode isEqualToString:@"late-image-below-newer"];
            BOOL repeated = [mode isEqualToString:@"late-rich-repeated"];
            FCTimedData([NSSet setWithObjects:NSPasteboardTypeRTF, NSPasteboardTypeHTML, NSPasteboardTypePNG,
                                              NSPasteboardTypeTIFF, @"com.compuserve.gif", nil], 0.5);
            timedQueueOnly = YES;
            NSString *older = image ? @"<image>" : @"rich-just-before";
            if (image)
                [pasteboard copyData:PNG(4) ofType:NSPasteboardTypePNG];
            else {
                [pasteboard copyText:@"rich-just-before"];
                [pasteboard setData:[@"{\\rtf1 rich}" dataUsingEncoding:NSUTF8StringEncoding] forType:NSPasteboardTypeRTF];
            }
            [controller hitMainHotKey:nil];          // catch-up: the slow read starts
            Escape();
            [controller waitForReadsLeavingCommitsQueued];   // it ends, the copy still on the clipboard
            NSString *newer = repeated ? @"rich-just-before" : @"newer-text";
            [pasteboard copyText:newer];              // the user copies again (plain text) ...
            [controller hitMainHotKey:nil];          // ... and opens the bezel again: caught up at once
            Observe(@"1-second-open");
            if (![[Contents(historyStore) firstObject] isEqualToString:newer]) return Emit(261);
            Escape();
            Spin(0.1);
            [controller drainCaptures];
            Spin(0.3);
            [controller drainCaptures];
            Observe(@"2-after-read");
            NSArray *after = Contents(historyStore);
            if (![[after firstObject] isEqualToString:newer]) return Emit(262);   // an older copy above the newest
            if (repeated) {
                // The newer copy of the same text stands for it: no second row, and the newer
                // (plain) copy's row keeps what it has.
                if ([after count] != [before count] + 1 || RichRTF(0) != nil) return Emit(263);
                return Emit(0);
            }
            if ([after count] != [before count] + 2 || ![[after objectAtIndex:1] isEqualToString:older]) return Emit(264);
            if (!image && RichRTF(1) == nil) return Emit(265);   // the older row came without its formatting
            if (![[pasteboard stringForType:NSPasteboardTypeString] isEqualToString:newer]) return Emit(266);
            // "Paste as plain text" puts back as decided only what Flycut decided on: the older
            // copy's late commit leaves the newer copy decided.
            Ivar decided = class_getInstanceVariable([AppController class], "pbDecidedGeneration");
            if (*(NSInteger *)((char *)controller + ivar_getOffset(decided)) != [pasteboard changeCount]) return Emit(267);
            return Emit(0);
        }
        if ([mode isEqualToString:@"late-rich-unread"]) {
            // The read queue is still busy with an earlier slow read when a formatted copy is
            // caught up, and the user pastes before the queue gets to it: its formatting can no
            // longer be read (the clipboard holds the choice), so it gets no row, neither one of
            // its text alone nor one with the formatting of what the clipboard holds now.
            FCTimedData([NSSet setWithObjects:NSPasteboardTypeRTF, NSPasteboardTypeHTML, NSPasteboardTypePNG, nil], 0.0);
            [pasteboard copyText:@"chosen-rich"];
            [pasteboard setData:[@"{\\rtf1 chosen}" dataUsingEncoding:NSUTF8StringEncoding] forType:NSPasteboardTypeRTF];
            [controller pollPB:nil]; [controller drainCaptures];
            NSArray *before = Contents(historyStore);
            if (![[before firstObject] isEqualToString:@"chosen-rich"]) return Emit(271);
            FCTimedData([NSSet setWithObjects:NSPasteboardTypeRTF, NSPasteboardTypeHTML, NSPasteboardTypePNG, nil], 2.0);
            timedQueueOnly = YES;
            [pasteboard copyData:PNG(4) ofType:NSPasteboardTypePNG];
            [controller pollPB:nil];                 // the poll's slow image read holds the queue
            [pasteboard copyText:@"rich-unread"];
            [pasteboard setData:[@"{\\rtf1 unread}" dataUsingEncoding:NSUTF8StringEncoding] forType:NSPasteboardTypeRTF];
            [controller hitMainHotKey:nil];
            Key(@"\r", 36, 0);                      // the user pastes the newest row ("chosen-rich")
            Spin(0.1);
            [controller drainCaptures];
            Spin(0.3);
            [controller drainCaptures];
            [controller pollPB:nil];
            [controller drainCaptures];
            Observe(@"2-after-read");
            NSArray *after = Contents(historyStore);
            if ([after containsObject:@"rich-unread"]) return Emit(272);   // a row without the copy's own formatting
            if (![after isEqualToArray:before]) return Emit(273);
            for (int i = 1; i < [historyStore jcListCount]; i++)
                if (RichRTF(i) != nil) return Emit(274);   // another row took formatting
            return Emit(0);
        }
        if ([mode isEqualToString:@"rich-read-spans-choice"]) {
            // A copy with RTF and HTML whose HTML takes long; the user pastes a formatted row while
            // the HTML is read, after its RTF was. Nothing read for the copy is kept: no row with the
            // copy's RTF, and none with the HTML the read answers with (the choice's).
            NSData *chosenHTML = [@"<b>chosen</b>" dataUsingEncoding:NSUTF8StringEncoding];
            FCTimedData([NSSet setWithObjects:NSPasteboardTypeRTF, NSPasteboardTypeHTML, nil], 0.0);
            [pasteboard copyText:@"chosen-rich"];
            [pasteboard setData:[@"{\\rtf1 chosen}" dataUsingEncoding:NSUTF8StringEncoding] forType:NSPasteboardTypeRTF];
            [pasteboard setData:chosenHTML forType:NSPasteboardTypeHTML];
            [controller pollPB:nil]; [controller drainCaptures];
            NSArray *before = Contents(historyStore);
            if (![[before firstObject] isEqualToString:@"chosen-rich"]) return Emit(184);
            FCTimedData([NSSet setWithObjects:NSPasteboardTypeHTML, nil], 2.0);
            timedQueueOnly = YES;
            [pasteboard copyText:@"rich-both"];
            [pasteboard setData:[@"{\\rtf1 both}" dataUsingEncoding:NSUTF8StringEncoding] forType:NSPasteboardTypeRTF];
            [pasteboard setData:[@"<b>both</b>" dataUsingEncoding:NSUTF8StringEncoding] forType:NSPasteboardTypeHTML];
            [controller hitMainHotKey:nil];         // the RTF is read in time, the HTML read goes on
            Key(@"\r", 36, 0);                      // the user pastes "chosen-rich" during the HTML read
            Spin(0.1);
            [controller drainCaptures];
            Spin(0.3);
            [controller drainCaptures];
            Observe(@"2-after-read");
            NSArray *after = Contents(historyStore);
            if ([after containsObject:@"rich-both"]) return Emit(185);   // a row from a read that spanned the choice
            if (![after isEqualToArray:before]) return Emit(186);
            if (![[[[historyStore clippingAtPosition:0] richData] objectForKey:NSPasteboardTypeHTML] isEqual:chosenHTML])
                return Emit(187);                   // the chosen row's formatting changed
            return Emit(0);
        }
        // An independent review's probes, with the provider's answer a real pasteboard gives.
        if ([mode isEqualToString:@"choice-rich-real"]) {
            // The user pastes a formatted row while a formatted copy's read runs; the read answers
            // with the choice's RTF. The copy gets no row, never its text with the choice's formatting.
            NSData *own = [@"{\\rtf1 own}" dataUsingEncoding:NSUTF8StringEncoding];
            NSData *chosenRTF = [@"{\\rtf1 chosen}" dataUsingEncoding:NSUTF8StringEncoding];
            NSSet *slowTypes = [NSSet setWithObjects:NSPasteboardTypeRTF, NSPasteboardTypeHTML, NSPasteboardTypePNG,
                                                     NSPasteboardTypeTIFF, @"com.compuserve.gif", nil];
            FCTimedData(slowTypes, 0.0);
            [pasteboard copyText:@"chosen-row"];
            [pasteboard setData:chosenRTF forType:NSPasteboardTypeRTF];
            [controller pollPB:nil]; [controller drainCaptures];
            if (![[Contents(historyStore) firstObject] isEqualToString:@"chosen-row"] || RichRTF(0) == nil) return Emit(191);
            NSArray *before = Contents(historyStore);
            FCTimedData(slowTypes, 2.0);
            timedQueueOnly = YES;
            [pasteboard copyText:@"rich-copy"];
            [pasteboard setData:own forType:NSPasteboardTypeRTF];
            [controller hitMainHotKey:nil];
            NSString *chosen = Selected();
            Key(@"\r", 36, 0);                      // the user pastes the newest row, "chosen-row"
            Spin(0.1); [controller drainCaptures]; Spin(0.3); [controller drainCaptures];
            NSArray *after = Contents(historyStore);
            NSUInteger idx = [after indexOfObject:@"rich-copy"];
            NSData *rtf = idx == NSNotFound ? nil : RichRTF((int)idx);
            printf("REPORT choice-rich-real chosen=%s row=%d rtf=%s\n", [chosen UTF8String], idx != NSNotFound,
                   rtf == nil ? "none" : [rtf isEqual:own] ? "own" : [rtf isEqual:chosenRTF] ? "CHOICE" : "other");
            if (idx != NSNotFound) return Emit([rtf isEqual:chosenRTF] ? 192 : 193);   // the choice's formatting, or a partial row
            if (![after isEqualToArray:before]) return Emit(194);
            if (![RichRTF(0) isEqual:chosenRTF]) return Emit(195);   // the chosen row's formatting changed
            if (![[pasteboard stringForType:NSPasteboardTypeString] isEqualToString:chosen]) return Emit(196);
            return Emit(0);
        }
        if ([mode isEqualToString:@"choice-image-real"]) {
            // An image copy's read runs when the user pastes a text row; the read answers with
            // nothing. The image gets no row, as on master, and the clipboard keeps the choice.
            FCTimedData([NSSet setWithObjects:NSPasteboardTypeRTF, NSPasteboardTypeHTML, NSPasteboardTypePNG,
                                              NSPasteboardTypeTIFF, @"com.compuserve.gif", nil], 2.0);
            timedQueueOnly = YES;
            NSArray *before = Contents(historyStore);
            [pasteboard copyData:PNG(4) ofType:NSPasteboardTypePNG];
            [controller hitMainHotKey:nil];
            NSString *chosen = Selected();
            Key(@"\r", 36, 0);
            Spin(0.1); [controller drainCaptures]; Spin(0.3); [controller drainCaptures];
            if (![Contents(historyStore) isEqualToArray:before]) return Emit(197);
            if (![[pasteboard stringForType:NSPasteboardTypeString] isEqualToString:chosen]) return Emit(198);
            return Emit(0);
        }
        if ([mode isEqualToString:@"poll-read-spans"]) {
            // A poll's read on the queue spans another application's newer copy: the older copy gets
            // no row (its formatting would be the newer copy's or none), the newer one comes with the
            // next poll.
            NSArray *before = Contents(historyStore);
            FCTimedData([NSSet setWithObjects:NSPasteboardTypeRTF, NSPasteboardTypeHTML, nil], 0.5);
            timedQueueOnly = YES;
            [pasteboard copyText:@"poll-older"];
            [pasteboard setData:[@"{\\rtf1 older}" dataUsingEncoding:NSUTF8StringEncoding] forType:NSPasteboardTypeRTF];
            [controller pollPB:nil];                // the read starts on the queue
            [pasteboard copyText:@"poll-newer"];    // another application copies while it runs
            [controller drainCaptures];
            NSArray *mid = Contents(historyStore);
            [controller pollPB:nil];
            [controller drainCaptures];
            NSArray *after = Contents(historyStore);
            if (![mid isEqualToArray:before]) return Emit(181);
            if (![after isEqualToArray:[@[@"poll-newer"] arrayByAddingObjectsFromArray:before]]) return Emit(182);
            return Emit(0);
        }
        if ([mode isEqualToString:@"poll-plain-read-spans"]) {
            // A poll's read of a plain-text copy on the queue spans another application's newer
            // copy: the older copy gets no row, the newer one comes with the next poll, and the
            // line is logged once.
            NSArray *before = Contents(historyStore);
            FCTimedData([NSSet setWithObjects:NSPasteboardTypeString, nil], 0.5);
            timedQueueOnly = YES;
            [pasteboard copyText:@"poll-plain-older"];
            [controller pollPB:nil];                // the text read starts on the queue
            [pasteboard copyText:@"poll-plain-newer"];   // another application copies while it runs
            [controller drainCaptures];
            NSArray *mid = Contents(historyStore);
            [controller pollPB:nil];
            [controller drainCaptures];
            NSArray *after = Contents(historyStore);
            if (![mid isEqualToArray:before]) return Emit(283);
            if (![after isEqualToArray:[@[@"poll-plain-newer"] arrayByAddingObjectsFromArray:before]]) return Emit(284);
            return Emit(0);
        }
        if ([mode isEqualToString:@"gif-lookup-spans-choice"]) {
            // The user pastes a formatted row whose HTML shows a GIF while a catch-up looks for an
            // image copy's GIF address on the queue; the read answers with the choice's HTML. The
            // copy gets no row, no download starts (not even of the choice's GIF), the clipboard
            // keeps the choice, and the line is logged once.
            [[NSUserDefaults standardUserDefaults] setBool:YES forKey:@"downloadAnimatedGIFs"];
            NSSet *slowTypes = [NSSet setWithObjects:NSPasteboardTypeHTML, nil];
            FCTimedData(slowTypes, 0.0);
            [pasteboard copyText:@"chosen-gif-row"];
            [pasteboard setData:[@"<img src=\"https://example.test/chosen.gif\">" dataUsingEncoding:NSUTF8StringEncoding]
                        forType:NSPasteboardTypeHTML];
            [controller pollPB:nil]; [controller drainCaptures];
            if (![[Contents(historyStore) firstObject] isEqualToString:@"chosen-gif-row"]) return Emit(285);
            NSArray *before = Contents(historyStore);
            FCTimedData(slowTypes, 2.0);
            timedQueueOnly = YES;
            [pasteboard copyData:PNG(4) ofType:NSPasteboardTypePNG];
            [pasteboard setData:[@"<img src=\"https://example.test/anim.gif\">" dataUsingEncoding:NSUTF8StringEncoding]
                        forType:NSPasteboardTypeHTML];
            [controller hitMainHotKey:nil];         // the catch-up looks for the GIF's address on the queue
            NSString *chosen = Selected();
            Key(@"\r", 36, 0);                      // the user pastes the newest row, "chosen-gif-row"
            Spin(0.1); [controller drainCaptures]; Spin(0.3); [controller drainCaptures];
            report[@"gif-spans-choice"] = @{@"downloads": @(gifDownloads), @"url": gifDownloadURL ?: @"-"};
            if (gifDownloads != 0) return Emit(286);   // a download started for a read that spanned the choice
            if (![Contents(historyStore) isEqualToArray:before]) return Emit(287);
            if (![[pasteboard stringForType:NSPasteboardTypeString] isEqualToString:chosen]) return Emit(288);
            return Emit(0);
        }
        // An independent reviewer's probe: one copy with text and an image gives two rows of one
        // clipboard generation; the image, committed after the text, goes in on top, as on master.
        if ([mode isEqualToString:@"text-and-image-one-copy"]) {
            FCTimedData([NSSet setWithObjects:NSPasteboardTypeRTF, nil], 0.0);
            Copy(@"seed-1");
            [pasteboard copyText:@"caption-of-image"];
            [pasteboard setData:PNG(7) forType:NSPasteboardTypePNG];
            [controller pollPB:nil];
            Spin(0.2); [controller drainCaptures]; Spin(0.2); [controller drainCaptures];
            NSArray *after = Contents(historyStore);
            report[@"order"] = @{@"after": [after componentsJoinedByString:@"|"]};
            if ([after count] < 3) return Emit(572);
            if (![[after firstObject] isEqualToString:@"<image>"]) return Emit(571);
            return Emit(0);
        }
        if ([mode isEqualToString:@"poll-image-below-newer"]) {
            // A poll's image read ends with the copy still on the clipboard, but its commit waits for
            // the main thread while another application copies: the image goes in all the same, as a
            // formatted copy's row does, below the newer copy.
            NSArray *before = Contents(historyStore);
            FCTimedData([NSSet setWithObjects:NSPasteboardTypePNG, NSPasteboardTypeTIFF, nil], 0.5);
            timedQueueOnly = YES;
            [pasteboard copyData:PNG(5) ofType:NSPasteboardTypePNG];
            [controller pollPB:nil];                // the read starts on the queue
            [controller waitForReadsLeavingCommitsQueued];   // it ends, the copy still on the clipboard
            [pasteboard copyText:@"poll-image-newer"];   // another application copies before the commit
            [controller pollPB:nil];
            Spin(0.1); [controller drainCaptures]; Spin(0.3); [controller drainCaptures];
            NSArray *after = Contents(historyStore);
            if ([after count] != [before count] + 2 || ![[after firstObject] isEqualToString:@"poll-image-newer"]) return Emit(226);
            if (![[after objectAtIndex:1] isEqualToString:@"<image>"]) return Emit(227);
            return Emit(0);
        }
        if ([mode isEqualToString:@"late-rich-diagnostics"]) {
            // Diagnostics go on while a formatted copy's late read runs: no content row.
            FCTimedData([NSSet setWithObjects:NSPasteboardTypeRTF, NSPasteboardTypeHTML, nil], 2.0);
            timedQueueOnly = YES;
            [pasteboard copyText:@"rich-diag"];
            [pasteboard setData:[@"{\\rtf1 own}" dataUsingEncoding:NSUTF8StringEncoding] forType:NSPasteboardTypeRTF];
            [controller hitMainHotKey:nil];
            Escape();
            [[NSUserDefaults standardUserDefaults] setBool:YES forKey:@"revealPasteboardTypes"];
            Spin(0.1); [controller drainCaptures]; Spin(0.3); [controller drainCaptures];
            if ([Contents(historyStore) containsObject:@"rich-diag"]) return Emit(188);
            return Emit(0);
        }
        if ([mode isEqualToString:@"late-rich-favorites"]) {
            // The bezel shows the favorites when a formatted copy's late read ends: the row goes into
            // the history, complete, and the favorites stay as they are.
            FCTimedData([NSSet setWithObjects:NSPasteboardTypeRTF, NSPasteboardTypeHTML, nil], 0.0);
            Copy(@"newer-plain-0");
            FCTimedData([NSSet setWithObjects:NSPasteboardTypeRTF, NSPasteboardTypeHTML, nil], 2.0);
            timedQueueOnly = YES;
            NSArray *favBefore = Contents(favoritesStore);
            [pasteboard copyText:@"rich-fav"];
            [pasteboard setData:[@"{\\rtf1 own}" dataUsingEncoding:NSUTF8StringEncoding] forType:NSPasteboardTypeRTF];
            [controller hitMainHotKey:nil];
            ToggleFavorites();                      // the bezel shows the favorites
            Spin(0.1); [controller drainCaptures]; Spin(0.3); [controller drainCaptures];
            NSArray *favAfter = Contents(favoritesStore);
            Escape();
            NSArray *after = Contents(historyStore);
            if (![[after firstObject] isEqualToString:@"rich-fav"] || RichRTF(0) == nil || ![favAfter isEqualToArray:favBefore])
                return Emit(189);
            return Emit(0);
        }
        // A read that ends with the copy still on the clipboard while the main thread is busy: its
        // commit waits, and the user's next copies and choices come first. The late row goes in
        // below every row of a newer copy.
        if ([mode isEqualToString:@"late-below-recopied-newest"] || [mode isEqualToString:@"late-below-recopied-image"] ||
            [mode isEqualToString:@"late-below-two-newer"]) {
            BOOL image = [mode isEqualToString:@"late-below-recopied-image"];
            BOOL two = [mode isEqualToString:@"late-below-two-newer"];
            NSSet *slow = [NSSet setWithObjects:NSPasteboardTypeRTF, NSPasteboardTypeHTML, nil];   // images come at once
            FCTimedData(slow, 0.0);
            if (image) CopyImage(PNG(5));                   // the newest row: an image
            NSString *top = [Contents(historyStore) firstObject];
            FCTimedData(slow, 0.5);
            timedQueueOnly = YES;
            [pasteboard copyText:@"rich-late"];
            [pasteboard setData:[@"{\\rtf1 late}" dataUsingEncoding:NSUTF8StringEncoding] forType:NSPasteboardTypeRTF];
            [controller hitMainHotKey:nil];
            Escape();
            [controller waitForReadsLeavingCommitsQueued];
            NSArray *want = nil;
            if (two) {
                [pasteboard copyText:@"newer-1"]; [controller hitMainHotKey:nil]; Escape();
                [pasteboard copyText:@"newer-2"]; [controller hitMainHotKey:nil]; Escape();
                want = @[@"newer-2", @"newer-1", @"rich-late"];
            } else {
                // The newest row copied again: no row, but it is the newest copy now.
                if (image) [pasteboard copyData:PNG(5) ofType:NSPasteboardTypePNG];
                else [pasteboard copyText:top];
                [controller hitMainHotKey:nil];         // an image is read within the wait and committed there
                Escape();
                want = @[top, @"rich-late"];
            }
            NSUInteger count = [Contents(historyStore) count];
            Spin(0.1); [controller drainCaptures]; Spin(0.3); [controller drainCaptures];
            NSArray *after = Contents(historyStore);
            printf("REPORT %s top=%s after=%s\n", [mode UTF8String], [top UTF8String],
                   [[[after subarrayWithRange:NSMakeRange(0, MIN((NSUInteger)3, [after count]))] componentsJoinedByString:@"|"] UTF8String]);
            if ([after count] != count + 1) return Emit(205);
            if (![[after subarrayWithRange:NSMakeRange(0, [want count])] isEqualToArray:want]) return Emit(206);   // above a newer copy
            if (RichRTF((int)[want count] - 1) == nil) return Emit(207);
            return Emit(0);
        }
        if ([mode isEqualToString:@"dup-pasted-stays-on-top"]) {
            // "Remove duplicates" and "Move pasted item to top" on. A formatted copy of a row's text
            // ends its read with the copy still on the clipboard, but its commit waits; the user
            // copies again and pastes the older equal row to the top. The late row's place is below
            // the newer copy, and the insert would take the equal row off the top: that row stands
            // for the copy and stays where the paste put it.
            NSUserDefaults *d = [NSUserDefaults standardUserDefaults];
            [d setBool:YES forKey:@"removeDuplicates"];
            [d setBool:YES forKey:@"pasteMovesToTop"];
            NSSet *slow = [NSSet setWithObjects:NSPasteboardTypeRTF, NSPasteboardTypeHTML, nil];
            FCTimedData(slow, 0.0);
            Copy(@"c-row"); Copy(@"alpha");
            FCTimedData(slow, 0.5);
            timedQueueOnly = YES;
            [pasteboard copyText:@"alpha"];
            [pasteboard setData:[@"{\\rtf1 own}" dataUsingEncoding:NSUTF8StringEncoding] forType:NSPasteboardTypeRTF];
            [controller hitMainHotKey:nil];         // catch-up: the slow read starts
            Escape();
            [controller waitForReadsLeavingCommitsQueued];
            [pasteboard copyText:@"b-newer"];
            [controller hitMainHotKey:nil];         // plain text: in at once, on top
            Down();
            NSString *chosen = Selected();          // "alpha", the older equal row
            Key(@"\r", 36, 0);                      // pasted and moved to the top
            NSArray *beforeLate = Contents(historyStore);
            Spin(0.1); [controller drainCaptures]; Spin(0.3); [controller drainCaptures];
            NSArray *after = Contents(historyStore);
            printf("REPORT dup-pasted-stays-on-top chosen=%s beforeLate=%s after=%s\n", [chosen UTF8String],
                   [[[beforeLate subarrayWithRange:NSMakeRange(0, 3)] componentsJoinedByString:@"|"] UTF8String],
                   [[[after subarrayWithRange:NSMakeRange(0, MIN((NSUInteger)3, [after count]))] componentsJoinedByString:@"|"] UTF8String]);
            if (![chosen isEqualToString:@"alpha"] ||
                ![[beforeLate subarrayWithRange:NSMakeRange(0, 3)] isEqualToArray:(@[@"alpha", @"b-newer", @"c-row"])]) return Emit(208);
            if (![after isEqualToArray:beforeLate]) return Emit(209);   // the pasted row left the top, or the row went in below an older one
            return Emit(0);
        }
        if ([mode isEqualToString:@"forget-deleted-rows"]) {
            // FlycutOperator remembers the latest copies' rows for late rows, only while they are in
            // the history: a delete (list or search, bezel) or a cleared history lets them go.
            Copy(@"forget-a"); Copy(@"forget-b"); Copy(@"forget-c");
            Ivar ivar = class_getInstanceVariable([FlycutOperator class], "recentClipboardRows");
            if (ivar == NULL) return Emit(214);
            NSArray *(^Remembered)(void) = ^NSArray *{
                NSMutableArray *out = [NSMutableArray array];
                for (NSArray *entry in (NSArray *)object_getIvar(op, ivar)) [out addObject:[entry objectAtIndex:0]];
                return out;
            };
            FlycutClipping *c = [[historyStore clippingAtPosition:0] retain];
            FlycutClipping *b = [[historyStore clippingAtPosition:1] retain];
            if (![[b contents] isEqualToString:@"forget-b"] || [Remembered() indexOfObjectIdenticalTo:b] == NSNotFound ||
                [Remembered() indexOfObjectIdenticalTo:c] == NSNotFound) return Emit(213);
            [op deleteClipping:b fromList:FlycutListHistory];
            if ([Remembered() indexOfObjectIdenticalTo:b] != NSNotFound) return Emit(215);   // a deleted row is kept
            [op setStackPositionTo:0];
            [op clearItemAtStackPosition];          // the bezel's delete of the newest row
            if ([Remembered() indexOfObjectIdenticalTo:c] != NSNotFound) return Emit(216);
            if ([Remembered() count] == 0) return Emit(218);   // rows still in the history are kept
            [op clearList];
            if ([Remembered() count] != 0) return Emit(217);   // a cleared history keeps its rows in memory
            [b release]; [c release];
            return Emit(0);
        }
        if ([mode hasPrefix:@"copy-just-before-"] || [mode isEqualToString:@"no-new-copy"]) {
            NSArray *before = Contents(historyStore);
            // The poll runs once a second: this copy was not polled when the selection opens.
            if (![mode isEqualToString:@"no-new-copy"]) [pasteboard copyText:@"copied-just-before"];
            if ([mode isEqualToString:@"copy-just-before-bezel"] || [mode isEqualToString:@"no-new-copy"]) {
                [controller hitMainHotKey:nil];
                Observe(@"1-bezel-open");
                if ([mode isEqualToString:@"no-new-copy"]) {
                    // Nothing new on the clipboard: nothing is added, the newest row is selected.
                    if (![Contents(historyStore) isEqualToArray:before]) return Emit(221);
                    if (![Selected() isEqualToString:[before firstObject]]) return Emit(222);
                    Escape();
                    return Emit(0);
                }
                if (![Contents(historyStore) isEqualToArray:[@[@"copied-just-before"] arrayByAddingObjectsFromArray:before]])
                    return Emit(201);
                if (![Selected() isEqualToString:@"copied-just-before"]) return Emit(202);
                Down();                                 // the user picks the older clipping ...
                Key(@"\r", 36, 0);                      // ... and pastes it with Return
                Spin(0.1);
                [controller pollPB:nil];
                [controller drainCaptures];
                Observe(@"2-after-paste");
                if (![Contents(historyStore) containsObject:@"copied-just-before"]) return Emit(203);
                if ([Contents(historyStore) count] != [before count] + 1) return Emit(204);
                return Emit(0);
            }
            if ([mode isEqualToString:@"copy-just-before-list"]) {
                [controller listControllerDidOpen:nil];
                Observe(@"1-list-open");
                if (![[Contents(historyStore) firstObject] isEqualToString:@"copied-just-before"]) return Emit(211);
                [controller listControllerDidClose:nil];
                [controller drainCaptures];
                Observe(@"2-list-closed");
                if ([Contents(historyStore) count] != [before count] + 1) return Emit(212);
                return Emit(0);
            }
            return Emit(299);
        }
"""
TIMED_DATA = r"""
// A stand-in for a slow provider: data of the listed types takes timedSeconds to arrive. When the
// clipboard changes while it waits, it answers as a real NSPasteboard does (measured with a lazy
// provider in another process on a uniquely named pasteboard): with the data the reading process
// wrote itself for that type (Flycut's write for a choice: its RTF, or nothing without one), and
// with nothing after another application's newer copy; never with the copy's own data. With
// timedQueueOnly only reads off the main thread are slow. Every data read is counted by thread
// (stringForType: is not a data read). A string read of a listed type waits and answers the same
// way.
static NSSet *timedTypes;
static NSTimeInterval timedSeconds;
static int timedMainThreadReads, timedQueueReads;
static BOOL timedQueueOnly;
static BOOL lastWriteWasFlycuts;   // the clipboard's last change: Flycut's write, or another application's copy
static IMP timedOriginal, declareOriginal, clearOriginal, copyTextOriginal, copyDataOriginal, timedStringOriginal;
static NSData *FCTimedDataForType(id self, SEL _cmd, NSString *type) {
    if ([NSThread isMainThread]) timedMainThreadReads++; else timedQueueReads++;
    BOOL slow = [timedTypes containsObject:type] && timedSeconds > 0 && !(timedQueueOnly && [NSThread isMainThread]);
    NSInteger asked = [self changeCount];
    NSData *data = [[((NSData *(*)(id, SEL, NSString *))timedOriginal)(self, _cmd, type) retain] autorelease];
    if (!slow) return data;
    [NSThread sleepForTimeInterval:timedSeconds];
    if ([self changeCount] == asked) return data;
    return lastWriteWasFlycuts ? ((NSData *(*)(id, SEL, NSString *))timedOriginal)(self, _cmd, type) : nil;
}
static NSString *FCTimedStringForType(id self, SEL _cmd, NSString *type) {
    BOOL slow = [timedTypes containsObject:type] && timedSeconds > 0 && !(timedQueueOnly && [NSThread isMainThread]);
    NSInteger asked = [self changeCount];
    if (slow) [NSThread sleepForTimeInterval:timedSeconds];
    if (!slow || [self changeCount] == asked || lastWriteWasFlycuts)
        return ((NSString *(*)(id, SEL, NSString *))timedStringOriginal)(self, _cmd, type);
    return nil;
}
// Flycut writes with -declareTypes:owner: or -clearContents; other applications' copies are the
// fixture's -copyText: and -copyData:ofType:.
static NSInteger FCFlycutDeclares(id self, SEL _cmd, NSArray *types, id owner) {
    lastWriteWasFlycuts = YES;
    return ((NSInteger (*)(id, SEL, NSArray *, id))declareOriginal)(self, _cmd, types, owner);
}
static NSInteger FCFlycutClears(id self, SEL _cmd) {
    lastWriteWasFlycuts = YES;
    return ((NSInteger (*)(id, SEL))clearOriginal)(self, _cmd);
}
static void FCOtherCopiesText(id self, SEL _cmd, NSString *text) {
    lastWriteWasFlycuts = NO;
    ((void (*)(id, SEL, NSString *))copyTextOriginal)(self, _cmd, text);
}
static void FCOtherCopiesData(id self, SEL _cmd, NSData *data, NSString *type) {
    lastWriteWasFlycuts = NO;
    ((void (*)(id, SEL, NSData *, NSString *))copyDataOriginal)(self, _cmd, data, type);
}
static void FCTimedData(NSSet *types, NSTimeInterval seconds) {
    Class board = [FCMemoryPasteboard class];
    if (timedOriginal == NULL) {
        timedOriginal = method_setImplementation(class_getInstanceMethod(board, @selector(dataForType:)), (IMP)FCTimedDataForType);
        declareOriginal = method_setImplementation(class_getInstanceMethod(board, @selector(declareTypes:owner:)), (IMP)FCFlycutDeclares);
        clearOriginal = method_setImplementation(class_getInstanceMethod(board, @selector(clearContents)), (IMP)FCFlycutClears);
        copyTextOriginal = method_setImplementation(class_getInstanceMethod(board, @selector(copyText:)), (IMP)FCOtherCopiesText);
        copyDataOriginal = method_setImplementation(class_getInstanceMethod(board, @selector(copyData:ofType:)), (IMP)FCOtherCopiesData);
        timedStringOriginal = method_setImplementation(class_getInstanceMethod(board, @selector(stringForType:)), (IMP)FCTimedStringForType);
    }
    timedTypes = [types retain]; timedSeconds = seconds; timedMainThreadReads = timedQueueReads = 0;
}
@interface FCFavController (CopyBeforeSelectionReads)
- (void)waitForReadsLeavingCommitsQueued;
@end
@implementation FCFavController (CopyBeforeSelectionReads)
// Every read queued so far ends while the main thread stays busy, so the commits they hand to the
// main queue wait, as when a read ends while Flycut handles the user's next key.
- (void)waitForReadsLeavingCommitsQueued { dispatch_sync(clipboardReadQueue, ^{}); }
@end
// GIF downloads are a network boundary: counted, never started.
static int gifDownloads;
static BOOL gifDownloadOnMain;
static NSString *gifDownloadURL;
@implementation FCFavController (CopyBeforeSelectionDownloads)
- (void)downloadAndCaptureGIFFromURL:(NSURL *)url fromApp:(NSString *)appName withAppBundleURL:(NSString *)bundleURL
                pasteboardGeneration:(NSInteger)generation {
    (void)appName; (void)bundleURL; (void)generation;
    gifDownloads++; gifDownloadOnMain = [NSThread isMainThread]; gifDownloadURL = [[url absoluteString] copy];
}
@end
"""
RICH = r"""
static NSData *SavedRichRTF(int position) {
    NSArray *saved = [[[NSUserDefaults standardUserDefaults] dictionaryForKey:@"store"] objectForKey:@"jcList"];
    return position < (int)[saved count] ? [[[saved objectAtIndex:position] objectForKey:@"RichData"] objectForKey:NSPasteboardTypeRTF] : nil;
}
static NSData *RichRTF(int position) {
    if (position >= [historyStore jcListCount]) return nil;
    return [[[historyStore clippingAtPosition:position] richData] objectForKey:NSPasteboardTypeRTF];
}
"""
SPANNED_LOG = "Clipboard read: the copy changed while it was read, so it is not taken in"
MODES = {
    "copy-just-before-bezel": "a copy made just before the bezel opened was not its newest row, or was lost to the paste",
    "copy-just-before-list": "a copy made just before the menu-bar list opened was not its newest row",
    "no-new-copy": "opening the bezel with nothing new on the clipboard changed the history",
    "catch-up-rich-fast": "a rich-text copy was read on the main thread, or was not the newest row with its formatting at once",
    "catch-up-rich-slow": "a slow rich-text read held up opening, gave the copy a row of its text alone, or its formatting was lost",
    "catch-up-image-fast": "an image copy was read on the main thread or was not the newest row at once",
    "catch-up-image-slow": "a slow image read held up opening, ran on the main thread or was lost",
    "catch-up-gif-slow": "a GIF copy's HTML was read on the main thread, held up opening, or its download did not start once after the read",
    "late-image-both": "an image copy whose slow read spanned a choice in the bezel added a row, or the clipboard lost the choice",
    "late-image-queue-only": "an image copy whose slow read spanned a choice in the bezel added a row, or the clipboard lost the choice",
    "late-rich-both": "a formatted copy whose slow read spanned a choice in the bezel added a row (its text alone or the choice's data)",
    "late-rich-queue-only": "a formatted copy whose slow read spanned a choice in the bezel added a row (its text alone or the choice's data)",
    "late-rich-paused": "a slow formatted read that ended after capture was paused added its copy",
    "late-image-own-write": "a slow read that returned the image Flycut wrote for a choice added it again",
    "rich-equal-newest-late": "a formatted copy of the newest row's text cleared that row's formatting before its own arrived, or never gave it",
    "equal-top-wipe": "a formatted copy of the newest row's text, chosen before its slow formatting read ended, left that row without formatting",
    "stale-image-on-top": "an image whose slow read ended after a newer copy was caught up landed above it",
    "late-image-below-newer": "an image whose commit ran after a newer copy went in landed above it, or was lost",
    "late-rich-below-newer": "a formatted copy whose commit ran after a newer copy went in landed above it, or lost its formatting",
    "late-rich-repeated": "a formatted copy whose commit ran after a newer copy of the same text went in added a second row",
    "late-rich-unread": "a formatted copy whose formatting could no longer be read got a row of its text alone or another clipping's formatting",
    "rich-read-spans-choice": "a formatted copy kept data read before a later read spanned a choice, or took the choice's HTML",
    "choice-rich-real": "a formatted copy whose read spanned the paste of a formatted row got a row, with the choice's formatting or without its own",
    "choice-image-real": "an image copy whose read spanned a choice added a row, or the clipboard lost the choice",
    "poll-read-spans": "a poll read that spanned another application's newer copy added the older copy, or lost the newer one",
    "poll-plain-read-spans": "a poll's text read that spanned another application's newer copy added the older copy, or lost the newer one",
    "gif-lookup-spans-choice": "a GIF lookup that spanned a choice in the bezel started a download or added a row, or the clipboard lost the choice",
    "text-and-image-one-copy": "the image row of a copy with text and an image went in below its text row",
    "poll-image-below-newer": "a poll's image whose read ended before a newer copy was lost, or landed above it",
    "late-rich-diagnostics": "a late formatted read stored content after Diagnostics went on",
    "late-rich-favorites": "a late formatted read while the bezel shows the favorites missed the history or touched the favorites",
    "late-below-recopied-newest": "a late row went in above a newer copy of the newest row's text",
    "late-below-recopied-image": "a late row went in above a newer copy of the newest row's image",
    "late-below-two-newer": "a late row went in between two newer copies",
    "dup-pasted-stays-on-top": "with Remove duplicates on, a late row took the pasted row off the top or went in below an older row",
    "forget-deleted-rows": "the rows remembered for late reads kept a deleted row or a cleared history",
    "late-image-paused": "a slow image read that ended after capture was paused added its copy",
    "late-image-capture-off": "a slow image read that ended after image capture was turned off added its copy",
}


def fixture() -> str:
    source = base.FIXTURE
    anchor = "        if ((failed = OpenFavoritesView())) return Emit(failed);\n"
    assert source.count(anchor) == 1
    declare = "- (void)hitMainHotKey:(id)hotKey;\n"
    assert source.count(declare) == 1
    source = source.replace(declare, declare + "- (void)listControllerDidOpen:(id)controller;\n"
                            "- (void)listControllerDidClose:(id)controller;\n")
    helpers = "static FCFavController *controller;\n"
    assert source.count(helpers) == 1
    source = source.replace(helpers, TIMED_DATA + helpers)
    contents = "static NSArray *Saved(NSString *key) {\n"
    assert source.count(contents) == 1
    source = source.replace(contents, RICH + contents)
    return source.replace(anchor, CASES + anchor)


def method_body(source: str, signature: str) -> str:
    if signature + "\n{" not in source:
        return ""
    start = source.index(signature + "\n{")
    opening = source.index("{", start)
    depth = 0
    for index in range(opening, len(source)):
        depth += {"{": 1, "}": -1}.get(source[index], 0)
        if depth == 0:
            return source[start:index + 1]
    raise AssertionError(signature)


class CopyBeforeSelectionRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.directory = tempfile.TemporaryDirectory(prefix="flycut-copy-before-selection-")
        temp = pathlib.Path(cls.directory.name)
        source = temp / "CopyBeforeSelectionFixture.m"
        cls.binary = temp / "CopyBeforeSelectionFixture"
        source.write_text(fixture())
        sources = base.fixture_sources()
        command = ["/usr/bin/xcrun", "clang", "-fno-objc-arc", "-fobjc-weak", "-fblocks", "-fmodules",
                   "-DFLYCUT_MAC=1", "-DNSBeep=FCFixtureBeep", "-mmacosx-version-min=13.5", "-arch", "arm64",
                   "-include", str(ROOT / "Flycut_Prefix.pch")]
        for include in sorted({ROOT, base.FIXTURES, *(p.parent for p in sources)}):
            command += ["-I", str(include)]
        command += [str(p) for p in sources] + [str(source)]
        for framework in ("Cocoa", "Carbon", "ServiceManagement", "CloudKit"):
            command += ["-framework", framework]
        command += ["-o", str(cls.binary)]
        cls.build = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=300)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.directory.cleanup()

    def run_mode(self, mode: str, spanned_logs: int | None = None) -> None:
        self.assertEqual(self.build.returncode, 0, self.build.stderr[-4000:])
        run = subprocess.run([str(self.binary), mode], cwd=ROOT, text=True, capture_output=True, timeout=60)
        reports = [line[len("REPORT "):] for line in run.stdout.splitlines() if line.startswith("REPORT ")]
        print(f"\n{mode}: exit={run.returncode} {reports[-1] if reports else '(no report)'}")
        self.assertEqual(run.returncode, 0, f"{MODES[mode]}; exit={run.returncode}; "
                         f"{reports[-1] if reports else run.stderr[-1500:]}")
        if spanned_logs is not None:
            # A read that spans a clipboard change says so once per copy, with a fixed text.
            self.assertEqual(run.stderr.count(SPANNED_LOG), spanned_logs, f"{mode}: log lines")

    def test_a_copy_just_before_the_bezel_opens_is_its_newest_row_and_survives_the_paste(self) -> None:
        self.run_mode("copy-just-before-bezel")

    def test_a_copy_just_before_the_list_opens_is_its_newest_row(self) -> None:
        self.run_mode("copy-just-before-list")

    def test_opening_the_bezel_without_a_new_copy_changes_nothing(self) -> None:
        self.run_mode("no-new-copy")

    def test_the_search_window_takes_a_waiting_copy_in_before_its_results(self) -> None:
        # The search window needs a real window; its order is pinned by source.
        body = method_body(APP_CONTROLLER.read_text(), "- (void)showSearchWindow")
        self.assertIn("[self captureClipboardChangeNow];", body, "the search window does not take a waiting copy in")
        self.assertLess(body.index("[self captureClipboardChangeNow];"), body.index("[self updateSearchResults];"))

    # Rich text and images: read on the read queue, opening waits a bounded time for them.
    def test_a_rich_text_copy_is_read_off_the_main_thread_and_is_the_newest_row_at_once(self) -> None:
        self.run_mode("catch-up-rich-fast")

    def test_a_slow_rich_text_read_does_not_hold_up_opening_and_its_row_goes_in_complete(self) -> None:
        self.run_mode("catch-up-rich-slow", spanned_logs=0)

    def test_an_image_copy_is_read_off_the_main_thread_and_is_the_newest_row_at_once(self) -> None:
        self.run_mode("catch-up-image-fast")

    def test_a_slow_image_read_does_not_hold_up_opening_and_its_copy_still_arrives(self) -> None:
        self.run_mode("catch-up-image-slow")

    def test_a_gif_copy_is_looked_up_off_the_main_thread_and_its_download_starts_once(self) -> None:
        self.run_mode("catch-up-gif-slow")

    # A choice in the bezel while a slow read of the copy runs (both threads slow, or only the queue):
    # the read answers with the choice's data or none, so the copy gets no row.
    def test_an_image_copy_whose_read_spans_a_choice_gets_no_row(self) -> None:
        self.run_mode("late-image-both")

    def test_an_image_copy_whose_queue_read_spans_a_choice_gets_no_row(self) -> None:
        self.run_mode("late-image-queue-only")

    def test_a_formatted_copy_whose_read_spans_a_choice_gets_no_row(self) -> None:
        self.run_mode("late-rich-both")

    def test_a_formatted_copy_whose_queue_read_spans_a_choice_gets_no_row(self) -> None:
        self.run_mode("late-rich-queue-only")

    def test_a_late_read_that_returns_flycuts_own_write_adds_no_row(self) -> None:
        self.run_mode("late-image-own-write")

    def test_a_formatted_copy_never_takes_the_formatting_of_a_choice(self) -> None:
        self.run_mode("choice-rich-real", spanned_logs=1)

    def test_an_image_copy_whose_read_spans_a_choice_is_not_kept(self) -> None:
        self.run_mode("choice-image-real", spanned_logs=1)

    def test_nothing_read_for_a_copy_is_kept_once_a_later_read_spans_a_choice(self) -> None:
        self.run_mode("rich-read-spans-choice", spanned_logs=1)

    def test_a_poll_read_that_spans_a_newer_copy_adds_no_row_and_says_so_once(self) -> None:
        self.run_mode("poll-read-spans", spanned_logs=1)

    def test_a_poll_text_read_that_spans_a_newer_copy_adds_no_row_and_says_so_once(self) -> None:
        self.run_mode("poll-plain-read-spans", spanned_logs=1)

    def test_a_gif_lookup_that_spans_a_choice_starts_no_download_and_says_so_once(self) -> None:
        self.run_mode("gif-lookup-spans-choice", spanned_logs=1)

    def test_a_poll_image_whose_commit_comes_after_a_newer_copy_goes_in_below_it(self) -> None:
        self.run_mode("poll-image-below-newer")

    # A late read with the copy still on the clipboard: pause, image capture and Diagnostics apply.
    def test_a_late_formatted_read_adds_nothing_once_capture_is_paused(self) -> None:
        self.run_mode("late-rich-paused")

    def test_a_late_image_read_adds_nothing_once_capture_is_paused(self) -> None:
        self.run_mode("late-image-paused")

    def test_a_late_image_read_adds_nothing_once_image_capture_is_off(self) -> None:
        self.run_mode("late-image-capture-off")

    def test_a_late_formatted_read_adds_nothing_once_diagnostics_are_on(self) -> None:
        self.run_mode("late-rich-diagnostics")

    def test_a_late_formatted_row_goes_into_the_history_while_the_bezel_shows_favorites(self) -> None:
        self.run_mode("late-rich-favorites")

    # Rows go in complete and in the order of the copies.
    def test_a_formatted_copy_of_the_newest_rows_text_keeps_its_formatting_until_its_own_arrives(self) -> None:
        self.run_mode("rich-equal-newest-late")

    def test_the_image_of_a_copy_with_text_goes_in_above_its_text_row(self) -> None:
        self.run_mode("text-and-image-one-copy", spanned_logs=0)

    def test_equal_top_formatting_survives_a_choice_before_the_late_read(self) -> None:
        self.run_mode("equal-top-wipe")

    def test_a_late_image_does_not_land_above_a_newer_copy(self) -> None:
        self.run_mode("stale-image-on-top")

    def test_a_late_image_goes_in_below_a_newer_copy(self) -> None:
        self.run_mode("late-image-below-newer")

    def test_a_late_formatted_copy_goes_in_below_a_newer_copy_with_its_formatting(self) -> None:
        self.run_mode("late-rich-below-newer")

    def test_a_late_formatted_copy_adds_no_row_when_a_newer_copy_repeats_its_text(self) -> None:
        self.run_mode("late-rich-repeated")

    def test_a_late_row_goes_in_below_a_newer_copy_of_the_newest_rows_text(self) -> None:
        self.run_mode("late-below-recopied-newest")

    def test_a_late_row_goes_in_below_a_newer_copy_of_the_newest_image(self) -> None:
        self.run_mode("late-below-recopied-image")

    def test_a_late_row_goes_in_below_every_newer_copy(self) -> None:
        self.run_mode("late-below-two-newer")

    def test_with_remove_duplicates_a_late_row_leaves_the_pasted_row_on_top(self) -> None:
        self.run_mode("dup-pasted-stays-on-top")

    def test_a_formatted_copy_whose_formatting_can_no_longer_be_read_gets_no_row(self) -> None:
        self.run_mode("late-rich-unread")

    def test_rows_remembered_for_late_reads_go_with_a_delete_or_a_cleared_history(self) -> None:
        self.run_mode("forget-deleted-rows")

if __name__ == "__main__":
    unittest.main()
