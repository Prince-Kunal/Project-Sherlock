"use client";

import {
  motion,
  useMotionTemplate,
  useMotionValue,
  useReducedMotion,
  useSpring,
} from "motion/react";
import Image, { type StaticImageData } from "next/image";
import { useRef } from "react";

import { cn } from "@/lib/utils";

const LENS = 92; // radius in px of the magnified area on screen
const ZOOM = 1.9;

/**
 * A Paget engraving under a magnifying glass: the lens follows the pointer and shows the plate
 * enlarged and inked in the brand colour. Pointer-only and off under reduced motion; everyone
 * else sees the plain illustration. Pointer position lives in motion values, never React state.
 */
export function LensImage({
  src,
  alt,
  priority = false,
  className,
  sizes,
}: {
  src: StaticImageData;
  alt: string;
  priority?: boolean;
  className?: string;
  sizes: string;
}) {
  const reduce = useReducedMotion();
  const box = useRef<HTMLDivElement>(null);
  const x = useMotionValue(-999);
  const y = useMotionValue(-999);
  const sx = useSpring(x, { stiffness: 500, damping: 40, mass: 0.4 });
  const sy = useSpring(y, { stiffness: 500, damping: 40, mass: 0.4 });
  const visible = useMotionValue(0);
  const opacity = useSpring(visible, { stiffness: 300, damping: 30 });

  const clip = useMotionTemplate`circle(${LENS / ZOOM}px at ${sx}px ${sy}px)`;
  const origin = useMotionTemplate`${sx}px ${sy}px`;
  const rimX = useMotionTemplate`calc(${sx}px - ${LENS}px)`;
  const rimY = useMotionTemplate`calc(${sy}px - ${LENS}px)`;

  const move = (event: React.PointerEvent) => {
    if (event.pointerType !== "mouse" || !box.current) return;
    const rect = box.current.getBoundingClientRect();
    x.set(event.clientX - rect.left);
    y.set(event.clientY - rect.top);
    visible.set(1);
  };

  return (
    <div
      ref={box}
      onPointerMove={reduce ? undefined : move}
      onPointerLeave={() => visible.set(0)}
      className={cn("relative isolate select-none", className)}
    >
      <Image
        src={src}
        alt={alt}
        priority={priority}
        sizes={sizes}
        placeholder="blur"
        className="paget h-auto w-full"
      />
      {!reduce && (
        <>
          <motion.div
            aria-hidden="true"
            className="bg-background pointer-events-none absolute inset-0"
            style={{
              clipPath: clip,
              scale: ZOOM,
              transformOrigin: origin,
              opacity,
            }}
          >
            <Image
              src={src}
              alt=""
              sizes={sizes}
              className="paget h-auto w-full contrast-125"
            />
            <div className="bg-brand absolute inset-0 opacity-25 mix-blend-color" />
          </motion.div>
          <motion.div
            aria-hidden="true"
            className="pointer-events-none absolute top-0 left-0"
            style={{ x: rimX, y: rimY, opacity }}
          >
            <div
              className="border-brand rounded-full border-[3px] shadow-[0_10px_40px_-10px_rgb(0_0_0/0.45),inset_0_0_0_1px_rgb(255_255_255/0.25)]"
              style={{ width: LENS * 2, height: LENS * 2 }}
            />
            <div
              className="bg-foreground absolute h-3 w-16 origin-left rounded-full"
              style={{
                left: LENS + LENS * Math.SQRT1_2,
                top: LENS + LENS * Math.SQRT1_2 - 6,
                rotate: "45deg",
              }}
            />
          </motion.div>
        </>
      )}
    </div>
  );
}
