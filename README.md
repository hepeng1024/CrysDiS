# CrysDiS

**CrysDiS** stands for **Crystal Diffraction Simulator**. It is a NiceGUI-based crystal-structure and electron-diffraction simulator that can run as a hosted web app, a local browser app, or an operating-system-specific desktop-style package.

The easiest way to try CrysDiS is the hosted web app. However, it may be laggy and disconnect occasionally. The most robust way is to run the Python code directly (see Run From Source below). Desktop packages are useful when users want a double-click local app, which is convenient and performs better than the hosted web version.

## Introduction Slides

A short visual introduction to CrysDiS is available here:

- [CrysDiS introduction slides](docs/CrysDiS_intro.pdf)

## Launch Online

Hosted app:

```text
https://crysdis.onrender.com
```

## Download Desktop Packages

Desktop packages are available from the GitHub **Releases** page. For version `v0.2.0`, download the file matching your operating system.

Release assets:

```text
CrysDiS-Windows-v0.2.0.zip
CrysDiS-Linux-v0.2.0.tar.gz
CrysDiS-macOS-arm64-v0.2.0.zip
```

### Windows

1. Download `CrysDiS-Windows-v0.2.0.zip`.
2. Before extracting, right-click the zip file → Properties → General → Unblock → Apply → OK.
3. Extract/unzip the folder.
4. Open the extracted `CrysDiS` folder.
5. Double-click:

```text
CrysDiS.exe
```

### Linux

1. Download `CrysDiS-Linux-v0.2.0.tar.gz`.
2. Extract it:

```bash
tar -xzf CrysDiS-Linux-v0.2.0.tar.gz
cd CrysDiS
```

3. Run:

```bash
./run_CrysDiS.sh
```

Optional application-menu launcher:

```bash
./install_launcher.sh
```

After installing the launcher, search for **CrysDiS** in your Linux application menu.

### macOS

1. Download `CrysDiS-macOS-arm64-v0.2.0.zip`.
2. Unzip it.
3. Double-click:

```text
CrysDiS.app
```

If macOS blocks the app because it is unsigned, right-click `CrysDiS.app`, choose **Open**, then confirm. This is usually only needed the first time.

## What It Does

- Visualizes real-space unit cells, atom sites, crystallographic planes, real-space vectors, and reciprocal vectors.
- Simulates electron diffraction patterns with the built-in Ewald sphere kinematic method or pymatgen TEMCalculator.
- Supports custom structures, symmetry expansion, CIF upload, atom colors, occupancies, and lattice parameters.
- Supports multiple ordinary panels plus combo panels for overlapped multiphase diffraction patterns.
- Exports crystal and diffraction images with DPI and transparent-background options.

## Quick Use

1. Choose a crystal and enter a zone axis such as `100`, `110`, or `0001`.
2. Press `Apply`.
3. Add planes such as `123 (411) 1,1,4` or vectors such as `100 114 [123] *1,2,3` (see Input Formats below).
4. Rotate the 3D crystal with the mouse. Press `Sync` to update the diffraction pattern to the current view.
5. Use `Download` to export images.
6. Use `Add combo panel` to overlay diffraction patterns from multiple panels.

`Add panel` cycles through the Crystal List: FCC, BCC, HCP, then custom structures in alphabetical order, before starting over. With only the built-in structures, it repeats FCC, BCC, and HCP.

### Builder Coordinates

The crystal builder offers **Fractional** and **Cartesian (nm)** beside **Atom sites**. Switching converts the existing coordinates, not just their labels. For a cubic cell with `a = b = c = 0.3 nm`, `(0.5, 0.5, 0.5)` becomes `(0.15, 0.15, 0.15) nm`.

Cartesian coordinates use the crystallographic Cartesian frame: **a** lies along x and **b** lies in the xy plane. Skew, hexagonal, and triclinic cells use the full lattice matrix, not independent multiplication by a, b, and c. Coordinates on screen stay in the selected representation when lattice parameters change: fractional values track the resized cell, while Cartesian values keep their physical positions. Saved structures, symmetry expansion, chemical formulas, and CIF export continue to use fractional coordinates internally.

### Input Formats

In the **Plane** and **Vector** fields, use **spaces to separate different entries** and **commas to separate the components of one entry**. Compact and bracketed forms can be mixed in the same field.

| Entry type | Accepted examples |
| --- | --- |
| Real-space vector (`u,v,w`) | `114`, `1,1,4`, `[114]`, `[1,1,4]`, `[1 1 4]` |
| Reciprocal vector (`*u,v,w`) | `*123`, `*1,2,3`, `*[123]`, `*[1,2,3]`, `*[1 2 3]` |
| Plane (`h,k,l`) | `411`, `4,1,1`, `(411)`, `(4,1,1)`, `(4 1 1)` |

The letters above stand for integer indices. Reciprocal vectors also accept `r` or `R` instead of `*`, for example `r123`, `R1,2,3`, `r[123]`, and `R[1,2,3]`.

Examples with multiple entries:

- Vector: `100 114 [123]` displays all three vectors.
- Vector: `1,1,4 *1,2,3` mixes a real-space vector and a reciprocal vector.
- Plane: `123 (411) 1,1,4` displays all three planes.

For negative or multi-digit components, use forms such as `1,-1,10`, `[13 3 0]`, or `(1 2 27)`. Compact notation treats each digit as a separate component, so use commas or spaces inside brackets/parentheses to make multi-digit indices unambiguous. When mixing entries, enclose space-separated components in brackets/parentheses, or use commas without brackets.

