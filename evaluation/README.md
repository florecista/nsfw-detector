# Private model evaluation set

The contents of `private/` are intentionally ignored by Git. Put evaluation
images into the matching directory:

- `safe/`
- `swimwear/`
- `artistic-nudity/`
- `explicit-nudity/`
- `drawings/`
- `difficult-false-positives/`

Keep this material local and verify that `git status` does not list any of the
images before committing. Use images you are permitted to possess and process.

For a useful comparison, keep the same evaluation set while testing every model
and record recall, false positives, images per second, peak memory, and cold-load
time. The application's persistent cache should be cleared or bypassed for
performance measurements.
