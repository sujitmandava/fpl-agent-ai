"use client";

import { useEffect, useRef } from "react";
import { X } from "lucide-react";
import styles from "./Sheet.module.css";

/** Bottom sheet on phones, side drawer on desktop. Native <dialog>: focus trap and Esc come free. */
export default function Sheet({
  open, onClose, title, children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className={styles.sheet}
      aria-label={title}
      onClose={onClose}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose(); // tap on the backdrop
      }}
    >
      <div className={styles.body}>
        <div className={styles.head}>
          <h2>{title}</h2>
          <button type="button" className={styles.close} onClick={onClose} aria-label="Close">
            <X size={20} aria-hidden />
          </button>
        </div>
        {children}
      </div>
    </dialog>
  );
}
