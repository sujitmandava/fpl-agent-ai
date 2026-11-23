---
version: 1
slug: "web-app-team-id-league-page-tsx"
primary_target: "web/app/team/[id]/league/page.tsx"
related_targets: ["web/components/LeagueView.tsx"]
---

# League

Mode: Operate. A section inside the established app shell and the Dressing-Room Tactics Board world (DESIGN.md); inherits the world, decides composition only.

Audience and job: a manager checking where they stand in their mini-league and whether they are catching the rival they care about. Success: they know the gap, whether it is shrinking, what the model expects next, and which of their players and the rival's actually move it. Proof: weekly points history from public data, the head-to-head projection, rivals' squads, captains and chips as of the last deadline. Constraints: rivals' picks are only public after each deadline; the finish chance is a rough normal approximation and must say so; colour never the only signal; the board has a typed equivalent.

## Direction contract

THESIS: The league race drawn on the tactics board: your points gap to one rival, week by week, as a marker line crossing the board, carried past today by the model's projected edge inside a band of honest uncertainty. It refuses the category's standings-table-first page and the stack of stat cards.

OWN-WORLD: The same framed white melamine board on the grey wall. The rival is the board's centre line ("level"); your gap is a black marker stroke above or below it; the projection continues as a dotted marker stroke inside a pale board-line band; today is your blue magnet on the line. GW ticks set in the 10px label face like board markings. One marker note annotates the weekly edge and repeats a figure the plate sets in type. One reversed plate, "Head to head", lists edge, swing, finish chance, captains and chips.

STORY: The visitor sees the gap as the display figure, sees at a glance whether the line is climbing toward level, reads the projection and its spread, checks the plate for why, switches rival from the stake line or a standings row and watches the line redraw, then scrolls to the standings, the players that separate the two squads, and who the league owns.

FIRST VIEWPORT: Phone: wordmark row, title (league name, after GWn), stake line with the gap as the one display figure and the rival picker, the framed race board full width, the top of the plate. Desktop: rail left, board left column, plate right. Primary action: change the rival (stake picker or a standings row).

FORM: Race to the line, the dealt lead (THE ROLL) chosen by the user over Split board and League template. seed:112dfde771301638. Raises carried: one reversed plate; one display figure; every claim beside its proof; player rows keep the same fields in the same places; nothing labelled twice.

FINISH: unreviewed is unfinished; this build ends with the detector, captures at phone and desktop, and the finish review.

Signature interaction: choosing a rival redraws the race line in one marker stroke (640ms, standard ease); reduced motion shows it drawn.

Open decisions: none new.
