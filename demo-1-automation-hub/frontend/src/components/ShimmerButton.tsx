// Adapted from Magic UI "Shimmer Button" (MIT). Used once, for the hero's main action.
import type { ButtonHTMLAttributes, CSSProperties } from "react";
import { cn } from "../lib/cn";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  shimmerColor?: string;
  background?: string;
}

export function ShimmerButton({ shimmerColor = "#9BE7DE", background = "#0F2A3F", className, children, type = "button", ...props }: Props) {
  return (
    <button
      type={type}
      style={{ "--spread": "90deg", "--shimmer-color": shimmerColor, "--radius": "12px", "--speed": "3s", "--cut": "0.08em", "--bg": background } as CSSProperties}
      className={cn(
        "group relative z-0 flex h-12 cursor-pointer items-center justify-center overflow-hidden [border-radius:var(--radius)] border border-white/10 px-6 font-semibold whitespace-nowrap text-white [background:var(--bg)]",
        "transform-gpu transition-transform duration-300 ease-in-out active:translate-y-px",
        className,
      )}
      {...props}
    >
      <div className="-z-30 blur-[2px] @container-[size] absolute inset-0 overflow-visible">
        <div className="animate-shimmer-slide absolute inset-0 aspect-[1] h-[100cqh] rounded-none [mask:none]">
          <div className="animate-spin-around absolute -inset-full w-auto [translate:0_0] rotate-0 [background:conic-gradient(from_calc(270deg-(var(--spread)*0.5)),transparent_0,var(--shimmer-color)_var(--spread),transparent_var(--spread))]" />
        </div>
      </div>
      {children}
      <div className="absolute inset-0 size-full rounded-[inherit] shadow-[inset_0_-8px_10px_#ffffff1f] transition-all duration-300 ease-in-out group-hover:shadow-[inset_0_-6px_10px_#ffffff3f] group-active:shadow-[inset_0_-10px_10px_#ffffff3f]" />
      <div className="absolute inset-(--cut) -z-20 [border-radius:var(--radius)] [background:var(--bg)]" />
    </button>
  );
}
