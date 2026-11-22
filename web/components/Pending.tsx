import styles from "./Pending.module.css";

/** Placeholder for sections not rebuilt yet; says what's coming and where it exists today. */
export default function Pending({ title, what }: { title: string; what: string }) {
  return (
    <section className={styles.wrap}>
      <h1>{title}</h1>
      <p>{what}</p>
      <p className={styles.note}>
        This section is still being rebuilt for the web. It already works in the local dashboard:{" "}
        <code>python fpl_agent.py ui</code>.
      </p>
    </section>
  );
}
