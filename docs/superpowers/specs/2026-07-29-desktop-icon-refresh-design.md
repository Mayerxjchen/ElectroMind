# ElectroMind Desktop Icon Refresh Design

## Goal

Replace the current application icon, which compresses the cat and the
`ElectroMind` wordmark into a small square, with the user-selected “B · light
cat” direction. The result must read clearly in the macOS Dock, window chrome,
browser favicon, Windows application icon, and Linux launcher.

## Selected Visual Direction

The icon uses the existing transparent pixel-art cat without redrawing it.

- Remove the `ElectroMind` wordmark from every small application icon.
- Enlarge and center the cat so it is the unmistakable primary subject.
- Place it on a light macOS-style rounded-square tile.
- Use a restrained warm-white to pale-blue background and a subtle blue edge.
- Preserve the cat’s white/dark-gray split face, blue eyes and collar, lightning
  medallion, navy pixel outline, and original pixel-art character.
- Do not add extra text, badges, glow, decorative symbols, or a new mascot.

The full wordmark remains available only as a large-format brand asset for
welcome, About, documentation, and marketing surfaces.

## Asset Roles

- `editors/desktop/assets/app-icon.png`: high-resolution application tile used
  by Electron and Linux packaging.
- `editors/desktop/assets/logo-icon.png`: square Web UI/favicon version of the
  same light-cat tile.
- `editors/desktop/assets/icon.iconset/*`: platform-required PNG sizes generated
  from the same master composition.
- `editors/desktop/assets/icon.icns`: macOS bundle icon generated from the
  iconset.
- `editors/desktop/assets/icon.ico`: Windows multi-resolution icon generated
  from the same composition.
- `editors/desktop/assets/electromind-logo.png`: full cat plus wordmark; retained
  as a large-format brand asset and not used as an application icon.

No application-icon path may point at the full wordmark image.

## Composition and Scaling

Create one high-resolution master composition and derive all smaller sizes from
it so Dock, favicon, and packaged icons cannot drift apart.

- Square canvas with transparent pixels outside the rounded tile.
- Tile corner radius approximately 22% of the canvas width.
- Cat occupies approximately 72–78% of the visible tile height.
- Cat is optically centered, with slightly more breathing room above the ears
  than below the paws.
- The tail and both ears remain complete.
- Small sizes are derived from the master and inspected at 16, 32, 48, 128, 256,
  512, and 1024 pixels.

The implementation should use deterministic local compositing and resizing.
Generative redraws are excluded because the existing mascot must remain exact.

## Integration

The existing paths in Electron startup, the renderer favicon, and the packaging
script remain the source of truth. The fix replaces their image contents rather
than introducing additional competing icon paths.

The application must be fully quit and rebuilt before visual verification,
because macOS and Electron cache icons aggressively.

## Verification

1. Verify all expected files exist with the required dimensions and alpha
   channels.
2. Verify transparent corners and no clipped cat pixels.
3. Render or inspect a contact sheet at all target sizes.
4. Confirm no target application icon contains the `ElectroMind` wordmark.
5. Run the Desktop TypeScript check and compile.
6. Rebuild the macOS icon bundle and inspect the resulting application icon.

## Non-goals

- Redesigning the mascot or wordmark.
- Changing application layout, onboarding, or runtime behavior.
- Replacing Electron.
- Adding animated icons.