Use `100 114`, not `100,114`, for two separate vectors or planes: commas mean components, not separate entries. Hexagonal structures also accept four-index forms such as `10-10`, `1,0,-1,0`, `[1 0 -1 0]`, or `(1 0 -1 0)` in the corresponding field.

### Diffraction Brightness

Enable **Uniform spot brightness** in **Advanced** to draw every reflection above the **Spot intensity threshold** at the same brightness. This applies to ordinary and combo panels, settings/download previews, static images, and animations with either renderer and diffraction method. Combo overlays retain a common partial opacity so overlapping phases remain distinguishable.

The threshold uses relative intensities **after compression** in both brightness modes. The **Compression factor** slider remains adjustable from **10 to 200**, including with uniform brightness enabled, so increasing it can bring weak reflections above the threshold. Switching brightness modes alone does not change which reflections are visible. **Spot size scaling effect** remains independent: set it to zero for equal-sized spots as well. Spot sizes, hover intensities, and spot-index priorities use the compressed relative intensities rather than replacing them with ones.

**Spot intensity threshold** accepts values from **1e-10 to 1**, including scientific notation; the default is **1e-4**. Very low values expose weaker calculated reflections, not necessarily physically significant ones. This display cutoff does not change the Ewald method's separate rejection of raw intensities below `1e-10` before normalization. Each Advanced settings control has hover help explaining its behavior.

In ordinary and combo-panel hover labels, relative intensities below **0.01** use scientific notation with up to four significant digits, such as `1e-5` or `1.235e-5`. Values at or above **0.01** retain four decimal places; exact zero is shown as `0`. This only changes the text, not the calculated intensity or the visibility cutoff.

### Panel Display Settings

Open an ordinary panel's **gear icon** to customize its drawing. All sections start collapsed; expand **Crystal frame**, **Atom sizes**, **Displayed cells**, **Vector/Plane colors**, **Panel background colors**, or **Annotations** as needed. These sections are also available in **Global display settings**.

- Show/hide frame lines, change their color and thickness (0.25x to 20x), and show either the **Original cell** frame or **Every cell** frame. Adjacent cells share their common edges; those lines are drawn only once.
- **Frame opacity** is in **Crystal frame**. **Vector/Plane colors** contains **Vector opacity**, **Reciprocal vector opacity**, **Plane fill opacity**, and **Plane edge opacity**. All use 0% for invisible and 100% for opaque. Their defaults are 72%, 95%, 78%, 36%, and 90%, respectively. Frame opacity follows frame inheritance; annotation opacities follow color inheritance. The panel preview, live crystal, PNG downloads, and both animation renderers use these settings. Reciprocal-vector bead opacity scales with its vector opacity. PNG frame and reciprocal-vector opacity match the interactive view.
- **Vector text size/opacity** and **Plane text size/opacity** control annotation labels independently of the arrows and planes. Text size ranges from 25% to 300% of the original size. Default text opacity is 95% for vectors (including reciprocal vectors) and 90% for planes; 0% hides only the corresponding labels. These settings follow color inheritance and affect the preview, live view, PNG downloads, and both animation renderers. The toolbar's **Crystal annotations** checkbox still shows/hides all labels.
- Change all atom radii together, or scale individual elements. The two percentage factors multiply. A mixed-occupancy sphere uses the occupancy-weighted average of its constituent elements' size factors.
- Set signed total cell counts along the lattice vectors **a (x)**, **b (y)**, and **c (z)**, not the screen axes. `2,1,2` displays four cells. `-2,1,2` also displays four, extending toward negative a instead of positive a. The original cell always remains included: `2` spans fractional coordinates 0 to 2, while `-2` spans -1 to 1. Counts of `1` and `-1` both mean just the original cell; zero is invalid.
- Enable **Extend planes and vectors** to clip planes to the expanded block and extend vectors to fit it, preserving their directions. Otherwise annotations remain in the original cell. Reciprocal arrows remain directional illustrations, not a physical real-space length scale.
- **Global display settings** in Advanced sets defaults for all six sections, including per-element atom sizes, diffraction color, vector/plane palettes, backgrounds, and annotations. New panels follow these defaults. Opening a panel's settings starts all **Use global...** checkboxes unchecked, with its current values ready for local editing. This changes only the draft: live inheritance remains unchanged until **Apply/Close**, and closing without applying leaves the panel untouched. Check individual sections or use **Follow global settings** to opt back in. Local sections remain unchanged when global settings are applied. In global settings, keep **Crystal default diffraction color** checked to retain each crystal's own default instead of assigning a common diffraction color. Panel settings instead have a reset icon beside the diffraction color field; it restores that crystal's default in the pending edits.
- A custom panel diffraction color stays unchanged when switching crystals, even if it matches one crystal's default. Resetting the diffraction color restores automatic crystal-specific colors after **Apply/Close**; those colors then follow subsequent crystal changes.
- Live previews on the left copy the panel's crystal view and diffraction pattern, while controls scroll independently on the right. Drag the vertical divider between them to resize the preview and controls areas in 11 positions, from 100:0 to 0:100 in 10% steps. Its edge handle can reopen either hidden side; double-click restores 50:50. The divider stays vertical on narrow screens, with horizontal scrolling available for narrow controls. Each preview has an upper-right magnify/shrink icon: magnifying one gives it the whole preview area and temporarily hides the other; shrinking restores both without resetting the view. The crystal preview supports mouse rotation, pan, and zoom without synchronizing diffraction or changing the real panel. Valid edits update the preview after a short typing delay, including palette changes, frame settings, atom sizes, and expanded cells. Incomplete or invalid display settings keep their last valid preview. Unfinished marker coordinates also keep the previous marker unchanged; completed invalid markers are individually hidden until corrected.
- All panel edits are drafts, including **Reset display** and **Follow global settings**. These two buttons ask for confirmation, then update the preview and leave the window open. Cancel keeps the edits unchanged. Press **Apply/Close** to commit the settings together and close the window; closing with X or Escape discards them. Only affected crystal drawings and diffraction colors are refreshed, with the real panel's viewing direction and roll preserved; changing cell counts refits the enlarged block. Crystal definitions, chemical formulas, diffraction calculations, and CIF exports are unchanged.
- **Reset vector defaults** and **Reset plane defaults** restore the respective built-in palette, geometry opacity, text size, and text opacity in the pending edits, without changing other settings.
- **Panel background colors**, between Vector/Plane colors and Annotations, sets separate crystal and diffraction backgrounds. **White background** and **Black background** set both backgrounds to the chosen color and enable **Automatic text contrast**: scale bars, zone/spot annotations, and crystal vector/plane/marker labels use black or white against the relevant background. Turning this off restores the stored annotation colors; it does not recolor atoms, spots, planes, or vectors. Edits preview immediately and commit with Apply/Close. Backgrounds have their own global-inheritance checkbox. Combined diffraction uses the global background. Static PNG/Three.js images and animations follow these colors; transparent exports remain transparent, with text contrast based on the configured panel background.
- **Annotations** controls the real-space scale bar, reciprocal-space scale bar, current-zone label, and spot indices globally or independently per panel. Each has a text color, font size (6-40 px in the live view), opacity, and position. Scale-bar colors also apply to their lines. Bars and zone labels can use any corner; if the reciprocal bar and zone label share a corner, the zone label is moved inward to avoid overlap. Spot indices have eight positions around their spots and a configurable gap from -20 to 40 px. Zero places the text box at the spot edge without extra padding; negative values compensate for remaining font whitespace and can overlap the spot (stopping at its center). Diagonal distances are measured radially, not once per axis. Scale-bar lengths remain physically calibrated regardless of styling.
- The two scale-bar checkboxes in **Annotations** select real space, reciprocal space, both, or neither. Applying **global** settings checks the toolbar **Scale bar** master switch when either or both bars are selected, and unchecks it when neither is selected. If the global choices match (both on or both off), toggling the toolbar switch also sets both global checkboxes and updates panels that follow global annotations. If exactly one is selected, the toolbar instead hides/restores that selection without changing it. Panel-only edits never change the toolbar switch, and toolbar toggles preserve local annotation choices. **Current zone** and **Spot indices** remain the master switches for those labels. **Use global annotation settings** or **Follow global settings** opts a panel into global annotation defaults; otherwise its local styling is preserved. **Reset annotations** restores built-in annotation defaults in the pending edits. Annotation edits stay pending until **Apply/Close**, and update PNG and animation exports as well. Combined diffraction overlays use each source's spot-index style and global styling for their shared scale bar and zone label.
- The global settings window also uses **Apply/Close** to commit edits and close on success; invalid edits leave it open. After confirmation, **Reset display** in that window restores the global built-in defaults and updates their followers without closing. It never changes element colors: both saved colors and pending element-color edits are preserved.

