// Inline icon set for the admin shell (§ UX plan, phase 2).
//
// Hand-rolled rather than an icon package: this is a dozen 16px paths against a
// project with two runtime dependencies, and a package would be the third — for
// roughly 400 bytes of geometry.
//
// Every icon is `aria-hidden` and `focusable="false"`. Icons here are always
// paired with a text label (visible, or visually hidden when the rail is
// collapsed), so an icon that announced itself would say everything twice.

import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function Icon({ size = 16, children, ...rest }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {children}
    </svg>
  );
}

export function IconProjects(p: IconProps) {
  return (
    <Icon {...p}>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </Icon>
  );
}

export function IconTemplates(p: IconProps) {
  return (
    <Icon {...p}>
      <path d="M12 3 3 7.5l9 4.5 9-4.5L12 3Z" />
      <path d="m3 12.5 9 4.5 9-4.5" />
      <path d="m3 17 9 4.5 9-4.5" />
    </Icon>
  );
}

export function IconMarketplace(p: IconProps) {
  return (
    <Icon {...p}>
      <path d="M3 8h18l-1.2 11a2 2 0 0 1-2 1.8H6.2a2 2 0 0 1-2-1.8L3 8Z" />
      <path d="M8.5 8V6a3.5 3.5 0 1 1 7 0v2" />
    </Icon>
  );
}

export function IconReview(p: IconProps) {
  return (
    <Icon {...p}>
      <path d="M21 11.5a8.5 8.5 0 1 1-4.2-7.3" />
      <path d="m8.5 11.5 3 3 8-8.5" />
    </Icon>
  );
}

export function IconNew(p: IconProps) {
  return (
    <Icon {...p}>
      <path d="M12 5v14M5 12h14" />
    </Icon>
  );
}

export function IconLabel(p: IconProps) {
  return (
    <Icon {...p}>
      <path d="M12.6 3H5a2 2 0 0 0-2 2v7.6a2 2 0 0 0 .6 1.4l7.4 7.4a2 2 0 0 0 2.8 0l6.6-6.6a2 2 0 0 0 0-2.8L13 3.6a2 2 0 0 0-.4-.6Z" />
      <circle cx="8" cy="8" r="1.2" fill="currentColor" stroke="none" />
    </Icon>
  );
}

export function IconCollapse(p: IconProps) {
  return (
    <Icon {...p}>
      <path d="m14 6-6 6 6 6" />
      <path d="M18 4v16" />
    </Icon>
  );
}

export function IconExpand(p: IconProps) {
  return (
    <Icon {...p}>
      <path d="m10 6 6 6-6 6" />
      <path d="M6 4v16" />
    </Icon>
  );
}

export function IconMenu(p: IconProps) {
  return (
    <Icon {...p}>
      <path d="M4 6h16M4 12h16M4 18h16" />
    </Icon>
  );
}

export function IconClose(p: IconProps) {
  return (
    <Icon {...p}>
      <path d="m6 6 12 12M18 6 6 18" />
    </Icon>
  );
}

export function IconKey(p: IconProps) {
  return (
    <Icon {...p}>
      <circle cx="7.5" cy="15.5" r="3.5" />
      <path d="M10 13 20 3" />
      <path d="m16 7 2.5 2.5" />
    </Icon>
  );
}

export function IconSun(p: IconProps) {
  return (
    <Icon {...p}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.2 4.2l1.5 1.5M18.3 18.3l1.5 1.5M2 12h2M20 12h2M4.2 19.8l1.5-1.5M18.3 5.7l1.5-1.5" />
    </Icon>
  );
}

export function IconMoon(p: IconProps) {
  return (
    <Icon {...p}>
      <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z" />
    </Icon>
  );
}

export function IconChevronRight(p: IconProps) {
  return (
    <Icon {...p}>
      <path d="m9 6 6 6-6 6" />
    </Icon>
  );
}
