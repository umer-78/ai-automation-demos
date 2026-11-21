// Adapted from Magic UI "Number Ticker" (MIT). Counts to a new value whenever it changes.
import { useEffect, useRef, type ComponentPropsWithoutRef } from "react";
import { useInView, useMotionValue, useReducedMotion, useSpring } from "motion/react";
import { cn } from "../lib/cn";

interface Props extends ComponentPropsWithoutRef<"span"> {
  value: number;
  decimalPlaces?: number;
  prefix?: string;
}

const format = (n: number, places: number, prefix: string) =>
  prefix + Intl.NumberFormat("en-US", { minimumFractionDigits: places, maximumFractionDigits: places }).format(Number(n.toFixed(places)));

export function NumberTicker({ value, decimalPlaces = 0, prefix = "", className, ...props }: Props) {
  const ref = useRef<HTMLSpanElement>(null);
  const reduced = useReducedMotion();
  const motionValue = useMotionValue(0);
  const spring = useSpring(motionValue, { damping: 60, stiffness: 100 });
  const inView = useInView(ref, { once: true });

  useEffect(() => {
    if (!inView) return;
    if (reduced) spring.jump(value);
    else motionValue.set(value);
  }, [inView, reduced, value, motionValue, spring]);

  useEffect(
    () => spring.on("change", (latest) => { if (ref.current) ref.current.textContent = format(latest, decimalPlaces, prefix); }),
    [spring, decimalPlaces, prefix],
  );

  return (
    <span ref={ref} className={cn("inline-block", className)} aria-label={format(value, decimalPlaces, prefix)} {...props}>
      {format(0, decimalPlaces, prefix)}
    </span>
  );
}
