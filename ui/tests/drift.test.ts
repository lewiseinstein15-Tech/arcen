// CI drift test: ui/src/types/events.ts must mirror src/arcen/stream/events.py
// name-for-name (FRONTEND-SPEC Part 17). This test reads the backend source
// and fails when the two lists drift apart.

import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { EVENT_TYPES } from '../src/types/events';

const BACKEND = '../../src/arcen/stream/events.py';

const backendTypes = (): string[] => {
  const source = readFileSync(new URL(BACKEND, import.meta.url), 'utf-8');
  const match = source.match(/EVENT_TYPES:\s*tuple\[str,\s*\.\.\.\]\s*=\s*\(([\s\S]*?)\)/);
  if (!match) throw new Error('EVENT_TYPES not found in backend schema');
  return [...match[1].matchAll(/"([a-z.]+)"/g)].map((m) => m[1]);
};

describe('frontend/backend event schema drift', () => {
  it('ui/types/events.ts matches backend events.py exactly', () => {
    const py = backendTypes();
    expect(py).toHaveLength(17);
    expect(EVENT_TYPES).toEqual(py);
  });
});
