import { motion, MotionConfig } from "motion/react";
import type { ElementType } from "react";

/**
 * Words that arrive out of a blur, one after another. Adapted from React Bits' BlurText
 * (blur effect, top direction, load trigger), trimmed to what the hero needs.
 */
export default function BlurText({ text, as: Tag = "h1", className, stagger = 0.07, delay = 0.15 }: { text: string; as?: ElementType; className?: string; stagger?: number; delay?: number }) {
  const words = text.split(" ");
  return (
    <MotionConfig reducedMotion="user">
      <Tag className={className}>
        <span className="sr-only">{text}</span>
        {words.map((w, i) => (
          <motion.span
            key={`${w}-${i}`}
            aria-hidden="true"
            className="inline-block will-change-[transform,filter,opacity]"
            initial={{ filter: "blur(10px)", opacity: 0, y: -32 }}
            animate={{ filter: ["blur(10px)", "blur(5px)", "blur(0px)"], opacity: [0, 0.5, 1], y: [-32, 3, 0] }}
            transition={{ delay: delay + i * stagger, duration: 0.75, times: [0, 0.5, 1], ease: [0.22, 1, 0.36, 1] }}
          >
            {w}
            {i < words.length - 1 ? " " : ""}
          </motion.span>
        ))}
      </Tag>
    </MotionConfig>
  );
}
