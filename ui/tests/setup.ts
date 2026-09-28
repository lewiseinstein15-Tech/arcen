import '@testing-library/jest-dom';

// jsdom shims required by Vaul/Radix (drawer) — pointer events + matchMedia
if (typeof window !== 'undefined' && !window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

if (typeof window !== 'undefined' && !('PointerEvent' in window)) {
  class FakePointerEvent extends MouseEvent {
    pointerId = 1;
    isPrimary = true;
    pointerType = 'mouse';
  }
  (window as unknown as { PointerEvent: unknown }).PointerEvent = FakePointerEvent;
}

if (typeof window !== 'undefined' && !('visualViewport' in window)) {
  Object.defineProperty(window, 'visualViewport', {
    configurable: true,
    value: { width: 375, height: 667, addEventListener: () => {}, removeEventListener: () => {} },
  });
}

// ResizeObserver shim (Radix/Vaul measure drawer content)
if (typeof globalThis !== 'undefined' && !('ResizeObserver' in globalThis)) {
  (globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

// quiet the fetch noise: tests drive stores/components directly
(globalThis as Record<string, unknown>).fetch ??= (() => Promise.resolve(new Response('{}', { status: 200 })));

// jsdom has no scrolling — the auto-scroll hook calls scrollTo with options
if (typeof Element !== 'undefined' && !Element.prototype.scrollTo) {
  Element.prototype.scrollTo = function scrollTo() {
    /* no-op: tests stub geometry via property defines where needed */
  };
}
