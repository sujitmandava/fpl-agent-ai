---
name: FPL Agent
description: The gameweek drawn on a dressing-room tactics board, magnets, marker and all.
colors:
  wall: "#e6e8eb"
  wall-deep: "#d9dde2"
  board: "#f7f8fa"
  board-line: "#cfd4db"
  frame: "#a3aab3"
  frame-light: "#c6ccd3"
  ink: "#15181c"
  ink-2: "#4a525c"
  ink-3: "#6b737d"
  magnet-blue: "#1d4ed8"
  magnet-blue-deep: "#1739a8"
  marker-red: "#c81e1e"
  red-soft: "#fbe4e4"
  error-ink: "#7f1212"
  armband-yellow: "#ffd400"
  doubt-amber: "#b45309"
  notice-wash: "#fdf1df"
  notice-ink: "#6b3a07"
  plate: "#15181c"
  plate-2: "#262b31"
  plate-text: "#f3f4f6"
  plate-mute: "#b7bec7"
  field-white: "#ffffff"
typography:
  display-figure:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "clamp(50px, 14.5vw, 84px)"
    fontWeight: 900
    lineHeight: 0.82
    letterSpacing: "-0.03em"
    fontVariation: "'wdth' 72"
    fontFeature: "'tnum'"
  display:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "clamp(36px, 10.4vw, 64px)"
    fontWeight: 900
    lineHeight: 0.98
    letterSpacing: "-0.012em"
    fontVariation: "'wdth' 78"
  headline:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "clamp(26px, 6vw, 38px)"
    fontWeight: 900
    lineHeight: 1.02
    letterSpacing: "-0.01em"
    fontVariation: "'wdth' 85"
  title:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "22px"
    fontWeight: 800
    lineHeight: 1.1
    letterSpacing: "-0.01em"
  section-title:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "19px"
    fontWeight: 800
    lineHeight: 1.1
  gain-figure:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "26px"
    fontWeight: 800
    lineHeight: 1
    fontVariation: "'wdth' 72"
    fontFeature: "'tnum'"
  move:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "16px"
    fontWeight: 700
    lineHeight: 1.3
  body:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.45
    fontFeature: "'tnum'"
  lede:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "17px"
    fontWeight: 400
    lineHeight: 1.45
  proof:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "12.5px"
    fontWeight: 400
    lineHeight: 1.35
  counter-name:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "11.5px"
    fontWeight: 700
    lineHeight: 1.25
  label:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "10px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "0.08em"
  marker:
    fontFamily: "Permanent Marker, Marker Felt, cursive"
    fontSize: "clamp(17px, 4.8vw, 22px)"
    fontWeight: 400
    lineHeight: 1
rounded:
  tick: "4px"
  control: "8px"
  plate: "10px"
  frame: "12px"
  sheet: "16px"
  pill: "99px"
  magnet: "50%"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  gutter: "16px"
  lg: "28px"
  xl: "44px"
  xxl: "72px"