Both crystal and diffraction backgrounds start as pure black (`#000000`) in Classic dark, including non-transparent exports. Other themes supply coordinated backgrounds, and saved global background preferences are restored on startup. Custom panel backgrounds and transparent exports remain available. This changes only the drawing background, not calculated intensities or diffraction filtering; very dark custom colors may need adjusting for visibility.

### Saved Crystal Views

Use **Save view** in a panel's settings window to keep a named display configuration without duplicating its crystal structure. It saves the pending settings and the preview's current orientation, pan, and zoom; it does not apply them to the original panel. Choose **New saved view** or select an existing view to explicitly update it. **Apply/Close** changes the live panel but never overwrites a saved view.

- Only crystals with saved views gain a small expand arrow in the left gutter of their **Crystal list** row; color dots and names stay aligned across all rows. Expand a row to open, rename, delete, or star its views. Opening a view creates a new panel without replacing existing panels. Every crystal also has an **Open in new panel** button immediately before **Export CIF**, using its starred default view when one is available.
- A starred view is that crystal's default when it is opened in a new panel or selected in a panel, including the startup crystal. Only one view per crystal can be the default; clicking its star again removes the default.
- Views include frame styling, atom sizes, displayed cells, markers, backgrounds, annotation styling/visibility, element colors, vector/plane palettes and indices, diffraction color, orientation, zoom, and the crystal/diffraction divider position. Appearance values are captured rather than linked to future global edits. **Follow global settings**, then **Apply/Close**, releases the loaded panel's overrides without changing the saved view. Toolbar annotation switches still override that visibility when toggled.
- Calculation parameters such as simulation method, voltage, thickness, and intensity filtering remain those of the current session. Views do not store the interface theme, preview-only coordinate grid, animation timeline, or a whole multi-panel workspace.
- Renaming a custom crystal keeps its views attached. **Save as a new structure** creates a separate crystal, without copying views. If a crystal's definition changes, its old default view is skipped and manually opening a saved view asks for confirmation because markers or directions may no longer fit. Review it and explicitly update the view to accept the new structure. Deleting a crystal with views also requires confirmation; deleting only a view leaves the crystal and open panels intact.

Views are stored with atomic writes in the versioned `display_presets.json`, alongside `custom_crystals.json` in the CrysDiS app-data folder. Invalid files are reported and not overwritten. Back up both files to preserve custom structures and their views. On hosted deployments this is server-side storage, shared by users of that deployment; the folder must be persistent to survive redeploys.

