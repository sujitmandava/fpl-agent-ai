import styles from "./Pending.module.css";

/** Placeholder for sections not built yet; says what's coming and what to use meanwhile. */
export default function Pending({ title, what }: { title: string; what: string }) {
  return (
    <section className={styles.wrap}>
      <h1>{title}</h1>
      <p>{what}</p>
      <p className={styles.note}>
        This section isn't built yet. Meanwhile, the terminal covers most of it:{" "}
        <code>python fpl_agent.py status</code>.
      </p>
    </section>
  );
}
