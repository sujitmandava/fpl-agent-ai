---
version: 1
slug: "web-app-team-id-page-tsx"
primary_target: "web/app/team/[id]/page.tsx"
related_targets: ["web/app/layout.tsx"]
---

# Plan (Suggestions) and app shell

Mode: Operate. Phone-first working screen inside the app shell (bottom tab bar on phone: Plan, League, Squad, Players, More; left rail on desktop). Only the shell and Plan are designed in full now; other sections get the shell and the world.

Audience and job: a manager in the days before the deadline who wants this week's moves and how they play against their mini-league rival. Success: they can make the moves on the FPL site without another tab, and know why. Proof: every move, the captain and the lineup carry the stats behind them (player sheet on tap). Constraints: public data only, no Premier League branding, colour never the only signal, the board has a list equivalent.

## Direction contract

THESIS: The gameweek drawn on a dressing-room tactics board: your XI as magnetic counters, each transfer a marker arrow swapping one counter for another. It refuses the category's dark stat-card dashboard and the plain lineup table.

OWN-WORLD: White melamine board in a brushed-aluminium frame on a cool grey wall; counters are glossy magnets, blue for your players, red for incoming, a dashed red ring for outgoing, a yellow armband for the captain; annotations in black or red marker; data set in a condensed workhorse grotesque with tabular figures. Marker lettering only ever annotates, never carries data. Counters your rival also owns carry a shared mark; differentials stay bare.

STORY: The visitor sees how far they are from their rival, sees exactly which counters to move and what each move is worth, taps any counter or move to see the evidence, adjusts options and watches the arrows redraw, then makes the moves on FPL.

FIRST VIEWPORT: Phone: top bar (product name, GW and deadline); stake line with the gap to the rival as the one display-scale figure, rank and weekly edge beside it; the board, full width, about half the screen, counters in formation with arrows and gain annotations; the moves strip under it, each move followed by its proof line; bottom tab bar. Desktop: rail left, board centre, moves and proof in a right panel. Primary action: tap a move or counter to open its player sheet.

FORM: Dressing-Room Tactics Board, IMPECCABLE'S PICK (position 1 on the ordered list; the roll assigned position 4, the Matchday Programme, and the user chose the pick). seed:5a2ea8218325360b. Raises carried from the round: one reversed plate per screen; one display-scale figure against small labels; every claim beside its proof; player rows keep the same fields in the same places; nothing labelled twice.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

Signature interaction: selecting a move lifts both counters and redraws its marker arrow in a single stroke; changing options re-solves and the arrows redraw in place. Reduced motion: arrows appear without the stroke.

Chosen sketch: .impeccable/mocks/decision/tactics-board.html (composition, palette, type, density the build must match).

Open decisions: product name (working name FPL Agent); exact faces; the shared-with-rival mark; settings stored in the browser for the hosted version.
