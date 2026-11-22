import TeamForm from "@/components/TeamForm";
import SampleBoard from "@/components/SampleBoard";
import { fetchModelCheck } from "@/lib/api";
import styles from "./page.module.css";

export const revalidate = 21600;

export default async function Landing() {
  const check = await fetchModelCheck();

  return (
    <div className={styles.page}>
      <header className={styles.bar}>
        <span className={styles.brand}>FPL Agent</span>
        <span className={styles.barNote}>Free · no login</span>
      </header>

      <section className={styles.hero}>
        <div className={styles.pitch}>
          <h1>Plan your gameweek to beat your mini-league.</h1>
          <p className={styles.lede}>
            Transfers, captain and chips for this deadline, with the stats behind every pick.
          </p>
          <TeamForm autoFocus />
          <p className={styles.small}>Uses public FPL data. It never touches your FPL account; you make the moves.</p>
        </div>
        <div className={styles.demo}>
          <SampleBoard />
        </div>
      </section>

      <section className={styles.band}>
        <div className={styles.copy}>
          <h2>Every pick comes with its reasons.</h2>
          <p>
            Each move shows why: expected minutes, goals and assists per 90, the fixture, how often he&apos;s
            returned. Tap any player for the full picture, and lock or ban players and the plan re-solves around you.
          </p>
        </div>
        <div className={styles.plate} aria-label="Sample move">
          <div className={styles.plateRow}>
            <div>
              <p className={styles.plateWhat}>Saka → Palmer</p>
              <p className={styles.plateProof}>WOL (H) · 88 mins · xG/90 0.38 · xA/90 0.29 · returned 8/11</p>
              <p className={styles.plateStance}>Dan owns Palmer: cover</p>
            </div>
            <p className={`${styles.plateGain} cond`}>+7.8<span>6 GWs</span></p>
          </div>
          <div className={styles.plateRow}>
            <div>
              <p className={styles.plateWhat}>Captain Haaland</p>
              <p className={styles.plateProof}>LEE (H) · vice Salah</p>
              <p className={styles.plateStance}>Dan captains Salah: your swing pick</p>
            </div>
            <p className={`${styles.plateGain} cond`}>9.2<span>xPts</span></p>
          </div>
          <p className={styles.plateTag}>Sample</p>
        </div>
      </section>

      <section className={`${styles.band} ${styles.flip}`}>
        <div className={styles.copy}>
          <h2>Your league is the scoreboard.</h2>
          <p>
            Pick the rival you&apos;re chasing. See the gap, your expected edge each week, a rough chance of finishing
            above them, and which of your players actually move the gap. Shared players cancel out; differentials and
            captains decide it.
          </p>
        </div>
        <div className={styles.stake} aria-label="Sample league position">
          <p className={`${styles.stakeFig} cond`}>−12</p>
          <div>
            <p><b>behind Dan Hughes</b></p>
            <p>3rd of 14 in your league</p>
            <p>Your edge +1.4 xPts a week · about 38% to finish above Dan</p>
          </div>
          <p className={styles.plateTag}>Sample</p>
        </div>
      </section>

      <section className={styles.proof}>
        <h2>How often is it right?</h2>
        {check ? (
          <>
            <p className={styles.proofLede}>
              We replay the season: hide everything after an earlier gameweek, predict the next {check.horizon}, then
              check what really happened. The yardstick is the simplest guess, each player scoring his average so far.
            </p>
            <table className={styles.compare}>
              <thead>
                <tr>
                  <th scope="col"><span className="sr-only">Measure</span></th>
                  <th scope="col">FPL Agent</th>
                  <th scope="col">Simple guess</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th scope="row">Typical miss per player, per week <span>lower is better</span></th>
                  <td className={styles.win}>{check.model_miss.toFixed(1)} pts</td>
                  <td>{check.baseline_miss.toFixed(1)} pts</td>
                </tr>
                <tr>
                  <th scope="row">What its top 20 picks scored, each <span>higher is better</span></th>
                  <td className={styles.win}>{check.model_top20.toFixed(1)} pts</td>
                  <td>{check.baseline_top20.toFixed(1)} pts</td>
                </tr>
              </tbody>
            </table>
            <p className={styles.small}>
              {check.predictions.toLocaleString("en-GB")} predictions across GW{check.first_gw}–{check.last_gw}. FPL
              scores are lumpy: a forward who should get 5 gets 2 or 8 depending on one shot, so no model gets near
              zero. A typical regular scored {check.average_player.toFixed(1)}; perfect hindsight would have averaged{" "}
              {check.hindsight_top20.toFixed(1)}.
            </p>
          </>
        ) : (
          <p className={styles.proofLede}>
            The model is checked every week against a simple average-so-far guess. The latest results are shown in the
            app once you&apos;re in.
          </p>
        )}
      </section>

      <section className={styles.find}>
        <h2>Finding your team ID</h2>
        <ol>
          <li>Sign in at <a href="https://fantasy.premierleague.com" rel="noreferrer">fantasy.premierleague.com</a> and open the <b>Points</b> tab.</li>
          <li>The address shows <code>…/entry/<mark>1234567</mark>/event/12</code>. That number is your team ID.</li>
          <li>Paste the number, or the whole link, above or here.</li>
        </ol>
        <TeamForm compact />
      </section>

      <footer className={styles.foot}>
        <p>FPL Agent is an independent, free tool. Not affiliated with the Premier League or Fantasy Premier League.</p>
      </footer>
    </div>
  );
}
