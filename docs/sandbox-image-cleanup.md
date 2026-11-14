# Sandbox image and container cleanup: instructions for Sonnet

The owner asked for this: every time the capture image is built, delete the previous image. Also delete any outdated containers. Once a newer image exists, nothing should keep an old one alive.

## What the code does today

- `lib/sandbox/runtime.py:16` defines a fixed tag, `IMAGE_TAG = "openmontage-capture:1"`.
  - When the image is rebuilt under that same tag, the previous build loses its name but stays on disk, untagged ("dangling").
  - Nothing ever removes it.
- `tools/capture/sandbox_capture.py:196` (`_build_image`) only runs `build`. It never cleans up.
- Containers are started with `--rm` and named `om-capture-<cid>-<ts>`. `teardown()` stops and removes them in `finally`.
  - If the process is killed partway through (SIGKILL, crash, reboot), stopped or orphaned `om-capture-*` containers can be left behind.
  - Nothing sweeps them up.
- Apple `container` 1.7.1 starts a separate builder VM for `container build`. That VM keeps running after the build finishes.

## What to build

1. **Version the image by content.**
   - Tag it `openmontage-capture:<h>`, where `<h>` is the first 12 hex characters of a sha256 over every file under `sandbox/`.
   - Hash files in sorted path order, covering both path and bytes.
   - Add `--label org.openmontage.role=capture` to the build argv for both runtimes.
   - Replace the `IMAGE_TAG` constant with a `current_image_tag()` helper. Update every caller: `image_exists`, `RunSpec(image=...)`, the error text, and the `build_image` hint at `sandbox_capture.py:110`.
   - If `current_image_tag()` already exists, `build_image` returns success with `"rebuilt": false` and builds nothing.
   - Run cleanup (step 3) in both cases.

2. **Add cleanup methods to `ContainerRuntime`.** Implement them for AppleContainer, Docker and Colima.
   - `list_capture_images() -> list[str]`: every image whose repository is `openmontage-capture`. Use `image list --format json`; don't parse tables.
   - `list_capture_containers(all=True) -> list[dict]`: every container whose name starts with `om-capture-`, with its state and image. Use `list --all --format json`.
   - `remove_image(ref)`: Apple uses `container image delete <ref>`, Docker/Colima use `docker image rm <ref>`.
     - Check the exact Apple subcommand with `container image --help` before relying on it.
   - `prune_dangling_images()`: Apple uses `container image prune`, Docker uses `docker image prune -f`.
     - **Never pass `--all`.** It would delete the owner's other images that have nothing to do with OpenMontage.
   - `stop_builder()`: Apple only, `container builder stop`. A no-op on the others.

3. **Add `cleanup_stale(rt, keep_tag, active_name=None)` in `lib/sandbox/runtime.py`.** It runs in this order:
   1. For each `om-capture-*` container that is not `active_name`, call `teardown(name)`. This covers stopped containers and any still running from a dead process.
      - Before removing a running one, hold the heavy lock (`lib/heavy_lock.py`) or check the capture session state file.
      - Skip any container that belongs to a capture still in progress (`start` without `collect`/`teardown` yet). Never kill a live login-handoff session.
   2. For each `openmontage-capture:*` image whose tag is not `keep_tag`, call `remove_image`. This includes the legacy `openmontage-capture:1`.
   3. Call `prune_dangling_images()`.
   4. Call `stop_builder()`.
   - Every step is best-effort. Log failures and keep going; a cleanup failure must never fail a build or capture that otherwise succeeded.
   - Return a dict listing what was removed, and include it in the tool result as `data["cleanup"]`.

4. **Where to call it:**
   - In `_build_image`, after a successful build or the "already current" short-circuit. **Never after a failed build**, because the old image is still the only one that works.
   - At the start of `run` and `start`, with `active_name=None` and before the new container is created. This cleans up leftovers from crashed runs.
   - Expose it as a new tool operation, `cleanup`, for manual use.

5. **Scope guard.** Every delete must match either the `openmontage-capture` repository, the `om-capture-` name prefix, or the `org.openmontage.role=capture` label. No other image or container may ever be touched. Assert this in code, not just in comments.

## Tests

Add these to `tests/contracts/test_topic_tutorial_fast.py`. Mock subprocess only; real container calls stay in the opt-in smoke test.

- The content hash is stable for the same files and changes when any file under `sandbox/` changes.
- A build calls `remove_image` for the old tag and `:1`, but not for the new tag, and never for `ubuntu:24.04` or any other repository in the fake list output.
- A failed build triggers no removals.
- Cleanup removes stopped `om-capture-*` containers. It skips the active or in-progress one, and it leaves a non-matching container (`postgres`) alone.
- No argv anywhere contains `prune --all`, `prune -a`, or `system prune`.
- A cleanup step that raises still returns success for the build.

In the smoke test, add one real check:
1. Build, then touch a comment in `sandbox/README.md` and build again.
2. Assert `container image list` shows exactly one `openmontage-capture` image.
3. Assert no `om-capture-*` container remains.
4. Revert the README change.

## Done when

- The fast and full suites are green.
- `sandbox/README.md` documents the content-hash tag, automatic cleanup, and the `cleanup` operation.
- `docs/topic-tutorial-v3-handoff.md` §5 has a one-line note on the capture sandbox.
- The work is committed on `feat/topic-tutorial-v3` and not pushed.
- Your report lists what the smoke run removed.
