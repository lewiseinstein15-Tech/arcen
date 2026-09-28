// ARCEN — logo mark: two overlapping triangles forming a mountain peak /
// stylized "A". Solid coral fill, left triangle slightly shorter than the
// right (reference brief). Fill resolves from tokens.css via var(--accent).

export function LogoMark({ height = 40, className }: { height?: number; className?: string }) {
  const width = Math.round(height * 1.2); // 48 × 40 at default
  return (
    <svg
      width={width}
      height={height}
      viewBox="0 0 48 40"
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      <polygon points="4,36 16,12 28,36" fill="var(--accent)" opacity="0.55" />
      <polygon points="20,36 33,6 46,36" fill="var(--accent)" />
    </svg>
  );
}