components:
  button-primary:
    backgroundColor: "{colors.magnet-blue}"
    textColor: "{colors.field-white}"
    typography: "{typography.move}"
    rounded: "{rounded.plate}"
    padding: "0 18px"
    height: "52px"
  button-primary-hover:
    backgroundColor: "{colors.magnet-blue-deep}"
    textColor: "{colors.field-white}"
  button-secondary:
    backgroundColor: "{colors.field-white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "8px 14px"
    height: "42px"
  pill-toggle:
    backgroundColor: "{colors.field-white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "8px 14px"
    height: "40px"
  pill-toggle-pressed:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.field-white}"
  input-team-id:
    backgroundColor: "{colors.field-white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.plate}"
    padding: "10px 14px"
    height: "52px"
  segment:
    backgroundColor: "{colors.field-white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "0 12px"
    height: "40px"
  segment-selected:
    backgroundColor: "{colors.magnet-blue}"
    textColor: "{colors.field-white}"
  counter-mine:
    backgroundColor: "{colors.magnet-blue}"
    textColor: "{colors.field-white}"
    rounded: "{rounded.magnet}"
    size: "clamp(36px, 10.6vw, 48px)"
  counter-incoming:
    backgroundColor: "{colors.marker-red}"
    textColor: "{colors.field-white}"
    rounded: "{rounded.magnet}"
    size: "clamp(36px, 10.6vw, 48px)"
  counter-out:
    backgroundColor: "transparent"
    textColor: "{colors.marker-red}"
    rounded: "{rounded.magnet}"
    size: "clamp(36px, 10.6vw, 48px)"
  armband:
    backgroundColor: "{colors.armband-yellow}"
    textColor: "{colors.ink}"
    rounded: "{rounded.tick}"
    size: "17px"
  plate:
    backgroundColor: "{colors.plate}"
    textColor: "{colors.plate-text}"
    rounded: "{rounded.plate}"
    padding: "14px 16px 12px"
  subs-strip:
    backgroundColor: "{colors.board}"
    textColor: "{colors.ink}"
    rounded: "{rounded.frame}"
    padding: "10px 12px 12px"
  sheet:
    backgroundColor: "{colors.board}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sheet}"
    padding: "6px 16px 24px"
  tab-active:
    textColor: "{colors.magnet-blue}"
    typography: "{typography.counter-name}"
---

# Design System: FPL Agent

## Overview

**Creative North Star: "The Dressing-Room Tactics Board"**

Every working screen is a white melamine board in a brushed-aluminium frame, hung on a cool grey wall. The squad sits on it as glossy magnetic counters; the week's transfers are drawn in red marker, each arrow pulling an outgoing counter off the pitch to the incoming one. Beside the board hangs one dark plate that lists the same moves in type, with the evidence under each. The metaphor is literal enough to be read at a glance on a phone before the deadline, and the data never depends on it: everything on the board is said again, in set type, somewhere readable.

Density is a manager's, not an analyst's. One stake figure, one board, one plate, then the long tables below the fold for anyone who wants them. Type is a single workhorse grotesque (Archivo) whose width axis does the hierarchy work: condensed and heavy for figures and names, normal width for reading. Hand lettering (Permanent Marker) is the marker on the board and nothing else.

