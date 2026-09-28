/** @jsxRuntime automatic */
/*
 * Meridyen loader "Orbit": the ONE loading indicator used by every OS app.
 * Canonical source: platform/shared/ui/spinner/ (generated together with
 * spinner.css; vendored into each app by scripts/sync-spinner.sh; never edit a
 * vendored copy).
 *
 * The two halves of the Meridyen mark sit at different depths and orbit each
 * other around a glowing sparkle that always faces the viewer.
 *
 *   <Spinner />                 inherits font size + text colour
 *   <Spinner size={16} />       explicit pixel size
 *   <Spinner tone="brand" />    Meridyen blue with glint, glow and shadow
 *   <LoadingState label="…" />  centred brand loader for a page / panel / list
 *
 * The CSS ships inside the component so it works in every app (Next, Vite,
 * SSR, React 18/19) with no global stylesheet wiring. The outer box is static,
 * so layout/transform classes passed in never fight the animation.
 */
import type { CSSProperties } from "react";

const CSS = `:where(.mx-spinner-box){display:inline-flex;flex:none;width:var(--mx-size,1em);height:var(--mx-size,1em);vertical-align:middle}:where(.mx-loading-state){box-sizing:border-box;display:flex;flex:1 1 auto;flex-direction:column;align-items:center;justify-content:center;gap:12px;width:100%;height:100%;min-height:96px;padding:24px}:where(.mx-loading-caption){font-size:13px;opacity:.65}:root{--mx-mark: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 26.1 26.1'%3E%3Cpath d='M11.9,14.5c-.7-.7-4.9-1.2-6.2-1.4-.2,0-.2-.3,0-.4,1.3-.2,5.5-.7,6.2-1.4.7-.7,1.2-6.7,1.4-10.8,0-.3-.3-.6-.6-.5C12.7,0,5.8,1.8,4,12.9c0,0,0,.3-.4.3s-.3-.3-.3-.3c0-4,.9-8.7,3.8-11.5.3-.3,0-.7-.4-.5-.5.3-1,.7-1.5,1.1C2,4.5,0,8.5,0,12.9c0,7.5,5.7,12.6,12.8,13,.3,0,.5-.2.5-.6-.2-4.1-.7-10.1-1.4-10.8Z'/%3E%3Cpath d='M14.8,2.4c-.2,0-.4.2-.4.4.2,3.3.6,8.2,1.2,8.8.6.6,4,1,5,1.2.2,0,.2.3,0,.3-1,.2-4.5.6-5,1.2-.6.6-1,5.4-1.1,8.7,0,.3.2.5.5.4,0,0,5.6-1.4,7.1-10.5,0,0,0-.2.3-.2s.3.2.3.2c0,3.2-.8,7-3.1,9.3-.2.2,0,.6.3.4.4-.3.8-.6,1.2-.9,2.5-2.1,4.2-5.3,4.2-8.9,0-6.1-4.6-10.3-10.4-10.5Z'/%3E%3C/svg%3E");--mx-half-l: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 26.1 26.1'%3E%3Cpath d='M11.9,14.5c-.7-.7-4.9-1.2-6.2-1.4-.2,0-.2-.3,0-.4,1.3-.2,5.5-.7,6.2-1.4.7-.7,1.2-6.7,1.4-10.8,0-.3-.3-.6-.6-.5C12.7,0,5.8,1.8,4,12.9c0,0,0,.3-.4.3s-.3-.3-.3-.3c0-4,.9-8.7,3.8-11.5.3-.3,0-.7-.4-.5-.5.3-1,.7-1.5,1.1C2,4.5,0,8.5,0,12.9c0,7.5,5.7,12.6,12.8,13,.3,0,.5-.2.5-.6-.2-4.1-.7-10.1-1.4-10.8Z'/%3E%3C/svg%3E");--mx-half-r: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 26.1 26.1'%3E%3Cpath d='M14.8,2.4c-.2,0-.4.2-.4.4.2,3.3.6,8.2,1.2,8.8.6.6,4,1,5,1.2.2,0,.2.3,0,.3-1,.2-4.5.6-5,1.2-.6.6-1,5.4-1.1,8.7,0,.3.2.5.5.4,0,0,5.6-1.4,7.1-10.5,0,0,0-.2.3-.2s.3.2.3.2c0,3.2-.8,7-3.1,9.3-.2.2,0,.6.3.4.4-.3.8-.6,1.2-.9,2.5-2.1,4.2-5.3,4.2-8.9,0-6.1-4.6-10.3-10.4-10.5Z'/%3E%3C/svg%3E");--mx-spark: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 26.1 26.1'%3E%3Cpath d='M13.05,6.8C13.5,11.4,14.7,12.6,19.3,13.05C14.7,13.5,13.5,14.7,13.05,19.3C12.6,14.7,11.4,13.5,6.8,13.05C11.4,12.6,12.6,11.4,13.05,6.8Z'/%3E%3C/svg%3E")}.mx-orbit{--mx-fill-l: currentColor;--mx-fill-r: currentColor;--mx-glow: transparent;position: relative;display: block;width: var(--mx-size,1em);height: var(--mx-size,1em);perspective: calc(var(--mx-size,1em) * 3.2)}.mx-orbit.mx-brand{--mx-fill-l: linear-gradient(140deg,#9ccbff 0%,#3d8bff 45%,#0052cc 100%);--mx-fill-r: linear-gradient(140deg,#6fb0ff 0%,#0066ee 50%,#003a99 100%);--mx-glow: #5aa2ff}.mx-orbit .mx-rig,.mx-orbit .mx-half,.mx-orbit .mx-glint,.mx-orbit .mx-face,.mx-orbit .mx-spark{position: absolute;inset: 0}.mx-orbit .mx-rig{transform-style: preserve-3d;animation: mx-orbit 2.6s linear infinite}.mx-orbit .mx-half{overflow: hidden;-webkit-mask: var(--mx-m) center / contain no-repeat;mask: var(--mx-m) center / contain no-repeat}.mx-orbit .mx-l{--mx-m: var(--mx-half-l);background: var(--mx-fill-l);transform: translate3d(-4%,0,calc(var(--mx-size,1em) * 0.2))}.mx-orbit .mx-r{--mx-m: var(--mx-half-r);background: var(--mx-fill-r);transform: translate3d(4%,0,calc(var(--mx-size,1em) * -0.2))}.mx-orbit:not(.mx-brand) .mx-r{opacity: 0.82}.mx-orbit .mx-glint{display: none}.mx-orbit.mx-brand .mx-glint{display: block;opacity: 0.55;background: linear-gradient(105deg,transparent 40%,rgba(255,255,255,0.85) 50%,transparent 60%);background-size: 320% 100%;animation: mx-glint 1.3s ease-in-out infinite}.mx-orbit .mx-face{filter: drop-shadow(0 0 calc(var(--mx-size,1em) * 0.06) var(--mx-glow));animation: mx-face 2.6s linear infinite}.mx-orbit .mx-spark{background: currentColor;-webkit-mask: var(--mx-spark) center / contain no-repeat;mask: var(--mx-spark) center / contain no-repeat;animation: mx-twinkle 1.3s ease-in-out infinite}.mx-orbit.mx-brand .mx-spark{background: #fff}.mx-orbit .mx-shadow{display: none}.mx-orbit.mx-brand .mx-shadow{display: block;position: absolute;left: 18%;right: 18%;bottom: -16%;height: 9%;border-radius: 50%;background: radial-gradient(closest-side,rgba(0,60,160,0.3),transparent);animation: mx-shadow 1.3s ease-in-out infinite}@keyframes mx-orbit{from{transform: rotateX(-16deg) rotateY(0deg)}to{transform: rotateX(-16deg) rotateY(360deg)}}@keyframes mx-face{from{transform: rotateY(0deg)}to{transform: rotateY(-360deg)}}@keyframes mx-twinkle{0%,100%{opacity: 0.7;transform: scale(0.55) rotate(0deg)}50%{opacity: 1;transform: scale(0.95) rotate(45deg)}}@keyframes mx-glint{0%{background-position: 120% 0}55%,100%{background-position: -40% 0}}@keyframes mx-shadow{0%,100%{transform: scaleX(1)}50%{transform: scaleX(0.7)}}.mx-spinner{display: inline-block;flex: none;width: var(--mx-size,1em);height: var(--mx-size,1em);vertical-align: middle;background: currentColor;-webkit-mask: var(--mx-mark) center / contain no-repeat;mask: var(--mx-mark) center / contain no-repeat;animation: mx-spin 2.6s linear infinite}.mx-spinner>*{display: none}@keyframes mx-spin{from{transform: perspective(8em) rotateX(-16deg) rotateY(0deg)}to{transform: perspective(8em) rotateX(-16deg) rotateY(360deg)}}@media (prefers-reduced-motion: reduce){.mx-orbit *,.mx-spinner{animation-duration: 8s !important}}`;

