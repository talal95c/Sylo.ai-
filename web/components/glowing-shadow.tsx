"use client";

import { motion, type HTMLMotionProps } from "framer-motion";
import type { ReactNode } from "react";
import { cx } from "./ui";

interface GlowingShadowProps extends Omit<HTMLMotionProps<"section">, "children"> {
  children: ReactNode;
  panelClassName?: string;
}

export function GlowingShadow({
  children,
  className,
  panelClassName,
  ...props
}: GlowingShadowProps) {
  return (
    <motion.section
      className={cx("group relative isolate rounded-[18px]", className)}
      {...props}
    >
      <span
        aria-hidden="true"
        className="pointer-events-none absolute -inset-[3px] -z-10 rounded-[21px] bg-[var(--accent)] opacity-[0.035] blur-[8px] transition-[opacity,filter] duration-300 ease-out group-hover:opacity-[0.09] group-hover:blur-[10px] motion-reduce:transition-none"
      />
      <span
        aria-hidden="true"
        className="pointer-events-none absolute -inset-px -z-10 rounded-[19px] opacity-60 ring-1 ring-[rgba(1,43,255,0.08)] transition-opacity duration-300 ease-out group-hover:opacity-100 motion-reduce:transition-none"
      />
      <div className={cx("card relative z-0 h-full w-full rounded-[18px]", panelClassName)}>
        {children}
      </div>
    </motion.section>
  );
}
