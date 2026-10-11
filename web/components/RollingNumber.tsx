"use client";

import { motion } from "framer-motion";
import { cx } from "./ui";

const DIGITS = "0123456789";
const LINE = 1.15;

/** A figure whose digits roll like an odometer when it changes; the decimals are dimmed. */
export function RollingNumber({ value, className }: { value: string; className?: string }) {
  const chars = [...value];
  const minorFrom = value.search(/\.\d{1,2}$/);
  return (
    <span className={cx("inline-flex font-mono tabular-nums", className)} aria-label={value} role="text">
      {chars.map((char, index) => {
        const key = chars.length - index;
        const minor = minorFrom >= 0 && index >= minorFrom;
        return DIGITS.includes(char) ? (
          <Digit key={`d${key}`} digit={Number(char)} minor={minor} />
        ) : (
          <span
            key={`s${key}${char}`}
            aria-hidden
            className={cx("inline-block", minor && "text-ink-3")}
            style={{ height: `${LINE}em`, lineHeight: `${LINE}em` }}
          >
            {char}
          </span>
        );
      })}
    </span>
  );
}

function Digit({ digit, minor }: { digit: number; minor: boolean }) {
  return (
    <span
      aria-hidden
      className={cx("relative inline-block overflow-hidden", minor && "text-ink-3")}
      style={{ height: `${LINE}em`, width: "1ch" }}
    >
      <motion.span
        className="absolute inset-x-0 top-0 flex flex-col"
        initial={false}
        animate={{ y: `${-digit * LINE}em` }}
        transition={{ type: "spring", stiffness: 210, damping: 26, mass: 0.8 }}
      >
        {[...DIGITS].map((item) => (
          <span key={item} style={{ height: `${LINE}em`, lineHeight: `${LINE}em` }}>
            {item}
          </span>
        ))}
      </motion.span>
    </span>
  );
}