export interface SpinnerProps {
  /** Pixel number or any CSS length. Defaults to 1em (the surrounding text size). */
  size?: number | string;
  /** "current" follows the text colour (default); "brand" paints the Meridyen blue. */
  tone?: "current" | "brand";
  className?: string;
  style?: CSSProperties;
  /** Accessible name. Pass null when adjacent text already says it is loading. */
  label?: string | null;
}

export function Spinner({ size, tone = "current", className, style, label = "Loading" }: SpinnerProps) {
  const sized =
    size == null ? style : ({ "--mx-size": typeof size === "number" ? `${size}px` : size, ...style } as CSSProperties);
  return (
    <span
      role={label ? "status" : undefined}
      aria-label={label ?? undefined}
      aria-hidden={label ? undefined : true}
      className={className ? `mx-spinner-box ${className}` : "mx-spinner-box"}
      style={sized}
    >
      <span className={tone === "brand" ? "mx-orbit mx-brand" : "mx-orbit"} aria-hidden="true">
        <span className="mx-shadow" />
        <span className="mx-rig">
          <span className="mx-half mx-l">
            <span className="mx-glint" />
          </span>
          <span className="mx-half mx-r">
            <span className="mx-glint" />
          </span>
          <span className="mx-face">
            <span className="mx-spark" />
          </span>
        </span>
      </span>
      <style>{CSS}</style>
    </span>
  );
}

export interface LoadingStateProps {
  /** Visible caption under the loader (also its accessible name). */
  label?: string;
  size?: number;
  className?: string;
  style?: CSSProperties;
}

/**
 * Centred brand loader (+ optional caption) filling its container: pages, panels, lists.
 * Layout lives in a zero-specificity rule, so the caller's classes (min-h-screen,
 * h-full, py-*) always win and the loader stays centred where it is placed.
 * Sizes: page / app boot = PAGE_LOADER_SIZE, panel = 28 (default), inline = Spinner.
 */
export const PAGE_LOADER_SIZE = 48;

export function LoadingState({ label, size = 28, className, style }: LoadingStateProps) {
  return (
    <div className={className ? `mx-loading-state ${className}` : "mx-loading-state"} style={style}>
      <Spinner size={size} tone="brand" label={label ?? "Loading"} />
      {label ? <span className="mx-loading-caption">{label}</span> : null}
    </div>
  );
}

export default Spinner;
