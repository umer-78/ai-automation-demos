// Adapted from Magic UI "Animated List" (MIT): reveals items one after another, in order,
// in step with the packets in the 3D scene. Shows everything at once when reduced motion is on.
import { Children, isValidElement, useEffect, useState, type ReactNode } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";

export function RevealList({ children, delay = 450, className }: { children: ReactNode; delay?: number; className?: string }) {
  const items = Children.toArray(children);
  const reduced = useReducedMotion();
  const [count, setCount] = useState(reduced ? items.length : 1);

  useEffect(() => {
    if (count >= items.length) return;
    const t = setTimeout(() => setCount((n) => n + 1), delay);
    return () => clearTimeout(t);
  }, [count, items.length, delay]);

  return (
    <ol className={className}>
      <AnimatePresence initial={false}>
        {items.slice(0, reduced ? items.length : count).map((item, i) => (
          <motion.li
            key={isValidElement(item) && item.key != null ? item.key : i}
            layout
            initial={{ opacity: 0, y: 6, scale: 0.985 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            transition={{ type: "spring", stiffness: 350, damping: 40 }}
          >
            {item}
          </motion.li>
        ))}
      </AnimatePresence>
    </ol>
  );
}