### Saved Element Colors

The global display settings window also has an **Element colors** section. Search by element symbol, edit its color, and press **Apply/Close**. Edits and resets remain pending until Apply. Each element has a reset icon; **Reset element colors** clears all overrides. The bulk reset asks for confirmation if any pending element color differs from its built-in default (ignoring hex letter case). Cancel keeps all edits; confirming stages the reset until **Apply/Close**. **Reset display** does not reset element colors.

Only explicitly edited elements are overridden, across all panels following global element colors, independently of the vector/plane palette inheritance checkboxes. Loaded saved views retain their captured element colors until released with **Follow global settings**. Overrides affect existing and newly loaded crystals, display previews, PNG images, and animations. Mixed-occupancy atoms blend constituent colors according to their occupancies. Unedited elements keep their structure-specific atom-site colors or the built-in element defaults. Resetting an override restores those original colors; it does not rewrite the crystal builder's atom-site colors or saved crystal definitions. Diffraction colors are separate and do not change when element overrides change.

Preferences are stored automatically on Apply in `element_colors.json` in the same user app-data folder as `custom_crystals.json`, and loaded when a new CrysDiS session opens. This separate, versioned JSON file keeps personal display preferences out of the crystal library. Writes are atomic; a save failure does not commit the pending settings. Missing preferences use the original colors, and invalid preferences produce a warning and fall back without overwriting the file. This file covers element colors; theme and global background preferences are stored separately as described below.

### Interface Themes

Open **Advanced > Theme** for a separate theme window. It offers **Classic dark** (black views), **Graphite** (charcoal views with mint/gold accents), **Light** (white views), **Forest** (pale green views), **Carbon** (black views with gold/cyan accents), **Rose** (deep plum-neutral views with rose/sage accents), **Lagoon** (pale aqua views), **Ruby** (pale rose views), **Jade** (deep green views with mint/peach accents), **Ember** (warm charcoal views with coral/ice accents), **Orchid** (pale lilac views with orchid/teal accents), and **Sky** (pale blue views with blue/berry accents). Light presets enable automatic black annotation text. Choose a preset or customize the accent, secondary accent, page, dialogs/menus, panel surround, toolbar, text, and crystal/diffraction backgrounds in one color grid. **White background** and **Black background** set both panel backgrounds and enable automatic text contrast. **Dark controls** selects dark styling when checked and light styling when unchecked for inputs, menus, and checkboxes; it does not independently change the crystal or diffraction backgrounds. A small sample previews the pending colors; **Apply/Close** applies and saves them. Closing without applying discards the edits.

**Panel background colors** remains available in Global display settings and individual panel settings. Theme and Global display settings edit the same global background colors and automatic-text-contrast setting: applying either updates the other. Panels following global backgrounds update immediately; panel-specific backgrounds and saved-view overrides are preserved. New panels use the updated global backgrounds. The built-in FCC, BCC, and HCP demonstrations automatically use darker cyan, orange, and violet atom/spot colors on light backgrounds and restore their original colors on dark backgrounds. Atoms follow the crystal background; spots follow the diffraction background, including the global background for combined diffraction. Explicit element/spot colors and custom structures are left unchanged. This adaptation also applies to settings previews and image/animation exports, independently of Automatic text contrast. Neither route changes simulation parameters, camera orientation, or zoom. Non-transparent exports follow their panel backgrounds; transparent exports remain transparent, with the same foreground colors as their configured panel backgrounds.

To keep several designs, click **Save theme**, enter a name, and save. Named copies appear in the Theme selector with **(saved)** after their names. Each copy includes all ten colors, Dark controls, and Automatic text contrast. Selecting a saved theme stages it; **Apply/Close** makes it active. Editing a saved theme creates a working Custom draft without changing the saved copy. The save icon updates that copy after confirmation; the pencil renames it, and the trash icon deletes it after confirmation. **Save theme** can instead save the edited colors under another name. Built-in themes cannot be overwritten or deleted, and duplicate names are rejected without overwriting anything.

Named themes are saved immediately in `saved_themes.json`, separately from the currently applied theme in `theme.json`, beside `element_colors.json`. Closing Theme without applying does not undo an explicit save, rename, update, or deletion. Deleting a named theme leaves the current appearance unchanged. Applying themes, editing global backgrounds, **Reset theme**, and **Reset display** do not overwrite saved copies. Writes are atomic; an invalid saved-theme file is reported and left untouched rather than silently replaced. Back up `saved_themes.json` to keep the named designs.

The preferred active theme, including global panel backgrounds, is restored on startup from `theme.json`. Older theme files without background settings remain readable and keep the former black-background default. **Reset theme** stages Classic dark, including its black backgrounds. **Reset display** keeps interface colors but resets display settings, including backgrounds. These files use the same app-data location as existing preferences, including packaged desktop builds. On hosted deployments, that directory must be persistent to retain preferences across server redeploys; it is server-side storage, not a per-browser account preference.

PNG images and both animation renderers include these display settings. Larger displayed blocks cost more to draw and export. Counts are limited to eight in either direction per axis, 216 cells total, and an estimated 30,000 displayed atoms before shared-boundary deduplication. An oversized global request is rejected before any panel changes. If switching crystals would exceed that replication limit, that panel returns to one displayed cell and stops inheriting cell counts, while retaining its styling. Single-cell structures are not truncated by this limit.

### Static Image Export

The ordinary panel's camera/download dialog offers **Current PNG exporter** and **Three.js** under **Crystal renderer**, defaulting to **Three.js**. Both save PNG image files and use the current viewing direction and roll, including unsynced mouse rotations. Three.js renders lit spheres with the same near-orthographic camera as animations. It supports the transparent-background and DPI controls; very high resolutions depend on the browser's WebGL limits. Diffraction export is unchanged.

