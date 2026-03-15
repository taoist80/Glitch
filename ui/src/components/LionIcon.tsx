interface LionIconProps {
  size?: number;
  className?: string;
}

/**
 * Custom lion head icon — used for the Auri tab in the sidebar.
 * Lucide does not include a lion glyph, so this is hand-drawn SVG.
 * Designed at 24×24 grid; scales cleanly at 16–32px.
 */
export function LionIcon({ size = 24, className }: LionIconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-label="Lion"
    >
      {/* Mane — 16-point starburst */}
      <path
        d="M12 1.5 L13.1 4.8 L16.2 3 L15.4 6.4 L18.8 5.8 L17.2 8.8 L20.5 9.8
           L17.8 12 L20.5 14.2 L17.2 15.2 L18.8 18.2 L15.4 17.6 L16.2 21
           L13.1 19.2 L12 22.5 L10.9 19.2 L7.8 21 L8.6 17.6 L5.2 18.2
           L6.8 15.2 L3.5 14.2 L6.2 12 L3.5 9.8 L6.8 8.8 L5.2 5.8
           L8.6 6.4 L7.8 3 L10.9 4.8 Z"
        strokeWidth="1.1"
      />
      {/* Face */}
      <circle cx="12" cy="12" r="5.2" />
      {/* Eyes */}
      <circle cx="10.3" cy="11" r="0.85" fill="currentColor" stroke="none" />
      <circle cx="13.7" cy="11" r="0.85" fill="currentColor" stroke="none" />
      {/* Nose */}
      <path d="M11.2 13 L12 14.3 L12.8 13 Z" fill="currentColor" strokeWidth="0.4" />
      {/* Mouth */}
      <path d="M10.6 14.7 Q12 15.6 13.4 14.7" strokeWidth="1" />
    </svg>
  );
}
