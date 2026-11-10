// Small set of styled primitives used across pages.
import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
} from "react";
import styles from "./Primitives.module.css";

export function Button({
  variant = "primary",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
}) {
  return (
    <button {...rest} className={`${styles.btn} ${styles[variant]} ${rest.className ?? ""}`} />
  );
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${styles.input} ${props.className ?? ""}`} />;
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={`${styles.card} ${className ?? ""}`}>{children}</div>;
}

export function Field({
  label,
  children,
  error,
}: {
  label: string;
  children: ReactNode;
  error?: string;
}) {
  return (
    <label className={styles.field}>
      <span className={styles.fieldLabel}>{label}</span>
      {children}
      {error ? <span className={styles.fieldError}>{error}</span> : null}
    </label>
  );
}

