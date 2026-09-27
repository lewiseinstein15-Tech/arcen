import '@testing-library/jest-dom';

// quiet the fetch noise: tests drive stores/components directly
(globalThis as Record<string, unknown>).fetch ??= (() => Promise.resolve(new Response('{}', { status: 200 })));