The system is light only, on purpose. A whiteboard is a light object, and the product is used on phones in daylight, on the bus or at work, in the days before a deadline. There is no dark theme and no `prefers-color-scheme` branch; the browser chrome is tinted to the wall (`themeColor` #E6E8EB). The one dark surface is the reversed plate, which is an object in the room, not a mode.

**Key Characteristics:**
- Physical materials, rendered lightly: wall, framed board, magnets, marker. No textures, no photographs.
- One grotesque on a width axis; condensed for numbers, normal for words; tabular figures everywhere.
- Blue is yours, red is change, yellow is the captain and the gain. Each is always paired with a shape or letter.
- One reversed plate and one display-scale figure per screen.
- Marker annotates; type carries the data.
- Motion is the marker being drawn and the magnet being lifted; nothing else moves on its own.

## Colors

A cool, near-neutral room with three saturated magnet colours that each mean one thing.

### Primary
- **Magnet Blue** (magnet-blue): your players' counters, the primary action (team ID submit, failure retry), the selected segment, the active tab, focus rings, the "ahead" stake figure. Its deep partner (magnet-blue-deep) is the magnet's shaded edge, the hover state of the primary button, links, the product mark, and the winning cell in the backtest table.

### Secondary
- **Marker Red** (marker-red): change and loss. Incoming counters, the dashed ring of an outgoing counter, move arrows, marker gain annotations, the "behind" stake figure, invalid-input borders, and the text caret. Red Soft (red-soft) is the wash behind inline errors and the lifted ghost of an outgoing counter. Error Ink (error-ink) is the text of every error message, on red-soft or on the wall.

### Tertiary
- **Armband Yellow** (armband-yellow): the captain's armband, gain figures on the reversed plate, the "Sample" tag on the landing plate, the focus ring inside the plate, the pressed-move wash (at 8%), text selection, and the `mark` highlight in how-to copy. It only ever sits on ink or the plate, never as text on the board.
- **Doubt Amber** (doubt-amber): the small injury-doubt badge on a counter. Notice Wash and Notice Ink (notice-wash, notice-ink) carry plan notes and player news in a warm box.

### Neutral
- **Wall** (wall) and **Wall Deep** (wall-deep): the page background and the desktop rail.
- **Board** (board): the melamine surface of the board, subs strip, sheets, tables and code chips. **Field White** (field-white) is reserved for controls that sit on the board (inputs, segments, toggles, the vice badge), so they read as a separate layer.
- **Board Line** (board-line): pitch markings, control borders, table rules, band dividers.
- **Frame** and **Frame Light** (frame, frame-light): the aluminium frame gradient and the frame-coloured border on loading and empty boards.
- **Ink** (ink), **Ink 2** (ink-2), **Ink 3** (ink-3): marker black and primary text; secondary text; tertiary labels and table heads (kept at 4.5:1 or better on the board).
- **Plate** (plate), **Plate 2** (plate-2), **Plate Text** (plate-text), **Plate Mute** (plate-mute): the reversed plate's surface, its row rules, its text and its proof lines.

### Named Rules
**The Magnet Meaning Rule.** Blue means a player you keep, red means a player arriving or leaving, yellow means the captain or a gain. Do not use these three for decoration, categories or charts.

**The Colour-Plus-Shape Rule.** Colour is never the only signal. Captain and vice carry the letters C and V; outgoing counters are a dashed ring with the name struck through; rival-owned players carry a letter disc; doubles carry "×2"; doubt carries its own badge; the stake figure carries "behind" or "ahead" in words beside it.

## Typography

**Display Font:** Archivo, variable with the `wdth` axis (fallback Helvetica Neue, Arial)
**Body Font:** Archivo at normal width
**Annotation Font:** Permanent Marker (fallback Marker Felt, cursive), board annotations only

**Character:** A plain, sturdy grotesque that turns into a condensed scoreboard face when it sets numbers, paired with a felt-tip hand that only ever writes on the board.

### Hierarchy
- **Display Figure** (900, clamp(50px, 14.5vw, 84px), 0.82, width 72%): the one stake figure, the gap to the rival or total points. On the landing's league band it runs to clamp(64px, 18vw, 96px).
- **Display** (900, clamp(36px, 10.4vw, 64px), 0.98, width 78%): the landing promise only. Max 15ch.
- **Headline** (900, clamp(26px, 6vw, 38px), 1.02, width 85%): landing band claims.
- **Title** (800, 19 to 22px, 1.1): screen titles, the plate head, sheet heads, section heads below the fold (19px).
- **Gain Figure** (800, 26px, width 72%): the per-move gain and captain xPts on the plate, in yellow; plate totals use 22px.
- **Move** (700, 16px): the "Out → In" line on each plate row.
- **Body** (400, 15px, 1.45): running text; ledes at 17px; captions 13px in ink-2, max 70 to 75ch.
- **Proof** (400, 12.5 to 13px): the stat line under each move, in plate-mute.
- **Counter Name** (700, 11.5px, on an 85% board-coloured chip): player names under magnets; the number inside the magnet is 800 at clamp(13px, 3.6vw, 16px).
- **Label** (700, 10px, 0.08em, uppercase, ink-3): board markings and component labels only ("Out" lane, "Subs, in order").
- **Marker** (400, clamp(17px, 4.8vw, 22px), rotated -4 to -6 degrees): gain annotations and board notes; clamp(24px, 6.6vw, 32px) on the landing's large board.

### Named Rules
**The Width-Axis Rule.** Hierarchy for numbers comes from the width axis and weight, not from more faces. Any figure that is a name or a number on a counter, a gain, or the display figure is set condensed (`.cond`, width 72%).

**The Marker Annotates Rule.** Permanent Marker is never the only place a value appears. The board's marker gains are `aria-hidden` and repeat a figure the plate sets in type. Marker never sets labels, buttons, headings or body copy.

**The Tabular Rule.** `font-variant-numeric: tabular-nums` is set on the body; columns of figures always align.

## Layout

Phone first, at a 16px gutter. The Plan screen stacks: a wordmark row (phone only: "FPL Agent" at 17px 800 in sentence case on the left, Options on the right), the title bar, stake line, framed board at full width, the reversed plate, the subs strip, then the below-fold sections (close calls, chip outlook, plan by gameweek, why this plan). Spacing steps used: 4, 8, 12, 16, 28, 44, 72px, with 6, 10 and 14px inside components.

From 760px the work area becomes two columns: the board (up to 540px) with the subs strip under it on the left, the plate (300 to 400px) on the right spanning both rows, 28px column gap. From 960px the wordmark row hides, Options moves into the title bar, and the shell gains a 216px left rail on wall-deep that carries the brand, while the phone's fixed bottom tab bar (five tabs, board-white at 96%) goes away. The landing goes two-column at 900px: promise and ID box left, the large sample board right, the first viewport at least the screen's height; bands alternate claim and demonstration (`flip`), 72px vertical padding, divided by board-line rules. The team ID field and submit stack below 420px. When the team does not exist the shell drops its section navigation: no tab bar on phones, and the rail keeps only the brand and "Switch team".

**The League-Column-Survives Rule.** On phones (below 760px) low-value table columns give way so the league columns survive: Bench and Price diff hide, and the Edge header drops its "vs Rival" tail, while League EO and Edge always stay visible.

**The Board-First Rule.** On every working screen the framed board is the largest object in the first viewport; tables and long copy live below it.

The League screen keeps the Plan grid: stake line, race board left with the "Head to head" plate right from 760px (stacked on phones), then full-width sections below: standings (your row on a 6% blue wash with a "You" pill; the rival marked by their letter disc; tapping a manager makes them the rival), the two "Only you" / "Only rival" lists side by side, the gameweek table with "Projected" and "Played" row groups on a wall-coloured head, and who the league owns.

## Elevation & Depth

Depth is physical and small: magnets sit on the board, the board sits in its frame, the frame and panels hang off the wall. Shadows are soft, ink-tinted, never coloured except the primary button's soft blue glow. No hard offset shadows anywhere. The board itself is recessed with an inner shadow; nothing on the wall floats more than the frame.

### Shadow Vocabulary
- **Magnet** (`box-shadow: 0 2px 3px rgb(21 24 28 / 0.28), 0 1px 0 rgb(21 24 28 / 0.18)`): a counter at rest.
- **Lift** (`box-shadow: 0 8px 14px rgb(21 24 28 / 0.24), 0 2px 4px rgb(21 24 28 / 0.2)`): a counter on hover or when its move is selected.
- **Panel** (`box-shadow: 0 1px 2px rgb(21 24 28 / 0.08), 0 6px 18px rgb(21 24 28 / 0.06)`): the plate, subs strip, tables, the active rail item.
- **Frame**: an inset highlight plus `0 10px 24px rgb(21 24 28 / 0.14), 0 2px 4px rgb(21 24 28 / 0.12)` on the aluminium frame.
- **Board recess** (`inset 0 0 0 1px rgb(21 24 28 / 0.06), inset 0 2px 6px rgb(21 24 28 / 0.08)`): the melamine inside the frame.
- **Primary** (`box-shadow: 0 1px 2px rgb(21 24 28 / 0.2), 0 6px 14px rgb(29 78 216 / 0.25)`): the team ID submit, the only coloured shadow.
- **Sheet** (`0 -8px 30px rgb(21 24 28 / 0.18)`; `-8px 0 30px rgb(21 24 28 / 0.16)` as a side sheet) over a 42% ink backdrop.

### Named Rules
**The Lift-Means-Selected Rule.** A counter rises (translateY -3px, scale 1.07, lift shadow) only when you hover it or its move is selected. Outgoing ghosts never cast a shadow; a lifted ghost fills with red-soft instead.

## Shapes

Round magnets (50%), a frame with gently rounded corners (12px outer, 6px board), plates and the ID field at 10px, controls at 8px, tiny badges and code chips at 4px, pills (99px) for toggles, the Options button and tags. Bottom sheets round their top corners at 16px; the desktop side sheet is square. Lines are hairline: pitch markings at a non-scaling 0.45 stroke, the out lane a 2-2 dashed rule. The dashed stroke is reserved for "leaving": the outgoing counter's ring and the rival picker's underline are the only dashes. A dotted stroke (round dots, never dashes) means "projected": the race board's projection is the only one.

## Components

### Magnet Counters
The squad as glossy magnets: a radial-gradient disc (blue for mine, red for incoming, grey #9aa3ad for a blank slot) with a white gloss highlight across its top 38%, white condensed xPts in the centre and the name on a translucent board chip below. Size clamp(36px, 10.6vw, 48px); the subs strip uses clamp(32px, 9vw, 40px). Corner badges: yellow armband C or white V at top right (17px, 4px corners), ink "×2" (fixture count) at top left, a white letter disc with an ink ring for "rival owns him too" at bottom left, an amber doubt disc carrying a warning triangle at bottom right. Press scales to 0.96. Every counter is a button that opens the player sheet.

### Out-Lane Ghost
Outgoing players stand in a dashed-ruled lane at the left edge of the board labelled "Out": a transparent disc with a 2px dashed red ring, red figure, red struck-through name, no gloss, no shadow. Ghosts in the same row fan out vertically so several transfers never overlap.

### Marker Arrow and Annotation
The board is a 100 by 98 field (aspect ratio 100/98). Each transfer is a red marker stroke (1.15 units, round caps, 1.5 when selected) from the ghost to the incoming counter, with an arrowhead. On load or re-solve the strokes draw in over 640ms on the standard ease, staggered 120ms plus 140ms per arrow. The gain is written in marker above the arrow's midpoint, rotated -4 degrees. Selecting a move dims the other arrows and gains to 28%. With no transfers, the lane carries a marker note ("Roll it"). The figcaption key underneath explains the xPts figure, the arrow and the rival mark in type.

### Race Board
The League screen's board: the same frame and melamine at 100 by 62. The rival is the level line (ink-3, 1px) with their white letter disc at its right end; your gap after each gameweek is a black marker stroke (0.95 units, round caps and joins) above level when you're ahead, below when behind. Past today it continues as a dotted marker stroke on the model's weekly edge, inside a board-line band one weekly swing wide per square root of weeks ahead. Today is a hairline in frame colour with your blue magnet (clamp(26px, 7.4vw, 32px), gloss, magnet shadow) set on the line. Gridlines are board-line hairlines; values, "Level", GW ticks and "Projected" are set in the 10px label face, today's GW in ink. One marker note writes the weekly edge on the side away from level, repeating the plate's "Edge per GW". The key names the magnet, both strokes and the level line, and a "Gameweek by gameweek" table below types every point, played and projected. On load or rival change the stroke draws over 640ms after 120ms; band, dots and note fade in from 780ms, and the magnet is set down from a lift at 760ms. Reduced motion shows it all in place.

### Reversed Plate
The one dark object on the screen: plate background, 10px radius, panel shadow, 14px 16px padding. Head in 22px title type with the bank and free transfers right-aligned in plate-mute. Each row: the move in 16px bold, the proof line in plate-mute, the stance against the rival in plate-text, and the gain right-aligned in condensed yellow with its horizon caption. Rows are buttons separated by plate-2 rules; hover lifts to 4% white, pressed carries an 8% yellow wash, focus rings are yellow. It closes with three totals in 22px condensed and a plate-mute note.

### Stake Figure
The gap to the chosen rival as the screen's one display-scale figure, condensed, red when behind and blue when ahead, with "behind Rival" (the rival is a dashed-underline select), league position, weekly edge and finish chance in 13.5px beside it. Without a rival it shows total points in ink.

### Subs Strip
A board-coloured panel (12px radius, panel shadow) titled with the 10px label "Subs, in order", holding small counters in bench order. A bench transfer shows the ghost, a red arrow icon, then the incoming counter.

### Sheets
Player and Options sheets are native dialogs on the board colour: a bottom sheet on phones (16px top corners, max 88dvh, rising 24px over 320ms), a 420px right-side sheet from 960px (sliding 32px). The backdrop fades in over 240ms. Sticky head with a 20px title and a 40px round close button.

### Buttons and Controls
- **Primary** (the team ID submit): magnet blue, white 800 text, 10px radius, 52px tall, the primary shadow; deep blue on hover, presses down 1px. Disabled at 75% opacity with a progress cursor.
- **Secondary**: white on the board, 1.5px board-line border, 8px radius, 42px; border darkens to ink-3 on hover.
- **Pill toggles** (lock, ban, Options): white, 1.5px border, 99px radius, 40px; pressed fills with ink.
- **Segments** (free transfers, horizon): 40px white tiles with a 1.5px border; checked fills magnet blue.
- **Team ID field**: white, 2px ink border, 10px radius, 52px, 17px text; focus turns the border blue with a 3px blue halo at 35%; invalid turns it red.
- **Focus**: everywhere else a 2px magnet-blue outline at 2px offset.

### Navigation
Phone: a fixed five-tab bar (Plan, League, Squad, Players, More) with stroke icons over 11px labels in ink-3; the current tab is magnet blue and bold. Desktop: a sticky 216px rail on wall-deep with the product name, 8px-radius items in ink-2, the current item lifted onto a board-coloured chip with the panel shadow and blue-deep text, and "switch team" pinned to the bottom.

### Unknown Team
An empty framed board (frame-light 7px border, 100:56) with a marker note, "No counters on the board", rotated -3 degrees in ink-3, then the error in title type and an inline compact team ID form to try again. The wordmark sits above it.

### Loading
Ghost board and plate shapes in the frame and board colours breathe between 55% and 100% opacity on a 1.4s alternate loop.

## Do's and Don'ts

### Do:
- **Do** keep exactly one reversed plate (plate on plate-text) per screen; everything else sits on the wall or the board.
- **Do** keep exactly one display-scale figure per viewport, condensed at width 72%, against small labels.
- **Do** pair every magnet colour with a shape, letter or word: C and V, dashed ring plus strikethrough, the rival letter disc, "behind"/"ahead".
- **Do** give everything drawn on the board a typed equivalent: the plate lists every move, the key explains every mark.
- **Do** put each claim beside its proof: a move's stat line sits directly under it, a landing claim sits beside its demonstration.
- **Do** keep player rows to the same fields in the same places across plate, sheet and tables.
- **Do** use the standard ease (cubic-bezier(0.16, 1, 0.3, 1)) for lifts, sheets, chevrons and the arrow draw; 160 to 320ms for state, 640ms for the stroke.
- **Do** honour reduced motion: all animations and transitions collapse to 0.01ms, arrows appear fully drawn, sheets appear in place, the loading ghost holds still.

### Don't:
- **Don't** add a dark theme or a `prefers-color-scheme` branch; the board is a light object used in daylight.
- **Don't** set data, labels, buttons or headings in Permanent Marker, or let a marker figure be the only place a value appears.
- **Don't** use blue, red or yellow for anything but their magnet meanings, and don't put yellow text on the board.
- **Don't** add a second reversed plate, a second display figure, or a stack of stat cards; the board carries the screen.
- **Don't** put an uppercase eyebrow above a headline; the 10px uppercase label is for board markings and component labels only.
- **Don't** set the product name as a tracked-caps eyebrow above a heading; the wordmark is 17px 800 in sentence case on its own row.
- **Don't** introduce a second grotesque or a separate display face; use Archivo's width axis.
- **Don't** let anything animate on its own after the arrows are drawn, except the loading ghost.