The download dialog previews the selected crystal and diffraction images below the export controls. Visual changes update the previews automatically, without changing the live panel. Checkerboard areas indicate transparency. Previews use a limited resolution for responsiveness; downloaded files use the selected DPI. The combo download dialog also previews its combined diffraction pattern.

Both export renderers offer **Shading: None, Mild, Strong, Very strong**. The PNG exporter shades atoms; Three.js adjusts the lighting and highlights on its solid 3D geometry. The light stays upper-left relative to the image during rotation. **None** gives flat colors; **Strong** matches the previous shaded-PNG option. Static downloads default to **Mild** for both renderers, with each renderer remembering its selection while the dialog remains open. Animations start with Three.js and Mild shading; switching to PNG initially uses None. Shading preserves depth overlap, partial occupancies, and translucent planes. These are surface-lighting effects, not cast shadows between atoms or bonds, and do not change the live panels.

Under **Atom sizes** in panel or global display settings, **Site occupancy colors** switches between **Occupancy sectors** (the default) and **Blended colors**. This works in live Three.js panels, settings previews, and both export renderers. A 75% Ni / 25% Ti site becomes one sphere with 75% and 25% colored sectors, shaded continuously across the sphere. Sectors face the viewer as the crystal rotates, keeping the displayed proportions constant. They show statistical site composition, not physically separated pieces of an atom. Underoccupied sites include a neutral gray sector for the missing fraction; invalid totals above 1 are normalized for drawing only and still trigger the existing warning when saving a structure or exporting CIF. Existing occupancy-dependent atom size, opacity, and depth overlap are retained. Sector colors respect structure-specific colors and global element overrides, including repeated cells.

Static and animation exports default to **Panel settings** for occupancy coloring. Choose **Blended colors** or **Occupancy sectors** in the download/animation window to override this without changing the live panel. For combo animations, **Panel settings** preserves each participating panel's own choice.

These shading and occupancy-color options are also available for normal and combo animations, including GIF and PNG-sequence output. They do not change the CIF, chemical formula, or diffraction calculation.

### Crystal Markers

In a panel's gear window, expand **Crystal markers** to add **Point**, **Line segment**, **Plane patch**, or **Polyhedron** markers. These are drawing objects only: they do not add atoms, alter occupancies, change diffraction, or enter CIF files.

The **Coordinate grid** checkbox reveals preview-only grid controls. Choose spacing of 0.1, 0.2, 0.25, **1/3** (exactly one third), 0.5, or 1 in fractional cell coordinates. Leave **Full 3D grid** unchecked for guides on the ab, ac, and bc planes, or check it for a volume grid. **Grid extent** can follow the displayed cells and markers, extend to both sides of the origin in all three lattice directions, or use custom a/b/c minimum and maximum bounds. Custom bounds must include the origin. Very large/dense grids use a coarser multiple of the selected spacing to keep the preview responsive; the effective spacing is displayed when this happens. The single-headed a/b/c arrows and grid follow the crystal's actual lattice angles, including non-orthogonal cells. The guide rotates with the crystal, is independent of the Crystal annotations switch, and is never applied to the normal panel or included in exports.

