// ARCEN — collapsible chevron: one glyph, rotated by state.
// ▾ open / ▸ closed (visually, via transform — DOM text stays stable).

import { memo } from 'react';

export const Chevron = memo(function Chevron({ open }: { open: boolean }) {
  return (
    <span className={`chev ${open ? '' : 'is-closed'}`} aria-hidden="true">
      ▾
    </span>
  );
});