- Positions use three fractional coordinates along a/b/c or Cartesian coordinates in nm. Negative and out-of-cell positions are allowed and are not periodically wrapped. Coordinate entries accept commas, spaces, and fractions such as `1/2`. A marker is attached to the crystal frame, not the screen.
- Click the crosshair beside a position or vertex field, then click an atom in the crystal preview to fill that field. The picker uses the field's fractional or Cartesian mode, works with all displayed atoms (including expanded cells), and turns off after one selection. Click the crosshair/cancel button again to cancel. Rotation and zoom remain available while picking. **Atom position** also offers a searchable list of the first 500 atoms. Points can be viewer-facing circles or colored spheres. Adjust the radius and line thickness in nm, color, opacity, visibility, and optional name label. Labels follow the toolbar's **Crystal annotations** switch.
- Line segments offer plain, single-headed (A to B), and double-headed styles. The **Edge style** selector offers solid, dashed, dotted, and dash-dotted shafts and surface edges, in both live views and exports.
- Plane patches accept 3-64 vertices in boundary order, including concave polygons. Add/remove vertices and use their drag handles or arrow buttons to reorder them. All vertices must be coplanar (within `1e-8` of the patch's extent); repeated vertices, crossing edges, and zero-area patches are invalid.
- Polyhedra use the convex hull of 4-64 non-coplanar vertices. They can be tilted or skewed, with configurable edge and face opacity. Interior points do not affect the hull; concave solids are not inferred. Coplanar hull triangles are merged into polygon faces so internal diagonals are not drawn. The separate Box tool has been removed; older Box markers become eight-vertex, unfilled polyhedra when edited, preserving their shape and edge styling.
- Colored spheres and viewer-facing circles use a single **Marker size** percentage control. At an occupied position it defaults to that exact atom's size, including element-specific scaling and occupancy; at an empty position it defaults to **All atom sizes**, never the nearest atom. The percentage follows these defaults until manually edited. All-atom and element-specific factors multiply (for example, 120% and 150% give a displayed marker percentage of 180%); the supported range is 1% to 900%. Enter a larger percentage to surround an atom with a circle. New circles have **Line thickness** 0.005 nm; that control is disabled for colored spheres. Spheres use the same lighting as atoms in the live view and the selected atom shading in either export renderer; they still do not contribute to diffraction.
- **Transparent (hide atom)** is a point-marker option that hides the atom at its exact three-dimensional position in the preview, live view, static exports, and animations. Use the atom picker to target a site. It is a display-only visibility mask, not a transparent object painted over the scene: frame lines remain intact, atoms behind the hidden site can still be seen, and structure data, composition, and diffraction are unchanged. Only that displayed copy is hidden, not all periodic copies; a point away from any site hides nothing. Marker size and opacity do not control this binary effect. Uncheck the option, turn off the marker's **Visible** checkbox, delete the marker, or reset the display to restore the atom. Apply/Close commits the preview changes.
- Labels have adjustable size, color, opacity, screen-relative placement (center or eight surrounding directions), and gap from the marker's center. By default their color follows the marker. Empty names fall back to the marker type. The toolbar's **Crystal annotations** switch controls their overall visibility, and enabling a marker label while that switch is off gives a reminder. Coordinate fields and atom-position choices display floating-point residues smaller than `1e-14` as exactly zero, as do builder coordinates.
- While a coordinate triple is unfinished, the previous marker preview is kept unchanged, without warnings. Once all three components of every position are entered, the preview updates; invalid coordinates or geometry hide that marker and show a warning beside the fields. Correcting the input restores the marker automatically. An already-hidden invalid marker stays hidden while its correction is incomplete. **Apply/Close** still rejects incomplete or invalid markers rather than silently committing an older preview or deleting them. Closing without applying discards the draft. **Reset display** asks for confirmation and clears markers while preserving element colors. **Follow global settings** asks for confirmation and preserves both. Panel changes remain in the preview until **Apply/Close**. Markers are panel-local and are not inherited from global settings.
- Drag a position's left-hand handle to reorder line endpoints, plane-patch vertices, or polyhedron vertices. The up/down buttons remain available. A line's single-headed arrow always runs from Position A to Position B, so swapping its endpoints reverses the arrow. Reordering preserves raw input, even while coordinates are incomplete, and cancels any active atom picker.
- The crystal preview stays above the diffraction preview on the left, while the settings scroll independently on the right. Their vertical divider adjusts the space given to previews and controls without changing pending edits. Rotate, pan, and zoom the preview crystal with the same mouse controls as the normal panel. This inspection view does not rotate the live panel or synchronize diffraction, and its orientation is not applied by **Apply/Close**.
- Live Three.js, static PNG/Three.js exports, and both animation renderers include markers, depth overlap, and translucent fills. The view refits when markers extend the drawing bounds. Markers are not replicated automatically when displaying more cells.
- Marker fields shrink to share rows as the settings divider moves, including the coordinate entry and atom-position selector; they stack only when their available area is very narrow.
- Limits: 300 markers, coordinate components between -1000 and 1000 in the chosen units, and 5000 edge pieces (segments or dots) per panel. Plane patches and polyhedra retain the 64-vertex limit. Markers are session display settings, not entries in the persistent crystal library; animation ZIP metadata records them.

Click an atom in either a normal crystal panel or the settings preview to inspect its element/site label, fractional coordinates along a/b/c, and Cartesian coordinates in nm. These describe the atom center relative to the crystal origin, not the mouse's intersection with the sphere surface or the centered drawing coordinates. Boundary copies and repeated cells retain their actual positions, including negative coordinates; they are not wrapped into the original cell. The nearest atom under the pointer is selected, ignoring frame lines and annotation surfaces. Click empty space or the readout's close icon to dismiss it. Picking runs only on clicks, not on hover or during rotation, and the readout is not included in exports.

In normal and combo panels, drag the divider to resize the two views within the same panel. It snaps to 11 positions in 10% increments, from 100:0 through 50:50 to 0:100, so either view can be completely hidden. The handle remains at the edge to reopen a hidden view; double-click it to restore equal sizes (the default for both panel types). The split is independent for each panel and survives panel magnification and crystal changes. On narrow screens the views stack vertically and the divider adjusts their heights instead. Resizing does not change crystal orientation or diffraction data.

In a combo panel's crystal list, drag the handle at the left of a row to reorder its source crystals. The up/down buttons remain available. Reordering changes the list and overlay order, not the crystals' orientations or their bound-motion settings.

### Animation Export

Open an ordinary panel's camera/download dialog, then choose **Create animation**. The starting orientation is captured from the live crystal view, including mouse rotations that have not been synced. Animation uses an isolated copy of that panel's structure, annotations, colors, and scientific settings; it does not rotate or refresh the original panels or their bound combo panels.

- Set the starting angle in the ordinary crystal panel before opening its download dialog. The animation window uses that panel view as its only starting point, shown as **Starting panel view: [100] zone, roll 0.000 deg**, for example. Reopening the window captures the latest panel view; there are no separate starting-orientation controls.
- Add and reorder **Rotation**, **Zone axis**, and **Pause** steps. Each has a duration; moving steps offer constant speed or ease-in/ease-out. Events occupy one row on desktop, with **Start event** after **Speed** and **Snap back view** between the zone axis and duration. Small screens wrap controls to keep them readable.
- Crystal-frame rotations accept the same real/reciprocal axis indices as the panel, such as `001`, `[1,1,0]`, or `*1,2,3`. Angles retain their sign and full turns: `720` means two complete revolutions.
- Lab/screen-frame rotations accept three Cartesian components separated by commas: X right = `1,0,0`, Y up = `0,1,0`, and Z toward the viewer = `0,0,1`. Arbitrary axes such as `1,2,0` also work. Positive angles follow the right-hand rule; positive screen-Z rotations appear counterclockwise.
- Zone-axis steps offer **Snap back view**. On: smoothly transition to the same fixed, zero-roll orientation as a snapped normal panel. Off: use the shortest tilt without additional twist; exactly opposite zone axes use the current screen-up axis to choose between equally short paths. New zone steps inherit the main app's snap-back setting. A pause holds the preceding endpoint.
- **Start event: With previous** joins an event to the previous simultaneous group. A group may contain one zone target and multiple rotations, but not two zone targets or a pause. At every frame the zone motion is applied first, followed by rotations in list order, regardless of the zone row's position. Thus a zone-plus-rotation group reaches the same endpoint as executing zone first and rotation second, while both progress together. A rotation away from the zone can change the final viewing direction, just as in a normal panel.
- Simultaneous rotations are an ordered composition, not a sum of angles about different axes: reordering them can change the result. Each keeps its duration, easing, signed angle, and complete turns. Shorter events hold their completed contribution until the longest finishes; use equal durations to finish together.
- Choose the **current PNG exporter** for the depth-composited illustration style, or **Three.js** (the default for normal and combo animations) for a 3D-rendered image. Both offer the four **Shading** presets and optional occupancy sectors. Three.js uses the normal panel's 1-degree field of view for the same near-orthographic appearance. Both include the panel's planes, vectors, annotations, and scale bar settings. View framing stays fixed throughout the animation.
- Press and hold the dotted handle beside the event number, drag the row to its new position, then release. Clicking the handle alone does not move an event; the up/down arrows are an alternative. **Duplicate event** inserts an independent copy immediately below, preserving its axis, angle, reference frame/crystal, duration, speed, snap-back setting, and timing. These controls work in ordinary and combo animations and are disabled during rendering. **With previous** always refers to the event's new position after a move or copy; the normal simultaneous-event validation still applies.
- Select **Ewald Sphere Kinematic** or **Pymatgen TEMCalculator** independently of the main app setting. Ewald follows continuous orientation; Pymatgen selects reflections from the nearest integer zone, so reflections may change abruptly during a tilt. Both views use the same orientation at every frame.
- Export the crystal, diffraction, or both side by side as **GIF** or a **PNG sequence (ZIP)**. **Transparent background** works with either renderer and format. PNG preserves full color and alpha, including translucent planes. The ZIP includes numbered frames and `animation.json` with timing, the captured starting orientation, and calculation settings.
- **Show crystal name** optionally adds the crystal name above the animation, without a panel-number prefix. It works with either renderer, all content choices, GIFs, and PNG sequences. Ordinary animations start with it off; combo animations start with it on. Turning it off removes the title band without resizing the crystal or diffraction view.
- Transparent GIFs offer **Clean edges (matte)** (the default) and **Dithered alpha**. There is no plane-dependent automatic mode.
- **Clean edges (matte)** blends partially transparent pixels against **Matte / slide color**, without making pixel holes in lattice lines, atom edges, labels, or planes; fully empty pixels remain transparent. Match the matte color to the intended solid slide background. Planes retain their blended appearance and rear atoms remain visible, but their pixels and antialiased edges are now opaque RGB colors, not true partial transparency. A different or textured slide background can reveal halos or filled plane regions.
- Dithered alpha retains the original screen-fixed pixel-hole approximation for use over arbitrary backgrounds, at the cost of grain and crawling edges during rotation. GIF itself only has on/off transparency and a 256-entry palette (255 colors plus transparency). Higher resolution can reduce visible pixel size, but increasing fps will not remove this grain. Use PNG sequences when you need full-color, smooth alpha independent of the background.
- **Preview** renders the complete sequence with up to 360-pixel crystal/diffraction views and 10 fps. Export uses the selected resolution and frame rate. Status text identifies Preview or Export and the frame rate actually used. For example, a 9-second sequence has 90 preview frames at 10 fps and 180 exported frames at 20 fps; both play for 9 seconds. Frames include both endpoints; their playback durations sum to the requested sequence duration, rounded to GIF's 10 ms timing units. Very fast turns at low frame rates can appear stationary or rotate backwards due to temporal aliasing; increase the duration or frame rate.
- **Loop GIF** repeats the sequence without an automatic return transition. Use matching initial/final orientations for a seamless loop, or add a return step. Save/load the sequence as JSON to reuse its events; loading never replaces the captured panel starting view, including for older saved sequences. Crystal-frame axes are interpreted for the crystal in the receiving panel.

In browser/hosted mode, downloads use the browser's save preferences. In Chrome, enable **Settings > Downloads > Ask where to save each file before downloading** to choose the location and name. Animation exports use the **File name** field; saved event sequences suggest `crysdis_animation.json`.

Packaged desktop mode (or `CRYSDIS_DESKTOP=1`) explicitly opens a native **Save As** dialog for sequence JSON and normal/combo animation GIF or ZIP exports, even if the interface opens in a browser. Choose both filename and location there; the selected animation format determines the extension. The picker opens before animation rendering, and canceling saves nothing. The last selected folder becomes the current export folder. Native-window mode uses pywebview's save dialog; otherwise the app tries the system picker (Zenity/KDialog/Yad on Linux, or Tk). If no picker is available, it reports an error instead of silently saving. Static-image and CIF exports retain their existing export-folder controls.

Export runs on demand, supports cancellation, and removes temporary frames afterward. Large structures, high `Max hkl`, long sequences, and high resolutions increase export time. There is a 5000-frame limit per export. Pillow and SciPy are used; ImageIO and FFmpeg are not required for GIF or PNG-sequence export.

### Bound Multi-Panel Animation

Open a combo panel's camera/download dialog and choose **Create animation**. Its source crystals move together during export, regardless of the live **Bind crystal motion** checkbox; no live panels or binding settings are changed. Their starting views, structures, annotations, display settings, and colors are captured when the animation window opens. **Include other bound panels**, when available, also includes panels connected through other enabled motion bindings.

- Each moving event has a **Reference crystal**. For example, tilt to `[111]` in panel 1, then to `[001]` in panel 2. Crystal-frame axes and zone targets are interpreted using that event's reference crystal; every other crystal follows the same screen-frame motion, preserving the original orientation relationship. **Snap back view** applies to the reference crystal, not independently to each follower. Lab/screen axes are shared by all participants.
- Full turns, pauses, easing, and **With previous** work as in ordinary animations. A simultaneous group permits one zone target and multiple rotations, even with different reference crystals. Zone motion is composed first, then rotations in row order; reordering rotations can change the result. Missing reference panels are rejected rather than silently substituted.
- **Crystals + combined diffraction** creates a grid of crystal views and one diffraction overlay. **Individual panels in one image** creates one grid animation, with crystal-only, diffraction-only, or both chosen separately for each panel. **Combined diffraction only** exports the overlay alone. **Show crystal name** controls labels in every layout, including separate files: each source is labeled with its crystal name only, and an overlay lists its source crystal names joined by `+`. Source order and diffraction colors follow the combo's participants.
- **Separate files for each panel** exports a ZIP containing `panel_1.gif`, `panel_2.gif`, etc., or one numbered PNG-sequence folder per panel. Each panel has its own content selector. The ZIP includes `animation.json` with reference events, captured orientations, calculation settings, and shared timing. All files have identical frame counts and frame durations, but separate GIF playback in presentation software is not guaranteed to stay synchronized. Use a single composite GIF for guaranteed synchronization within the file.
- Separate-file **Preview** displays the outputs together in one grid; it does not change the separate-file export. Both crystal renderers, diffraction methods, and the matte/dithered GIF transparency choices remain available. The chosen GIF transparency mode applies consistently to all participants, regardless of whether they contain planes; PNG sequences always preserve full alpha.
- For **Individual panels in one image** and **Separate files for each panel**, each panel's content selector appears immediately below the export-layout/format row. These choices are retained when switching layouts; only included panels are shown.
- Saved bound sequences retain the reference panel IDs. Load them with those panels included; starting views remain those captured from the current panels. Ordinary single-panel sequences can also be loaded and initially use the first participating panel as their reference.

Bound exports additionally limit the total to 20,000 panel frames; combined images are limited to 32 megapixels per frame. **Tile height** specifies the size of each square crystal or diffraction view, not the total grid size. Three.js renders one panel stream at a time to avoid allocating an extra WebGL context for every participant. Export and preview both support cancellation.

## Run From Source

First install Git and Anaconda/Miniconda. Then clone the repository:

```bash
git clone https://github.com/hepeng1024/CrysDiS.git
cd CrysDiS
```

Create and activate the conda environment:

```bash
conda env create -f environment.yml
conda activate crysdis
```

Start CrysDiS:

```bash
python CrysDiS.py
```

Then open:

```text
http://127.0.0.1:8080
```

Choose another port when needed:

```bash
NICEGUI_PORT=8094 python CrysDiS.py
```

On Windows PowerShell:

```powershell
$env:NICEGUI_PORT = "8094"
python CrysDiS.py
Remove-Item Env:\NICEGUI_PORT
```

## Update A Clone

```bash
cd CrysDiS
git pull
conda env update -f environment.yml --prune
conda activate crysdis
python CrysDiS.py
```

## Run With Pip

From this folder:

```bash
python -m pip install -e .
python CrysDiS.py
```

Then open:

```text
http://127.0.0.1:8080
```

## User Data And Privacy

- CIF files are uploaded through the browser and parsed by the running CrysDiS app.
- Bundled structures are read from `custom_crystals_local.json`.
- User edits and CIF imports are saved to the operating system's CrysDiS app-data folder.
- Desktop package image exports are saved to the selected export folder, initially `Downloads` (falling back to the app-data exports folder if needed). Sequence JSON and animation exports use a native Save As dialog.
- Hosted web exports use the browser's normal download behavior instead of saving files on the server.
- On a shared hosted deployment, saved custom structures and crystal views may be visible to other users of that same deployment account.
- For sensitive unpublished data, prefer the local desktop package, a private lab server, a university VM, a VPN-protected service, or a private cloud app with authentication.

Common user-data locations:

```text
Windows: %LOCALAPPDATA%\CrysDiS\custom_crystals.json
Linux:   ${XDG_DATA_HOME:-~/.local/share}/CrysDiS/custom_crystals.json
macOS:   ~/Library/Application Support/CrysDiS/custom_crystals.json
```

## Developer Documentation

Developer notes have been moved out of the main README:

```text
docs/PACKAGING.md
docs/DEPLOYMENT.md
```

Use `docs/PACKAGING.md` for Windows/Linux/macOS package-building notes. Use `docs/DEPLOYMENT.md` for Docker, Render, and hosted deployment notes.

## Main Files

- `CrysDiS.py`: main app
- `CrysDiS_views.py`: versioned saved-view storage (bundled with the main app)
- `custom_crystals_local.json`: bundled custom crystal seed/library data
- `assets/`: app icons and bundled runtime assets
- `environment.yml`: conda environment for running from source
- `requirements.txt`: pip dependency list used by `environment.yml`
- `pyproject.toml`: Python project metadata and dependencies
- `Dockerfile`: reproducible container build
- `.dockerignore`: keeps the Docker build context small
